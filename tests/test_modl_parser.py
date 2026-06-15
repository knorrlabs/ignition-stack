"""Parsing real-shaped module.xml descriptors out of a .modl zip."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from ignition_stack.catalog.modl import ModlParseError, ModuleDescriptor


def test_parses_all_fields(make_modl) -> None:
    modl = make_modl(
        identifier="com.mussonindustrial.embr.charts",
        name="Embr Charts",
        version="6.0.0.2026060403",
        required_ignition="8.3.0",
        depends=("com.inductiveautomation.perspective",),
        filename="Embr-Charts-Ignition83-6.0.0.modl",
    )
    d = ModuleDescriptor.from_modl(modl)
    assert d.identifier == "com.mussonindustrial.embr.charts"
    assert d.name == "Embr Charts"
    assert d.version == "6.0.0.2026060403"
    assert d.required_ignition_version == "8.3.0"
    assert d.ignition_line == "8.3"
    assert d.framework_version == "8"
    assert d.free_module is True
    assert d.depends == ("com.inductiveautomation.perspective",)


def test_line_derived_from_floor(make_modl) -> None:
    modl = make_modl(required_ignition="8.1.49")
    assert ModuleDescriptor.from_modl(modl).ignition_line == "8.1"


def test_non_zip_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.modl"
    bad.write_bytes(b"definitely not a zip")
    with pytest.raises(ModlParseError):
        ModuleDescriptor.from_modl(bad)


def test_zip_without_module_xml_rejected(tmp_path: Path) -> None:
    p = tmp_path / "x.modl"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("readme.txt", "no descriptor here")
    with pytest.raises(ModlParseError):
        ModuleDescriptor.from_modl(p)


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    p = tmp_path / "x.modl"
    xml = '<?xml version="1.0"?>\n<modules><module><name>X</name></module></modules>'
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("module.xml", xml)
    with pytest.raises(ModlParseError):
        ModuleDescriptor.from_modl(p)
