"""Resolve a requested module to the latest build compatible with an Ignition version.

Third-party Ignition modules declare compatibility as a *floor*
(``requiredIgnitionVersion``, a ``>=``) scoped to a major *line*: an 8.1-line
build will not load on an 8.3 gateway, and vice-versa. So "give me embr-charts
for Ignition 8.3.6" means: keep the registry entries on the 8.3 line whose floor
is satisfied by 8.3.6, then pick the highest module version among them.

This is deliberately distinct from the bundled ``modules.yaml`` catalog's
exact-match ``ignition_versions`` model, which cannot express "newest build that
still supports my patch release".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ignition_stack.catalog.registry import RegistryEntry


class ResolutionError(Exception):
    """Raised when no cached build satisfies the requested Ignition version."""


def parse_version(value: str) -> tuple[int, ...]:
    """Parse a dotted version into a comparable tuple of ints.

    Tolerates the 3- or 4-part ``<version>`` Ignition modules carry
    (``6.2.0`` or ``6.2.0.2026060621`` - the build-stamp tail sorts naturally as
    a later component, breaking ties between otherwise-equal semvers). Any
    non-numeric trailing junk on a component is dropped rather than raising, so a
    surprising version string degrades to a best-effort comparison instead of a
    crash mid-resolve.
    """
    parts: list[int] = []
    for raw in value.split("."):
        digits = ""
        for ch in raw:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def ignition_line_of(version: str) -> str:
    """The major.minor *line* of an Ignition version (``8.3.6`` -> ``8.3``).

    The line is the compatibility boundary between module artifacts; the patch
    component is compared separately against each build's floor.
    """
    parts = version.split(".")
    if len(parts) < 2:
        return version
    return f"{parts[0]}.{parts[1]}"


def satisfies(entry: RegistryEntry, ignition_version: str) -> bool:
    """Whether ``entry`` can load on the given Ignition version.

    Same major line AND the chosen version at or above the entry's floor.
    """
    if entry.ignition_line != ignition_line_of(ignition_version):
        return False
    return parse_version(ignition_version) >= parse_version(entry.min_ignition_version)


def candidates(entries: Iterable[RegistryEntry], name_or_id: str) -> list[RegistryEntry]:
    """All registry entries matching a slug or fully-qualified identifier."""
    return [e for e in entries if name_or_id in (e.name, e.module_identifier)]


def resolve(entries: Sequence[RegistryEntry], name_or_id: str, ignition_version: str) -> RegistryEntry:
    """Latest registered build of ``name_or_id`` compatible with ``ignition_version``.

    Raises :class:`ResolutionError` naming why nothing matched: an unknown
    module reads differently from a known module with no build for the chosen
    line, and that distinction is what tells the user whether to fix a typo or
    ``modules add`` the right-line artifact.
    """
    known = candidates(entries, name_or_id)
    if not known:
        raise ResolutionError(f"no module named '{name_or_id}' in the local registry; add one with `ignition-stack modules add <url-or-path>`")

    line = ignition_line_of(ignition_version)
    compatible = [e for e in known if satisfies(e, ignition_version)]
    if not compatible:
        have = ", ".join(sorted(f"{e.module_version} (line {e.ignition_line}, needs >= {e.min_ignition_version})" for e in known))
        raise ResolutionError(f"'{name_or_id}' has no build compatible with Ignition {ignition_version} (line {line}); registered: {have}")

    return max(compatible, key=lambda e: parse_version(e.module_version))
