"""A test-only profile proving the engine is not media-specific.

It classifies Linux distribution images and is registered by the tests; it is
not a shipped profile. A real profile can be this small.
"""

from __future__ import annotations

import re
from pathlib import Path

from trovium.profiles.base import (
    CandidateGroup,
    Classification,
    Profile,
    safe_component,
)

_ARCHES = ("x86_64", "amd64", "aarch64", "arm64", "i686", "riscv64")
_IMAGE = re.compile(
    r"^(?P<name>[a-z][a-z0-9]*)"
    r"[-_](?P<version>\d+(?:\.\d+)*)"
    r"[-_].*?"
    r"(?P<arch>" + "|".join(_ARCHES) + r")",
    re.IGNORECASE,
)


class DistrosProfile(Profile):
    """Linux distribution images under ``Distros/<Name>/<Version>/<Arch>/``."""

    name = "distros"
    categories = ("iso", "all")
    extensions = frozenset({".iso", ".img"})

    def groups(self, entry: Path) -> tuple[CandidateGroup, ...]:
        files = self.collect_files(entry)
        if not files:
            return ()
        return (CandidateGroup(name=entry.name, files=files, root=entry),)

    def classify(self, group: CandidateGroup) -> Classification | None:
        match = _IMAGE.search(group.name)
        if match is None:
            return None
        return Classification(
            profile=self.name,
            kind="iso",
            title=match.group("name"),
            details={
                "version": match.group("version"),
                "arch": match.group("arch").lower(),
            },
        )

    def destination(self, classification: Classification, library_root: Path) -> Path:
        name = safe_component(classification.title or "Unknown").title()
        version = safe_component(str(classification.details["version"]))
        arch = safe_component(str(classification.details["arch"]))
        return library_root / "Distros" / name / version / arch
