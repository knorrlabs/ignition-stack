"""Top-level Typer application.

Phase 2 implements ``init`` for the standalone+Postgres walking skeleton.
Phase 3 wires the real ``modules`` sub-app (catalog list/validate/download);
``reset`` and ``wipe`` remain visible placeholders so the command surface
is stable from day one, with later phases filling them in.

Phase 6 widens ``init`` with ``--profile``, ``--spokes``, ``--force``, and
``--edge-role`` for the four architecture profiles, and falls into the
interactive wizard when no profile is named.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from ignition_stack import __version__
from ignition_stack.commands.modules import modules_app
from ignition_stack.compose import write_project
from ignition_stack.config import ProjectConfig
from ignition_stack.profiles import (
    ProfileError,
    ProfileOptions,
    build_profile,
    get_profile,
    list_profiles,
)
from ignition_stack.wizard import run_wizard

app = typer.Typer(
    name="ignition-stack",
    help="Generate ready-to-run Docker Compose stacks for Ignition 8.3 SCADA demos.",
    add_completion=False,
    rich_markup_mode="rich",
)
app.add_typer(modules_app, name="modules")

console = Console()


# invoke_without_command=True lets the eager --version handler fire on bare
# `ignition-stack --version`. Typer's `no_args_is_help` short-circuits the
# callback when no subcommand is given, which swallowed --version and made
# it look like the command was missing; handling the "no subcommand" case
# manually here keeps both behaviours: --version prints, bare call shows help.
@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show ignition-stack version and exit.",
        is_eager=True,
    ),
) -> None:
    if version:
        console.print(f"ignition-stack {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


def _profile_help() -> str:
    """Format the available profiles for ``--profile`` help text."""
    lines = ["Architecture profile to materialize (skips the wizard):"]
    for p in list_profiles():
        lines.append(f"  - {p.slug}: {p.summary}")
    return "\n".join(lines)


@app.command()
def init(
    name: str = typer.Argument(
        ...,
        help="Project name. Becomes the directory, the compose project, and the gateway name.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help=_profile_help(),
    ),
    spokes: int = typer.Option(
        3,
        "--spokes",
        help="Spoke gateway count for the hub-and-spoke profile (ignored otherwise).",
        min=0,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Bypass the hub-and-spoke red-tier RAM advisory.",
    ),
    edge_role: str | None = typer.Option(
        None,
        "--edge-role",
        help=(
            "Gateway role that runs the Ignition Edge edition. Scaleout defaults "
            "to 'frontend'; hub-and-spoke defaults its spokes to Edge. Pass 'none' "
            "to disable the profile's edge default; pass a role name ('hub', "
            "'gateway', ...) to opt that specific role in."
        ),
    ),
    output_dir: Path | None = typer.Option(  # noqa: B008 - Typer pattern
        None,
        "--output-dir",
        "-o",
        help="Parent directory the project is written into. Defaults to the current directory.",
    ),
) -> None:
    """Generate a new Ignition stack at ``<output-dir>/<name>``.

    With ``--profile``, runs non-interactively from the named profile and its
    flags. Without ``--profile``, walks the interactive wizard.
    """
    target = ((output_dir or Path.cwd()) / name).resolve()

    # Name validation runs before either the wizard or the profile build so
    # invalid names fail fast with a clear exit code (2), instead of bubbling
    # through the wizard's first prompt or the profile's deep model_validate.
    try:
        ProjectConfig(name=name)
    except ValueError as exc:
        console.print(f"[red]error[/red]: invalid project name: {exc}")
        raise typer.Exit(code=2) from exc

    if profile is None:
        config = _run_wizard_or_exit(name)
    else:
        config = _build_from_profile(name, profile, spokes, force, edge_role)

    try:
        files = write_project(config, target)
    except FileExistsError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]created[/green] {target}")
    console.print(f"  {len(files)} file(s) written")
    console.print()
    console.print("Next steps:")
    console.print(f"  cd {target}")
    console.print("  docker compose up -d")
    console.print(
        f"  open http://localhost:{config.gateways[0].http_port}  (admin / {config.admin_password})"
    )


def _build_from_profile(
    name: str, profile: str, spokes: int, force: bool, edge_role: str | None
) -> ProjectConfig:
    """Materialize a config from the named profile + CLI flags, or exit cleanly."""
    try:
        get_profile(profile)
    except KeyError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=2) from exc

    options = ProfileOptions(spokes=spokes, force=force, edge_role=edge_role)
    try:
        config = build_profile(profile, name, options)
    except ProfileError as exc:
        # Red-tier advisory: exit code 3 keeps it distinguishable from a config
        # error (2) or a generic write failure (1), so callers and tests can
        # branch on it explicitly.
        console.print(f"[red]advisory[/red]: {exc}")
        raise typer.Exit(code=3) from exc
    except ValueError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=2) from exc
    return config


def _run_wizard_or_exit(name: str) -> ProjectConfig:
    """Run the interactive wizard, surfacing cancellation as a clean non-zero exit."""
    try:
        return run_wizard(name)
    except KeyboardInterrupt as exc:
        console.print("[yellow]cancelled[/yellow]")
        raise typer.Exit(code=130) from exc


@app.command()
def reset() -> None:
    """Reset a generated project to a clean baseline. (placeholder; arrives in Phase 7)"""
    console.print(
        "[yellow]ignition-stack reset[/yellow] is not yet implemented. "
        "Arrives in Phase 7 (lifecycle modes)."
    )
    raise typer.Exit(code=2)


@app.command()
def wipe() -> None:
    """Remove this project's containers and volumes. (placeholder; arrives in Phase 7)"""
    console.print(
        "[yellow]ignition-stack wipe[/yellow] is not yet implemented. "
        "Arrives in Phase 7 (lifecycle modes)."
    )
    raise typer.Exit(code=2)


if __name__ == "__main__":  # pragma: no cover
    app()
