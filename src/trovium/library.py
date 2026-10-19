"""Destination resolution and convention-based already-handled detection.

Folder names are derived here; file names are never changed (FR-003). The
already-handled rule is stateless: an existing library item that the resolved
candidate would occupy decides the disposition (FR-004), with the hash scope
pinned in ``specs/001-ingest-vertical-slice/data-model.md``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from trovium.classify import Classification, Kind, is_incidental, is_media_file

MOVIES_DIRNAME = "Movies"
TV_DIRNAME = "TV"

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe(title: str) -> str:
    cleaned = _ILLEGAL.sub("", title).strip().rstrip(".")
    return cleaned or "Unknown"


def resolve_destination(classification: Classification, library_root: Path) -> Path:
    """Derive the library destination for a resolved classification."""
    title = _safe(classification.title or "Unknown")
    if classification.kind is Kind.MOVIE:
        leaf = f"{title} ({classification.year})" if classification.year else title
        return library_root / MOVIES_DIRNAME / leaf
    if classification.kind is Kind.TV:
        series = library_root / TV_DIRNAME / title
        if classification.season is not None:
            return series / f"Season {classification.season:02d}"
        return series
    return library_root / "Unresolved" / title


def collect_media_files(root: Path) -> tuple[Path, ...]:
    """All ingestable media files beneath ``root`` (nested trees included)."""
    if root.is_file():
        if is_media_file(root.name) and not is_incidental(root.name):
            return (root,)
        return ()
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and is_media_file(path.name) and not is_incidental(path.name):
            found.append(path)
    return tuple(found)


def file_digest(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """BLAKE2b digest of a file's bytes (hash scope: only when sizes match)."""
    digest = hashlib.blake2b()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class Sameness(StrEnum):
    """Result of comparing a candidate with what the library already holds."""

    NONE = "none"
    IDENTICAL = "identical"
    COLLISION = "collision"


@dataclass(frozen=True)
class ExistingItem:
    """What the library already holds at a resolved destination."""

    sameness: Sameness
    detail: str | None = None


def compare_existing(destination: Path, files: tuple[Path, ...]) -> ExistingItem:
    """Compare candidate files with the destination, never overwriting blindly.

    Identity by (kind, title, season, file-name set) first is the caller's job;
    here **every** candidate file is checked against the same name at the
    destination: size equality first, BLAKE2b only when sizes match. A single
    missing target means the item is new (``NONE``); a single present target
    with different content means ``COLLISION`` regardless of file order.
    """
    if not files:
        return ExistingItem(sameness=Sameness.NONE)

    any_missing = False
    for source in files:
        target = destination / source.name
        if not target.exists():
            any_missing = True
            continue
        try:
            if target.stat().st_size != source.stat().st_size:
                return ExistingItem(
                    sameness=Sameness.COLLISION,
                    detail=f"same name, different content: {target}",
                )
            if file_digest(target) != file_digest(source):
                return ExistingItem(
                    sameness=Sameness.COLLISION,
                    detail=f"same name, different content: {target}",
                )
        except OSError as error:
            return ExistingItem(
                sameness=Sameness.COLLISION,
                detail=f"cannot compare with {target}: {error.strerror or error}",
            )
    if any_missing:
        return ExistingItem(sameness=Sameness.NONE)
    return ExistingItem(sameness=Sameness.IDENTICAL)
