"""CLI: `modules add` (path + URL), versions, remove, and list integration.

Isolation is via XDG env vars so each run reads/writes a scratch registry and
cache under tmp_path rather than the developer's real home.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ignition_stack.cli import app

runner = CliRunner()


def _xdg(tmp_path: Path) -> dict[str, str]:
    return {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_CACHE_HOME": str(tmp_path / "cache")}


def test_add_from_path_then_versions_then_remove(make_modl, tmp_path: Path) -> None:
    env = _xdg(tmp_path)
    modl = make_modl(
        identifier="com.mussonindustrial.embr.charts",
        name="Embr Charts",
        version="6.0.0",
        required_ignition="8.3.0",
        depends=("com.inductiveautomation.perspective",),
        filename="Embr-Charts-Ignition83-6.0.0.modl",
    )

    added = runner.invoke(app, ["modules", "add", str(modl)], env=env)
    assert added.exit_code == 0, added.output
    assert "embr-charts" in added.output
    assert "com.mussonindustrial.embr.charts" in added.output
    assert "depends on com.inductiveautomation.perspective" in added.output

    listed = runner.invoke(app, ["modules", "versions", "embr-charts"], env=env)
    assert listed.exit_code == 0, listed.output
    assert "6.0.0" in listed.output

    removed = runner.invoke(app, ["modules", "remove", "embr-charts"], env=env)
    assert removed.exit_code == 0, removed.output

    gone = runner.invoke(app, ["modules", "versions", "embr-charts"], env=env)
    assert gone.exit_code == 2


def test_add_from_url(make_modl, file_server, tmp_path: Path) -> None:
    base_url, served = file_server
    make_modl(
        identifier="com.mussonindustrial.embr.charts",
        name="Embr Charts",
        version="6.2.0",
        required_ignition="8.1.49",
        filename="Embr-Charts-Ignition81-6.2.0.modl",
        dest=served,
    )
    url = f"{base_url}/Embr-Charts-Ignition81-6.2.0.modl"

    result = runner.invoke(app, ["modules", "add", url], env=_xdg(tmp_path))
    assert result.exit_code == 0, result.output
    assert "line 8.1" in result.output


def test_add_rejects_non_modl(tmp_path: Path) -> None:
    bad = tmp_path / "bad.modl"
    bad.write_bytes(b"not a zip at all")
    result = runner.invoke(app, ["modules", "add", str(bad)], env=_xdg(tmp_path))
    assert result.exit_code == 2
    assert "valid .modl" in result.output


def test_list_includes_local_registry(make_modl, tmp_path: Path) -> None:
    env = _xdg(tmp_path)
    modl = make_modl(
        identifier="com.mussonindustrial.embr.charts",
        name="Embr Charts",
        version="6.0.0",
        required_ignition="8.3.0",
        filename="Embr-Charts-Ignition83-6.0.0.modl",
    )
    runner.invoke(app, ["modules", "add", str(modl)], env=env)

    listed = runner.invoke(app, ["modules", "list"], env=env)
    assert listed.exit_code == 0, listed.output
    assert "local registry" in listed.output
    assert "embr-charts" in listed.output
