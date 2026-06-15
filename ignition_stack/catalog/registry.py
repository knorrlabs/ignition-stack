"""The user-owned, global module registry + blob cache.

The bundled ``modules.yaml`` is the maintainer-curated, sha-pinned "blessed"
tier. This is the second tier: modules the *user* adds with
``ignition-stack modules add``. It persists globally (not per-project) so a
go-to module is registered once and reused across every stack.

Layout::

    $XDG_CONFIG_HOME/ignition-stack/registry.yaml   # the metadata entries
    $XDG_CACHE_HOME/ignition-stack/modules/          # the cached .modl blobs
        <identifier>/<version>-<line_tag>/<file>.modl

The cache key is ``(identifier, version, line)`` - not the install-path name the
bundled cache uses - so multiple versions, and the same version built for
different Ignition lines, coexist instead of overwriting one another.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RegistryError(Exception):
    """Raised on a registry integrity violation (sha conflict, name clash, bad file)."""


class RegistryEntry(BaseModel):
    """One cached third-party module build, keyed by ``(identifier, version, line)``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[
        str,
        Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$", description="User-facing slug; one slug maps to one module identifier."),
    ]
    module_identifier: Annotated[
        str,
        Field(min_length=1, pattern=r"^[a-z0-9.-]+$", description="Fully-qualified id from module.xml; verbatim in GATEWAY_MODULES_ENABLED."),
    ]
    module_version: Annotated[str, Field(min_length=1, description="The module's own <version> (3- or 4-part).")]
    min_ignition_version: Annotated[str, Field(min_length=1, description="Compatibility floor (>=) from <requiredIgnitionVersion>.")]
    ignition_line: Annotated[str, Field(pattern=r"^\d+\.\d+$", description="Major.minor line the build targets (e.g. 8.3).")]
    framework_version: str = Field(default="", description="Module-API contract version from <requiredFrameworkVersion>.")
    depends: tuple[str, ...] = Field(default=(), description="Dependency identifiers from <depends> (force-enabled in the whitelist).")
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", description="Lowercase hex sha256 of the cached artifact (trust-on-first-use).")]
    install_path: Annotated[str, Field(min_length=1, description="In-container destination under user-lib/modules/.")]
    requires_license_env: str | None = Field(default=None, description="Env var the user must set with a license key; None for free modules.")
    vendor: str = Field(default="third-party", description="Best-effort vendor (derived from the identifier).")
    source: Annotated[str, Field(min_length=1, description="The URL or path the module was added from.")]

    @property
    def line_tag(self) -> str:
        """Filesystem-safe line marker (``8.3`` -> ``ign83``), mirroring vendor naming."""
        return "ign" + self.ignition_line.replace(".", "")

    @property
    def cache_filename(self) -> str:
        """The artifact's filename inside the cache (the install-path basename)."""
        return PurePosixPath(self.install_path).name

    @property
    def cache_relpath(self) -> Path:
        """Path of the cached blob relative to the cache root."""
        return Path(self.module_identifier) / f"{self.module_version}-{self.line_tag}" / self.cache_filename


class Registry(BaseModel):
    """Top-level shape of registry.yaml."""

    model_config = ConfigDict(extra="forbid")

    version: Annotated[int, Field(default=1, ge=1)]
    entries: list[RegistryEntry] = Field(default_factory=list)

    def find(self, identifier: str, version: str, line: str) -> RegistryEntry | None:
        """The entry with this exact cache key, or None."""
        for e in self.entries:
            if e.module_identifier == identifier and e.module_version == version and e.ignition_line == line:
                return e
        return None


def default_config_dir() -> Path:
    """``$XDG_CONFIG_HOME/ignition-stack`` (or ``~/.config/ignition-stack``)."""
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "ignition-stack"


def default_cache_dir() -> Path:
    """``$XDG_CACHE_HOME/ignition-stack/modules`` (or ``~/.cache/...``)."""
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "ignition-stack" / "modules"


class RegistryStore:
    """Read/write access to the registry file and its blob cache.

    Both directories are injectable so tests (and a future ``--registry-dir``
    flag) can point at a scratch location instead of the user's real home.
    """

    def __init__(self, config_dir: Path | None = None, cache_dir: Path | None = None) -> None:
        self.config_dir = config_dir or default_config_dir()
        self.cache_dir = cache_dir or default_cache_dir()

    @property
    def registry_file(self) -> Path:
        return self.config_dir / "registry.yaml"

    def load(self) -> Registry:
        path = self.registry_file
        if not path.is_file():
            return Registry()
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise RegistryError(f"registry.yaml is not valid YAML: {exc}") from exc
        try:
            return Registry.model_validate(raw)
        except ValidationError as exc:
            raise RegistryError(f"registry.yaml failed validation:\n{exc}") from exc

    def save(self, registry: Registry) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            yaml.safe_dump(registry.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )

    def cache_path(self, entry: RegistryEntry) -> Path:
        return self.cache_dir / entry.cache_relpath

    def add(self, entry: RegistryEntry, blob: Path) -> Path:
        """Register ``entry`` and move its ``blob`` into the cache.

        Integrity rules:
          - same ``(id, version, line)`` already present with a *different* sha
            -> refuse (the user is re-adding a changed artifact under an existing
            pin);
          - same key + same sha -> idempotent (ensure the blob is cached, do not
            duplicate the entry);
          - the slug already maps to a *different* identifier -> refuse (a name
            collision would make resolution ambiguous).
        Returns the cache path the blob now lives at.
        """
        registry = self.load()

        for existing in registry.entries:
            if existing.name == entry.name and existing.module_identifier != entry.module_identifier:
                raise RegistryError(f"slug '{entry.name}' already maps to {existing.module_identifier}; choose another --name for {entry.module_identifier}")

        existing = registry.find(entry.module_identifier, entry.module_version, entry.ignition_line)
        if existing is not None and existing.sha256 != entry.sha256:
            raise RegistryError(f"{entry.name} {entry.module_version} (line {entry.ignition_line}) already registered with a different sha256; refusing to overwrite")

        target = self.cache_path(entry)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            blob.unlink(missing_ok=True)
        else:
            shutil.move(str(blob), str(target))

        if existing is None:
            registry.entries.append(entry)
            self.save(registry)
        return target

    def remove(self, name_or_id: str, version: str | None = None) -> list[RegistryEntry]:
        """Drop matching entries (and their cached blobs). Returns what was removed."""
        registry = self.load()
        removed: list[RegistryEntry] = []
        kept: list[RegistryEntry] = []
        for e in registry.entries:
            matches_name = name_or_id in (e.name, e.module_identifier)
            matches_version = version is None or e.module_version == version
            if matches_name and matches_version:
                removed.append(e)
            else:
                kept.append(e)
        if removed:
            registry.entries = kept
            self.save(registry)
            for e in removed:
                self.cache_path(e).unlink(missing_ok=True)
        return removed
