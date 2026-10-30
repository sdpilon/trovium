"""Library comparison helpers shared by every profile.

Destination resolution and media detection are profile concerns; this module
only knows how to compare a candidate's files with what the library already
holds. The already-handled rule stays stateless: an existing library item that
the resolved candidate would occupy decides the disposition (FR-004), with the
hash scope pinned in ``specs/001-ingest-vertical-slice/data-model.md``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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


def _content_match(
    source: Path, present: list[Path], consumed: set[Path]
) -> Path | None:
    """A destination file with the source's content, under any name."""
    try:
        size = source.stat().st_size
    except OSError:
        return None
    for candidate in present:
        if candidate in consumed:
            continue
        try:
            if candidate.stat().st_size != size:
                continue
            if file_digest(candidate) == file_digest(source):
                consumed.add(candidate)
                return candidate
        except OSError:
            continue
    return None


def compare_existing(
    destination: Path,
    files: tuple[Path, ...],
    *,
    planned: Mapping[Path, Path] | None = None,
) -> ExistingItem:
    """Compare candidate files with the destination, never overwriting blindly.

    Identity by (profile, kind, title, fields, file-name set) is the profile's
    job; here **every** candidate file is checked against the same name at the
    destination: size equality first, BLAKE2b only when sizes match. A
    same-name target with different content means ``COLLISION`` regardless of
    file order.

    A source without a same-name target is compared by content against the
    destination's other files, so a library file renamed by ``trovium-rename``
    still counts as already held. Only when no content match exists is the item
    new (``NONE``).

    ``planned`` maps a target path to the source another item in the same
    dry-run would place there. It lets a later candidate see an earlier
    candidate's planned placement without touching the filesystem.
    """
    if not files:
        return ExistingItem(sameness=Sameness.NONE)

    present: list[Path] | None = None
    consumed: set[Path] = set()
    any_missing = False
    for source in files:
        target = destination / source.name
        planned_source = None if planned is None else planned.get(target)
        if not target.exists() and planned_source is None:
            if present is None:
                try:
                    present = sorted(
                        path for path in destination.iterdir() if path.is_file()
                    )
                except OSError:
                    present = []
            if _content_match(source, present, consumed) is None:
                any_missing = True
            continue
        existing = target if target.exists() else planned_source
        assert existing is not None
        try:
            if existing.stat().st_size != source.stat().st_size:
                return ExistingItem(
                    sameness=Sameness.COLLISION,
                    detail=f"same name, different content: {target}",
                )
            if file_digest(existing) != file_digest(source):
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
