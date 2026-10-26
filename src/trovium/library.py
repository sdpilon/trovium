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


def compare_existing(
    destination: Path,
    files: tuple[Path, ...],
    *,
    planned: Mapping[Path, Path] | None = None,
) -> ExistingItem:
    """Compare candidate files with the destination, never overwriting blindly.

    Identity by (profile, kind, title, fields, file-name set) is the profile's
    job; here **every** candidate file is checked against the same name at the
    destination: size equality first, BLAKE2b only when sizes match. A single
    missing target means the item is new (``NONE``); a single present target
    with different content means ``COLLISION`` regardless of file order.

    ``planned`` maps a target path to the source another item in the same
    dry-run would place there. It lets a later candidate see an earlier
    candidate's planned placement without touching the filesystem.
    """
    if not files:
        return ExistingItem(sameness=Sameness.NONE)

    any_missing = False
    for source in files:
        target = destination / source.name
        planned_source = None if planned is None else planned.get(target)
        if not target.exists() and planned_source is None:
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
