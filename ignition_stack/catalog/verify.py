"""Reachability + sha256 verification for catalog entries."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

from ignition_stack.catalog.schema import SHA256_UNPINNED, CatalogEntry

REACHABILITY_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class VerifyIssue:
    """One problem found while validating an entry."""

    entry_name: str
    reason: str


def verify_reachable(entry: CatalogEntry, client: httpx.Client) -> VerifyIssue | None:
    """HEAD-check the entry's download URL. None means reachable.

    Entries that are manual-download are skipped (no URL to check). The
    response must be 2xx; many CDNs reject HEAD with 405 but accept GET,
    so a 405 falls through to a small range GET before declaring failure.
    """
    if entry.requires_manual_download:
        return None
    if entry.download_url is None:
        return VerifyIssue(entry.name, "no download_url and not marked manual")

    url = str(entry.download_url)
    try:
        response = client.head(url, follow_redirects=True, timeout=REACHABILITY_TIMEOUT_SECONDS)
        if response.status_code == 405:
            response = client.get(
                url,
                follow_redirects=True,
                timeout=REACHABILITY_TIMEOUT_SECONDS,
                headers={"Range": "bytes=0-0"},
            )
        if response.status_code >= 400:
            return VerifyIssue(entry.name, f"HTTP {response.status_code} for {url}")
    except httpx.HTTPError as exc:
        return VerifyIssue(entry.name, f"unreachable: {exc} ({url})")
    return None


def sha256_of_file(path: Path) -> str:
    """Lowercase hex sha256 digest of a file on disk."""
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksum(entry: CatalogEntry, file_path: Path) -> VerifyIssue | None:
    """Check the file at ``file_path`` matches the entry's pinned sha256."""
    if entry.sha256 == SHA256_UNPINNED:
        return VerifyIssue(entry.name, "sha256 is UNPINNED (maintainer must pin before release)")
    actual = sha256_of_file(file_path)
    if actual != entry.sha256:
        return VerifyIssue(
            entry.name,
            f"sha256 mismatch: expected {entry.sha256}, got {actual}",
        )
    return None
