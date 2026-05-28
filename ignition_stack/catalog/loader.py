"""Load and validate modules.yaml into the pydantic Catalog model."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml
from pydantic import ValidationError

from ignition_stack.catalog.schema import Catalog


class CatalogLoadError(Exception):
    """Raised when modules.yaml cannot be read or fails schema validation."""


DEFAULT_CATALOG_NAME = "modules.yaml"


def load_catalog(path: Path | None = None) -> Catalog:
    """Load and validate the catalog.

    When ``path`` is None, the catalog shipped with the installed package is
    loaded. Otherwise the file at ``path`` is used (test fixtures, alternate
    catalogs).
    """
    yaml_text = _read_yaml_text(path)
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise CatalogLoadError(f"modules.yaml is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise CatalogLoadError("modules.yaml top-level must be a mapping.")

    try:
        return Catalog.model_validate(raw)
    except ValidationError as exc:
        raise CatalogLoadError(f"modules.yaml failed schema validation:\n{exc}") from exc


def _read_yaml_text(path: Path | None) -> str:
    if path is not None:
        if not path.is_file():
            raise CatalogLoadError(f"Catalog not found at {path}.")
        return path.read_text(encoding="utf-8")

    # Installed wheels: modules.yaml is force-included as package data at
    # ignition_stack/modules.yaml. Editable dev installs: it lives at the
    # repo root next to pyproject.toml.
    try:
        bundled = resources.files("ignition_stack").joinpath(DEFAULT_CATALOG_NAME)
        if bundled.is_file():
            return bundled.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, ModuleNotFoundError):
        pass

    repo_root = Path(__file__).resolve().parents[2]
    dev_path = repo_root / DEFAULT_CATALOG_NAME
    if not dev_path.is_file():
        raise CatalogLoadError(
            f"Bundled catalog not found (looked for {dev_path}).",
        )
    return dev_path.read_text(encoding="utf-8")
