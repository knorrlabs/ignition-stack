"""Compatibility resolution: line + floor filter, then pick the newest build."""

from __future__ import annotations

import pytest

from ignition_stack.catalog.registry import RegistryEntry
from ignition_stack.catalog.resolver import ResolutionError, ignition_line_of, parse_version, resolve


def _e(version: str, line: str, floor: str, *, name: str = "charts", ident: str = "com.x.charts") -> RegistryEntry:
    return RegistryEntry(
        name=name,
        module_identifier=ident,
        module_version=version,
        min_ignition_version=floor,
        ignition_line=line,
        sha256="0" * 64,
        install_path="/usr/local/bin/ignition/user-lib/modules/X.modl",
        source="test",
    )


def test_picks_latest_compatible() -> None:
    entries = [_e("6.0.0", "8.3", "8.3.0"), _e("6.1.0", "8.3", "8.3.5"), _e("6.2.0", "8.1", "8.1.49")]
    assert resolve(entries, "charts", "8.3.6").module_version == "6.1.0"


def test_excludes_unsatisfied_floor() -> None:
    # 7.0.0 needs >= 8.3.9 but the gateway is 8.3.6, so it falls back to 6.0.0.
    entries = [_e("6.0.0", "8.3", "8.3.0"), _e("7.0.0", "8.3", "8.3.9")]
    assert resolve(entries, "charts", "8.3.6").module_version == "6.0.0"


def test_wrong_line_has_no_match() -> None:
    entries = [_e("6.2.0", "8.1", "8.1.49")]
    with pytest.raises(ResolutionError):
        resolve(entries, "charts", "8.3.6")


def test_unknown_module_errors() -> None:
    with pytest.raises(ResolutionError):
        resolve([], "nope", "8.3.6")


def test_resolves_by_identifier() -> None:
    entries = [_e("6.0.0", "8.3", "8.3.0")]
    assert resolve(entries, "com.x.charts", "8.3.6").module_version == "6.0.0"


def test_build_stamp_breaks_tie() -> None:
    assert parse_version("6.0.0.2026060403") > parse_version("6.0.0")


def test_ignition_line_of() -> None:
    assert ignition_line_of("8.3.6") == "8.3"
    assert ignition_line_of("8.1.49") == "8.1"
