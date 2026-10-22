"""The media-profile boundary.

A profile answers the domain questions the ingest engine must not know:
which files belong to a candidate, how to interpret a candidate's name, and
where the resulting library item belongs. The engine owns sources, placement,
conflict handling, idempotency, and the record envelope.

Profiles are code modules with a small contract. Adding one is a module plus a
registration line, not a new application and not a DSL.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_component(value: str) -> str:
    """A path component with illegal characters removed; never empty."""
    cleaned = _ILLEGAL.sub("", value).strip().rstrip(".")
    return cleaned or "Unknown"


@dataclass(frozen=True)
class CandidateGroup:
    """One candidate's display name and the files that travel with it."""

    name: str
    files: tuple[Path, ...]
    root: Path | None = None


@dataclass(frozen=True)
class Classification:
    """The resolved meaning of one candidate, in profile-defined terms."""

    profile: str
    kind: str
    title: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NamePlan:
    """One file's rename target, or a reason it cannot be named safely."""

    source: Path
    name: str | None
    reason: str | None = None


class Profile(ABC):
    """A media type's membership, grouping, classification, and layout."""

    name: ClassVar[str]
    categories: ClassVar[tuple[str, ...]]
    extensions: ClassVar[frozenset[str]]

    def is_member(self, path: Path) -> bool:
        """True when ``path`` is a media file this profile can ingest."""
        return path.suffix.lower() in self.extensions

    def is_incidental(self, path: Path) -> bool:
        """True for release clutter that must never be a candidate on its own."""
        return False

    def collect_files(self, root: Path) -> tuple[Path, ...]:
        """All member files at or beneath ``root``, incidental files excluded."""
        if not root.exists():
            return ()
        if root.is_file():
            return (
                (root,) if self.is_member(root) and not self.is_incidental(root) else ()
            )
        return tuple(
            sorted(
                path
                for path in root.rglob("*")
                if path.is_file()
                and self.is_member(path)
                and not self.is_incidental(path)
            )
        )

    @abstractmethod
    def groups(self, entry: Path) -> tuple[CandidateGroup, ...]:
        """Split one source entry into zero or more candidates."""

    @abstractmethod
    def classify(self, group: CandidateGroup) -> Classification | None:
        """Classify a candidate, or return ``None`` when it cannot be resolved."""

    @abstractmethod
    def destination(self, classification: Classification, library_root: Path) -> Path:
        """Derive the library destination for a resolved classification."""

    def plan_names(
        self, classification: Classification, files: tuple[Path, ...]
    ) -> tuple[NamePlan, ...]:
        """Plan one target name per file; identity by default."""
        return tuple(NamePlan(path, path.name) for path in files)
