"""`create --module`: resolve from the registry, wire compose, copy blob, pin record."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ignition_stack.cli import app
from ignition_stack.record import RECORD_DIR, RECORD_NAME

runner = CliRunner()


def _xdg(tmp_path: Path) -> dict[str, str]:
    return {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_CACHE_HOME": str(tmp_path / "cache")}


def _add_charts(make_modl, env: dict[str, str], *, version: str = "6.0.0", floor: str = "8.3.0") -> None:
    modl = make_modl(
        identifier="com.mussonindustrial.embr.charts",
        name="Embr Charts",
        version=version,
        required_ignition=floor,
        depends=("com.inductiveautomation.perspective",),
        filename=f"Embr-Charts-Ignition83-{version}.modl",
    )
    result = runner.invoke(app, ["modules", "add", str(modl)], env=env)
    assert result.exit_code == 0, result.output


def test_create_module_wires_compose_copies_blob_and_pins(make_modl, tmp_path: Path) -> None:
    env = _xdg(tmp_path)
    _add_charts(make_modl, env)

    out = tmp_path / "out"
    result = runner.invoke(app, ["create", "mystack", "--arch", "basic", "--module", "embr-charts", "--output-dir", str(out)], env=env)
    assert result.exit_code == 0, result.output
    assert "embr-charts -> 6.0.0" in result.output

    project = out / "mystack"
    compose = (project / "docker-compose.yaml").read_text(encoding="utf-8")
    # ACCEPT_MODULE_LICENSES / CERTS carry the resolved identifier.
    assert "com.mussonindustrial.embr.charts" in compose
    # The cached .modl is copied into the project so the stack is self-contained.
    assert (project / "modules" / "cache" / "Embr-Charts-Ignition83-6.0.0.modl").is_file()
    # The resolved version is pinned in the recorded config.
    record = (project / RECORD_DIR / RECORD_NAME).read_text(encoding="utf-8")
    assert "embr-charts" in record
    assert "6.0.0" in record


def test_create_module_force_enables_disabled_dependency(make_modl, tmp_path: Path) -> None:
    env = _xdg(tmp_path)
    _add_charts(make_modl, env)

    out = tmp_path / "out"
    result = runner.invoke(
        app,
        ["create", "s2", "--arch", "basic", "--module", "embr-charts", "--disable-builtin", "perspective", "--output-dir", str(out)],
        env=env,
    )
    assert result.exit_code == 0, result.output
    compose = (out / "s2" / "docker-compose.yaml").read_text(encoding="utf-8")
    # Disabling a built-in emits the whitelist; the module's own id AND its
    # disabled dependency (Perspective) must both be force-enabled in it.
    assert "GATEWAY_MODULES_ENABLED" in compose
    assert "com.mussonindustrial.embr.charts" in compose
    assert "com.inductiveautomation.perspective" in compose


def test_create_module_incompatible_with_stack_errors(make_modl, tmp_path: Path) -> None:
    env = _xdg(tmp_path)
    # Only an 8.1-line build is cached; the default stack is Ignition 8.3.6.
    modl = make_modl(identifier="com.x.charts", name="X", version="6.2.0", required_ignition="8.1.49", filename="X-Ignition81-6.2.0.modl")
    assert runner.invoke(app, ["modules", "add", str(modl)], env=env).exit_code == 0

    result = runner.invoke(app, ["create", "s3", "--arch", "basic", "--module", "x", "--output-dir", str(tmp_path / "o3")], env=env)
    assert result.exit_code == 2
    assert "compatible" in result.output


def test_create_module_pin_exact_version(make_modl, tmp_path: Path) -> None:
    env = _xdg(tmp_path)
    _add_charts(make_modl, env, version="6.0.0", floor="8.3.0")
    _add_charts(make_modl, env, version="6.1.0", floor="8.3.5")

    out = tmp_path / "out"
    result = runner.invoke(app, ["create", "s4", "--arch", "basic", "--module", "embr-charts@6.0.0", "--output-dir", str(out)], env=env)
    assert result.exit_code == 0, result.output
    # The explicit pin wins over the newer 6.1.0 that would otherwise resolve.
    assert "embr-charts -> 6.0.0" in result.output
