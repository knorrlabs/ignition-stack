"""Read an Ignition ``.modl`` artifact's ``module.xml`` descriptor.

A ``.modl`` is a ZIP whose root holds a ``module.xml`` descriptor. Everything
the version manager needs to register and resolve a third-party module is
declared there - so ``modules add`` can take just a URL or a file and learn the
rest from the artifact instead of asking the user to hand-type metadata.

Fields read (verified against real artifacts, e.g. Musson Industrial's Embr
Charts)::

    <id>                       fully-qualified module identifier (verbatim in
                               GATEWAY_MODULES_ENABLED / ACCEPT_MODULE_* )
    <name>                     display name
    <version>                  module's own version, 3- or 4-part
                               (semver + optional build-stamp tail)
    <requiredIgnitionVersion>  the compatibility FLOOR (>=), not an exact match
    <requiredFrameworkVersion> module-API contract version
    <freeModule>               true => no license env var needed
    <depends>                  zero or more dependency identifiers (e.g. a
                               Perspective component module depends on
                               com.inductiveautomation.perspective)

The same module ships a different ``<version>`` and floor per Ignition major
*line* (8.1 vs 8.3 are separate artifacts), which is why the resolver keys on
``(identifier, version, line)`` rather than name alone.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from ignition_stack.catalog.resolver import ignition_line_of

MODULE_XML_NAME = "module.xml"


class ModlParseError(Exception):
    """Raised when a file is not a readable .modl or its module.xml is malformed."""


@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    """The subset of ``module.xml`` the version manager cares about."""

    identifier: str
    name: str
    version: str
    required_ignition_version: str
    ignition_line: str
    framework_version: str
    free_module: bool
    depends: tuple[str, ...]

    @classmethod
    def from_modl(cls, path: Path) -> ModuleDescriptor:
        """Parse the ``module.xml`` out of a ``.modl`` zip at ``path``."""
        if not path.is_file():
            raise ModlParseError(f"not a file: {path}")
        try:
            with zipfile.ZipFile(path) as zf:
                if MODULE_XML_NAME not in zf.namelist():
                    raise ModlParseError(f"{path.name} is not a valid .modl: no {MODULE_XML_NAME} at the archive root")
                xml_bytes = zf.read(MODULE_XML_NAME)
        except zipfile.BadZipFile as exc:
            raise ModlParseError(f"{path.name} is not a valid .modl (not a zip archive): {exc}") from exc
        return cls.from_xml(xml_bytes)

    @classmethod
    def from_xml(cls, xml_bytes: bytes) -> ModuleDescriptor:
        """Parse a ``module.xml`` document into a descriptor."""
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise ModlParseError(f"module.xml is not well-formed XML: {exc}") from exc

        # The root is <modules>; the descriptor lives in the first <module>.
        module = root.find("module") if root.tag == "modules" else root
        if module is None or module.tag != "module":
            raise ModlParseError("module.xml has no <module> element")

        identifier = _required_text(module, "id")
        name = _required_text(module, "name")
        version = _required_text(module, "version")
        floor = _required_text(module, "requiredIgnitionVersion")
        framework = _text(module, "requiredFrameworkVersion") or ""
        free = (_text(module, "freeModule") or "false").strip().lower() == "true"
        depends = tuple(dep.text.strip() for dep in module.findall("depends") if dep.text and dep.text.strip())

        return cls(
            identifier=identifier,
            name=name,
            version=version,
            required_ignition_version=floor,
            ignition_line=ignition_line_of(floor),
            framework_version=framework,
            free_module=free,
            depends=depends,
        )


def _text(module: ET.Element, tag: str) -> str | None:
    el = module.find(tag)
    if el is None or el.text is None:
        return None
    return el.text.strip()


def _required_text(module: ET.Element, tag: str) -> str:
    value = _text(module, tag)
    if not value:
        raise ModlParseError(f"module.xml is missing required <{tag}>")
    return value
