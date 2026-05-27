"""Shared fixtures: an ephemeral local HTTP file server used in place of
the real Cirrus Link / IA download endpoints. Stdlib only.
"""

from __future__ import annotations

import contextlib
import threading
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
