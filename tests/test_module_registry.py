"""User registry store: cache layout, upsert integrity, removal."""

from __future__ import annotations

from pathlib import Path

import pytest

from ignition_stack.catalog.registry import RegistryEntry, RegistryError, RegistryStore
from ignition_stack.catalog.verify import sha256_of_file


def _store(tmp_path: Path) -> RegistryStore:
    return RegistryStore(config_dir=tmp_path / "cfg", cache_dir=tmp_path / "cache")


def _entry(
    *,
    version: str = "6.0.0",
    line: str = "8.3",
    floor: str = "8.3.0",
    name: str = "charts",
    ident: str = "com.x.charts",
    sha: str = "a" * 64,
    filename: str = "Charts.modl",
) -> RegistryEntry:
    return RegistryEntry(
        name=name,
        module_identifier=ident,
        module_version=version,
        min_ignition_version=floor,
        ignition_line=line,
        sha256=sha,
        install_path=f"/usr/local/bin/ignition/user-lib/modules/{filename}",
        source="test",
    )


def _blob(tmp_path: Path, name: str, content: bytes = b"data") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_add_moves_blob_and_persists(tmp_path: Path) -> None:
    store = _store(tmp_path)
    blob = _blob(tmp_path, "in.modl")
    entry = _entry(sha=sha256_of_file(blob))
    cached = store.add(entry, blob)

    assert cached.is_file()
    assert not blob.exists()  # moved, not copied
    assert "com.x.charts/6.0.0-ign83/Charts.modl" in cached.as_posix()
    loaded = store.load()
    assert len(loaded.entries) == 1
    assert store.cache_path(loaded.entries[0]).is_file()


def test_add_same_key_same_sha_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(_entry(sha="a" * 64), _blob(tmp_path, "a.modl"))
    second = _blob(tmp_path, "b.modl")
    store.add(_entry(sha="a" * 64), second)
    assert len(store.load().entries) == 1
    assert not second.exists()  # temp copy consumed, not duplicated


def test_add_same_key_different_sha_refuses(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(_entry(sha="a" * 64), _blob(tmp_path, "a.modl"))
    with pytest.raises(RegistryError):
        store.add(_entry(sha="b" * 64), _blob(tmp_path, "b.modl"))


def test_name_reused_for_other_identifier_refuses(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(_entry(name="charts", ident="com.x.charts", sha="a" * 64), _blob(tmp_path, "a.modl"))
    with pytest.raises(RegistryError):
        store.add(_entry(name="charts", ident="com.y.charts", version="1.0.0", sha="b" * 64), _blob(tmp_path, "b.modl"))


def test_multiple_versions_coexist_and_remove(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(_entry(version="6.0.0", filename="c60.modl", sha="a" * 64), _blob(tmp_path, "a.modl"))
    store.add(_entry(version="6.1.0", filename="c61.modl", sha="b" * 64), _blob(tmp_path, "b.modl"))
    assert len(store.load().entries) == 2

    removed = store.remove("charts", version="6.0.0")
    assert [e.module_version for e in removed] == ["6.0.0"]
    assert [e.module_version for e in store.load().entries] == ["6.1.0"]

    removed_rest = store.remove("charts")
    assert [e.module_version for e in removed_rest] == ["6.1.0"]
    assert store.load().entries == []
