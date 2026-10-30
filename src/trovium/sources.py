"""Candidate enumeration for both declared sources.

Disk mode: each direct child of ``--source`` is one source entry; the active
profile decides whether it yields one candidate, several (for example one
ebook per file), or none. Client mode: one torrent is one candidate, with the
profile deciding which of its files travel with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from trovium.profiles.base import Profile
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
    root: Path | None = None
    unresolved_reason: str | None = None
    completion: CompletionState = CompletionState.COMPLETE
    client_state: ClientState = ClientState.NONE
    client_category: str | None = None
    client_hash: str | None = None


def disk_candidates(source_dir: Path, profile: Profile) -> tuple[Candidate, ...]:
    """Each direct child is one entry; the profile splits it into candidates."""
    candidates: list[Candidate] = []
    for child in sorted(source_dir.iterdir()):
        groups = profile.groups(child)
        if not groups:
            # Keep the entry visible in the record as rejected/out of scope.
            candidates.append(
                Candidate(
                    name=child.name,
                    source=Source.DISK,
                    files=(),
                    root=child,
                )
            )
            continue
        candidates.extend(
            Candidate(
                name=group.name,
                source=Source.DISK,
                files=group.files,
                root=group.root if group.root is not None else child,
            )
            for group in groups
        )
    return tuple(candidates)


def client_candidates(
    entries: tuple[
        tuple[str, str, Path, Path, CompletionState, ClientState, str | None], ...
    ],
    profile: Profile,
) -> tuple[Candidate, ...]:
    """Adapt adapter-reported entries to candidates (one torrent, one item).

    A completed torrent is expanded through the profile's grouping so sidecars
    travel with their book. Groups that share one name are formats of the same
    item and merge; distinct groups make the torrent unresolvable rather than
    splitting it across client actions.
    """
    candidates: list[Candidate] = []
    for (
        torrent_hash,
        name,
        content_path,
        root_path,
        completion,
        client_state,
        client_category,
    ) in entries:
        groups = profile.groups(content_path)
        unresolved: str | None = None
        if len(groups) == 1:
            files = groups[0].files
        elif groups and all(group.name == groups[0].name for group in groups):
            files = tuple(path for group in groups for path in group.files)
        elif groups:
            files = tuple(path for group in groups for path in group.files)
            names = ", ".join(
                group.files[0].name if group.files else group.name for group in groups
            )
            unresolved = f"torrent holds several items: {names}"
        else:
            files = ()
        candidates.append(
            Candidate(
                name=name,
                source=Source.CLIENT,
                files=files,
                root=root_path,
                unresolved_reason=unresolved,
                completion=completion,
                client_state=client_state,
                client_category=client_category,
                client_hash=torrent_hash,
            )
        )
    return tuple(candidates)
