"""Candidate enumeration for both declared sources.

Disk mode: each direct child of ``--source`` (file or directory) is exactly one
candidate (FR-013). Client mode: candidates come from the single qBittorrent
adapter and are adapted to the same shape here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from trovium.library import collect_media_files
from trovium.record import Source


class CompletionState(StrEnum):
    """Completion state of a candidate (client mode; disk is always complete)."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class ClientState(StrEnum):
    """Client-side involvement of a candidate's files."""

    NONE = "none"
    SEEDING = "seeding"


@dataclass(frozen=True)
class Candidate:
    """One unit of ingest consideration."""

    name: str
    source: Source
    files: tuple[Path, ...]
    completion: CompletionState = CompletionState.COMPLETE
    client_state: ClientState = ClientState.NONE
    client_category: str | None = None
    client_hash: str | None = None


def disk_candidates(source_dir: Path) -> tuple[Candidate, ...]:
    """Each direct child entry of ``source_dir`` is one candidate (FR-013)."""
    candidates: list[Candidate] = []
    for child in sorted(source_dir.iterdir()):
        candidates.append(
            Candidate(
                name=child.name,
                source=Source.DISK,
                files=collect_media_files(child),
            )
        )
    return tuple(candidates)


def client_candidates(
    entries: tuple[
        tuple[str, str, Path, CompletionState, ClientState, str | None], ...
    ],
) -> tuple[Candidate, ...]:
    """Adapt adapter-reported entries to candidates (same shape as disk)."""
    return tuple(
        Candidate(
            name=name,
            source=Source.CLIENT,
            files=collect_media_files(content_path),
            completion=completion,
            client_state=client_state,
            client_category=client_category,
            client_hash=torrent_hash,
        )
        for (
            torrent_hash,
            name,
            content_path,
            completion,
            client_state,
            client_category,
        ) in entries
    )
