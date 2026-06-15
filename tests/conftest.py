"""Shared fixtures: an ephemeral local HTTP file server used in place of
the real Cirrus Link / IA download endpoints. Stdlib only.
"""

from __future__ import annotations

import contextlib
import threading
import zipfile
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def file_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """Serve ``tmp_path`` over HTTP on an ephemeral port.

    Yields ``(base_url, served_dir)``. Files written into ``served_dir``
    after the fixture starts are visible.
    """
    served_dir = tmp_path / "served"
    served_dir.mkdir()

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(_QuietHandler, directory=str(served_dir)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}", served_dir
    finally:
        server.shutdown()
        with contextlib.suppress(Exception):
            server.server_close()
        thread.join(timeout=2)


def _module_xml(*, identifier: str, name: str, version: str, required_ignition: str, framework: str = "8", free: bool = True, depends: tuple[str, ...] = ()) -> str:
    """A minimal but realistic module.xml body (mirrors real Embr descriptors)."""
    deps = "".join(f'    <depends scope="GD">{d}</depends>\n' for d in depends)
    free_text = "true" if free else "false"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<modules>\n  <module>\n"
        f"    <name>{name}</name>\n"
        f"    <id>{identifier}</id>\n"
        f"    <version>{version}</version>\n"
        f"    <requiredIgnitionVersion>{required_ignition}</requiredIgnitionVersion>\n"
        f"    <freeModule>{free_text}</freeModule>\n"
        f"{deps}"
        f"    <requiredFrameworkVersion>{framework}</requiredFrameworkVersion>\n"
        "  </module>\n</modules>\n"
    )


@pytest.fixture
def make_modl(tmp_path: Path):
    """Factory building a synthetic ``.modl`` (a zip holding a module.xml) on disk."""

    def _factory(
        *,
        identifier: str = "com.example.demo",
        name: str = "Demo Module",
        version: str = "1.0.0",
        required_ignition: str = "8.3.0",
        framework: str = "8",
        free: bool = True,
        depends: tuple[str, ...] = (),
        filename: str = "Demo.modl",
        dest: Path | None = None,
    ) -> Path:
        target_dir = dest or tmp_path
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / filename
        xml = _module_xml(identifier=identifier, name=name, version=version, required_ignition=required_ignition, framework=framework, free=free, depends=depends)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("module.xml", xml)
            zf.writestr("demo-gateway.jar", b"\x00stub")
        return path

    return _factory
