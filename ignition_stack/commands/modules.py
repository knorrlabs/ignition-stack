"""`ignition-stack modules` subcommands: list, validate, download."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Annotated
from urllib.parse import urlparse

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from ignition_stack.catalog.download import (
    DEFAULT_CACHE_DIR,
    DOWNLOAD_TIMEOUT_SECONDS,
    DownloadError,
    DownloadOutcome,
    download_entry,
)
from ignition_stack.catalog.loader import CatalogLoadError, load_catalog
from ignition_stack.catalog.modl import ModlParseError, ModuleDescriptor
from ignition_stack.catalog.registry import RegistryEntry, RegistryError, RegistryStore
from ignition_stack.catalog.resolver import candidates, parse_version
from ignition_stack.catalog.schema import SHA256_UNPINNED, ModuleEntry
from ignition_stack.catalog.verify import (
    REACHABILITY_TIMEOUT_SECONDS,
    VerifyIssue,
    sha256_of_file,
    verify_reachable,
)
from ignition_stack.completion import complete_module_name

modules_app = typer.Typer(help="Inspect and prepare the module + driver catalog.")
console = Console()
err_console = Console(stderr=True)

# In-container directory the gateway loads .modl files from; a cached artifact is
# mounted/copied here (mirrors the bundled catalog entries' install_path).
MODULES_INSTALL_DIR = "/usr/local/bin/ignition/user-lib/modules"

CatalogOpt = Annotated[
    Path | None,
    typer.Option("--catalog", help="Path to a modules.yaml. Defaults to the bundled catalog."),
]
IgnVerOpt = Annotated[
    str | None,
    typer.Option("--ignition-version", help="Filter to entries verified for this exact version."),
]


@modules_app.command("list")
def list_entries(
    catalog_path: CatalogOpt = None,
    ignition_version: IgnVerOpt = None,
) -> None:
    """Show every catalog entry as a table."""
    catalog = _load(catalog_path)
    entries = catalog.for_ignition(ignition_version) if ignition_version else catalog.entries
    table = Table(title="ignition-stack catalog")
    table.add_column("name")
    table.add_column("kind")
    table.add_column("vendor")
    table.add_column("ignition")
    table.add_column("identifier / driver")
    table.add_column("manual?")
    for e in entries:
        identifier = e.module_identifier if isinstance(e, ModuleEntry) else "(jdbc)"
        table.add_row(
            e.name,
            e.kind,
            e.vendor,
            ", ".join(e.ignition_versions),
            identifier,
            "yes" if e.requires_manual_download else "no",
        )
    console.print(table)
    _print_registry_section()


@modules_app.command("validate")
def validate(
    catalog_path: CatalogOpt = None,
    skip_network: Annotated[
        bool,
        typer.Option("--skip-network", help="Only validate the schema; skip URL reachability."),
    ] = False,
) -> None:
    """Confirm schema integrity, pinned shas, and (optionally) URL reachability."""
    catalog = _load(catalog_path)
    issues: list[VerifyIssue] = []

    for entry in catalog.entries:
        # Manual-download entries (e.g. EA-gated MCP) cannot be sha-pinned
        # while gated; flipping requires_manual_download to false at GA is
        # the moment the maintainer is expected to pin the sha.
        if entry.sha256 == SHA256_UNPINNED and not entry.requires_manual_download:
            issues.append(VerifyIssue(entry.name, "sha256 is UNPINNED"))

    if not skip_network:
        with httpx.Client(timeout=REACHABILITY_TIMEOUT_SECONDS) as client:
            for entry in catalog.entries:
                issue = verify_reachable(entry, client)
                if issue is not None:
                    issues.append(issue)

    if issues:
        err_console.print("[bold red]Catalog validation failed:[/bold red]")
        for issue in issues:
            err_console.print(f"  - {issue.entry_name}: {issue.reason}")
        raise typer.Exit(code=1)

    console.print(
        f"[green]OK[/green]: {len(catalog.entries)} entries valid" + (" (schema only)" if skip_network else " (schema + reachability)"),
    )


@modules_app.command("download")
def download(
    names: Annotated[
        list[str] | None,
        typer.Argument(
            help="Entries to download. Omit to download every non-manual entry.",
            autocompletion=complete_module_name,
        ),
    ] = None,
    catalog_path: CatalogOpt = None,
    ignition_version: IgnVerOpt = None,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="Destination directory for cached artifacts."),
    ] = DEFAULT_CACHE_DIR,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="No network calls. Fails if any selected entry is missing from the cache.",
        ),
    ] = False,
) -> None:
    """Materialise selected catalog entries into the host-side cache."""
    catalog = _load(catalog_path)

    selected = list(catalog.entries)
    if ignition_version:
        selected = [e for e in selected if ignition_version in e.ignition_versions]
    if names:
        wanted = set(names)
        present = {e.name for e in selected}
        missing = wanted - present
        if missing:
            err_console.print(
                f"[red]Unknown catalog entries:[/red] {', '.join(sorted(missing))}",
            )
            raise typer.Exit(code=2)
        selected = [e for e in selected if e.name in wanted]

    if not selected:
        err_console.print("[yellow]No catalog entries match the filters.[/yellow]")
        raise typer.Exit(code=2)

    had_error = False
    with httpx.Client() as client:
        for entry in selected:
            try:
                result = download_entry(entry, cache_dir, client=client, offline=offline)
            except DownloadError as exc:
                err_console.print(f"[red]ERROR[/red] {exc}")
                had_error = True
                continue
            style = {
                DownloadOutcome.DOWNLOADED: "green",
                DownloadOutcome.COPIED_FROM_LOCAL: "green",
                DownloadOutcome.SKIPPED_CACHED: "cyan",
                DownloadOutcome.SKIPPED_MANUAL: "yellow",
            }[result.outcome]
            console.print(f"[{style}]{result.outcome.value}[/{style}] {result.message}")

    if had_error:
        raise typer.Exit(code=1)


@modules_app.command("add")
def add(
    source: Annotated[str, typer.Argument(help="URL (http/https) or local path of a .modl to register.")],
    name: Annotated[str | None, typer.Option("--name", help="Override the auto-derived slug.")] = None,
    license_env: Annotated[str | None, typer.Option("--license-env", help="Env var holding the license key, for a non-free module.")] = None,
) -> None:
    """Register a third-party ``.modl`` in the local registry.

    Metadata (id, version, Ignition floor, line, dependencies, license-need) is
    read from the artifact's ``module.xml``; the sha256 is computed on add
    (trust-on-first-use). The original file/URL is never modified - a temp copy
    is what lands in the global cache.
    """
    store = RegistryStore()
    with tempfile.TemporaryDirectory() as td:
        try:
            blob, basename = _acquire(source, Path(td))
        except (httpx.HTTPError, OSError) as exc:
            err_console.print(f"[red]error[/red]: could not read {source}: {exc}")
            raise typer.Exit(code=1) from exc

        try:
            desc = ModuleDescriptor.from_modl(blob)
        except ModlParseError as exc:
            err_console.print(f"[red]error[/red]: {exc}")
            raise typer.Exit(code=2) from exc

        try:
            entry = RegistryEntry(
                name=name or _slugify(desc.name) or desc.identifier.rsplit(".", 1)[-1],
                module_identifier=desc.identifier,
                module_version=desc.version,
                min_ignition_version=desc.required_ignition_version,
                ignition_line=desc.ignition_line,
                framework_version=desc.framework_version,
                depends=desc.depends,
                sha256=sha256_of_file(blob),
                install_path=f"{MODULES_INSTALL_DIR}/{basename}",
                requires_license_env=None if desc.free_module else license_env,
                vendor=_vendor_of(desc.identifier),
                source=source,
            )
        except ValidationError as exc:
            err_console.print(f"[red]error[/red]: invalid module metadata: {exc}")
            raise typer.Exit(code=2) from exc

        try:
            cached = store.add(entry, blob)
        except RegistryError as exc:
            err_console.print(f"[red]error[/red]: {exc}")
            raise typer.Exit(code=1) from exc

    console.print(f"[green]added[/green] {entry.name}  ([cyan]{entry.module_identifier}[/cyan])")
    console.print(f"  version {entry.module_version} | line {entry.ignition_line} | requires Ignition >= {entry.min_ignition_version}")
    if desc.free_module:
        detail = "free module"
    elif entry.requires_license_env:
        detail = f"license env {entry.requires_license_env}"
    else:
        detail = "[yellow]licensed module - pass --license-env so the gateway accepts it[/yellow]"
    deps = (" | depends on " + ", ".join(entry.depends)) if entry.depends else ""
    console.print(f"  {detail}{deps}")
    console.print(f"  cached {cached} (sha {entry.sha256[:12]})")


@modules_app.command("versions")
def versions(
    name: Annotated[str, typer.Argument(help="Module slug or identifier to inspect.")],
) -> None:
    """Show every cached version of a module and the Ignition line each satisfies."""
    matches = candidates(_registry_entries(), name)
    if not matches:
        err_console.print(f"[yellow]no registered module matches '{name}'.[/yellow]")
        raise typer.Exit(code=2)
    table = Table(title=f"{name} - cached versions")
    table.add_column("version")
    table.add_column("line")
    table.add_column("min ignition")
    table.add_column("identifier")
    for e in sorted(matches, key=lambda e: (e.ignition_line, parse_version(e.module_version)), reverse=True):
        table.add_row(e.module_version, e.ignition_line, e.min_ignition_version, e.module_identifier)
    console.print(table)


@modules_app.command("remove")
def remove(
    name: Annotated[str, typer.Argument(help="Module slug or identifier to remove.")],
    version: Annotated[str | None, typer.Option("--version", help="Remove only this exact version; omit to remove every version.")] = None,
) -> None:
    """Remove a module (and its cached blob) from the local registry."""
    removed = RegistryStore().remove(name, version)
    if not removed:
        suffix = f" version {version}" if version else ""
        err_console.print(f"[yellow]nothing removed: no registry entry matches '{name}'{suffix}.[/yellow]")
        raise typer.Exit(code=2)
    for e in removed:
        console.print(f"[green]removed[/green] {e.name} {e.module_version} (line {e.ignition_line})")


def _acquire(source: str, tmp: Path) -> tuple[Path, str]:
    """Materialise a temp copy of ``source`` and return (blob_path, basename).

    A URL is streamed down; a path is copied. Either way the result is a throw-
    away temp file the registry move consumes, so the user's original artifact is
    never touched.
    """
    if source.startswith(("http://", "https://")):
        basename = PurePosixPath(urlparse(source).path).name or "module.modl"
        blob = tmp / basename
        with httpx.Client() as client, client.stream("GET", source, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            with blob.open("wb") as fp:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    fp.write(chunk)
        return blob, basename
    src = Path(source).expanduser()
    if not src.is_file():
        raise OSError(f"no such file: {src}")
    blob = tmp / src.name
    shutil.copy2(src, blob)
    return blob, src.name


def _slugify(text: str) -> str:
    """Best-effort slug from a display name (``Embr Charts`` -> ``embr-charts``)."""
    slug = "".join(ch if ch.isalnum() else "-" for ch in text.strip().lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _vendor_of(identifier: str) -> str:
    """Best-effort vendor from a reverse-DNS identifier (``com.x.y`` -> ``x``)."""
    parts = identifier.split(".")
    return parts[1] if len(parts) >= 2 else "third-party"


def _registry_entries() -> list[RegistryEntry]:
    try:
        return RegistryStore().load().entries
    except RegistryError as exc:
        err_console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1) from exc


def _print_registry_section() -> None:
    """Append the user-registry table to ``modules list`` when entries exist."""
    try:
        entries = RegistryStore().load().entries
    except RegistryError:
        return
    if not entries:
        return
    table = Table(title="local registry (added with `modules add`)")
    table.add_column("name")
    table.add_column("version")
    table.add_column("line")
    table.add_column("min ignition")
    table.add_column("identifier")
    for e in sorted(entries, key=lambda e: (e.name, e.ignition_line, parse_version(e.module_version))):
        table.add_row(e.name, e.module_version, e.ignition_line, e.min_ignition_version, e.module_identifier)
    console.print(table)


def _load(catalog_path: Path | None):
    try:
        return load_catalog(catalog_path)
    except CatalogLoadError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
