"""Run-record models and JSON emission for ``trovium-ingest``.

The record shape is pinned by
``specs/001-ingest-vertical-slice/contracts/record-schema.md``; that contract is
authoritative. No credential value may ever appear in a record
(constitution I).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TextIO


class Source(StrEnum):
    """Which source a run declared."""

    CLIENT = "client"
    DISK = "disk"


class Mode(StrEnum):
    """Placement semantics."""

    MOVE = "move"
    COPY = "copy"
    HARDLINK = "hardlink"


class Category(StrEnum):
    """Declared run scope."""

    MOVIE = "movie"
    TV = "tv"
    ALL = "all"


class PostIngest(StrEnum):
    """Client-side policy applied after a successful placement."""

    KEEP = "keep"
    PAUSE = "pause"
    DELETE = "delete"


class OnFail(StrEnum):
    """Per-item failure behavior."""

    STOP = "stop"
    CONTINUE = "continue"


class JsonStyle(StrEnum):
    """Formatting of the emitted record (same data either way)."""

    COMPACT = "compact"
    PRETTY = "pretty"


class Disposition(StrEnum):
    """Outcome of one candidate in one run (canonical enum)."""

    INGESTED = "ingested"
    ALREADY_HANDLED = "already_handled"
    NOT_YET_COMPLETE = "not_yet_complete"
    UNRESOLVABLE = "unresolvable"
    REJECTED_OUT_OF_SCOPE = "rejected_out_of_scope"
    ERROR = "error"


class ActionKind(StrEnum):
    """Kind of placement action recorded for an item."""

    MOVE = "move"
    COPY = "copy"
    HARDLINK = "hardlink"
    DELETE = "delete"


@dataclass(frozen=True)
class Action:
    """One planned or executed filesystem operation."""

    op: ActionKind
    source: str
    destination: str
    bytes: int

    def to_json(self) -> dict[str, Any]:
        """Serialize using the contract's ``from``/``to`` field names."""
        return {
            "op": self.op.value,
            "from": self.source,
            "to": self.destination,
            "bytes": self.bytes,
        }


@dataclass(frozen=True)
class ClientAction:
    """One client-facing operation performed for an ingested item."""

    op: str
    detail: str

    def to_json(self) -> dict[str, Any]:
        """Serialize this client operation."""
        return {"op": self.op, "detail": self.detail}


@dataclass
class ItemRecord:
    """Per-candidate detail in the run record."""

    name: str
    disposition: Disposition
    source: Source
    reason: str | None = None
    kind: str | None = None
    title: str | None = None
    destination: str | None = None
    actions: list[Action] = field(default_factory=list)
    client_actions: list[ClientAction] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """Serialize this item to its contract shape."""
        payload: dict[str, Any] = {
            "name": self.name,
            "source": self.source.value,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "kind": self.kind,
            "title": self.title,
            "destination": self.destination,
            "actions": [action.to_json() for action in self.actions],
        }
        if self.client_actions:
            payload["client_actions"] = [
                action.to_json() for action in self.client_actions
            ]
        return payload


@dataclass(frozen=True)
class Declared:
    """The run's declared options, echoed into the record."""

    library_root: str
    category: Category
    mode: Mode
    on_fail: OnFail
    post_ingest: PostIngest | None

    def to_json(self) -> dict[str, Any]:
        """Serialize the declared options."""
        return {
            "library_root": self.library_root,
            "category": self.category.value,
            "mode": self.mode.value,
            "on_fail": self.on_fail.value,
            "post_ingest": None if self.post_ingest is None else self.post_ingest.value,
        }


@dataclass
class RunSummary:
    """The record of one run."""

    source: Source
    dry_run: bool
    declared: Declared
    items: list[ItemRecord] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Per-disposition tallies plus ``total``; always reconciles with items."""
        counts = {disposition.value: 0 for disposition in Disposition}
        for item in self.items:
            counts[item.disposition.value] += 1
        counts["total"] = len(self.items)
        return counts

    def to_json(self) -> dict[str, Any]:
        """Serialize the whole record."""
        return {
            "source": self.source.value,
            "dry_run": self.dry_run,
            "declared": self.declared.to_json(),
            "items": [item.to_json() for item in self.items],
            "counts": self.counts(),
        }


def render(summary: RunSummary, style: JsonStyle) -> str:
    """Render a run record as JSON, compact or pretty, same data."""
    indent = 2 if style is JsonStyle.PRETTY else None
    return json.dumps(summary.to_json(), indent=indent, ensure_ascii=False)


def emit(summary: RunSummary, style: JsonStyle, stream: TextIO | None = None) -> None:
    """Write the run record to stdout by default, then a newline."""
    out = sys.stdout if stream is None else stream
    out.write(render(summary, style))
    out.write("\n")


def fail(message: str, stream: TextIO | None = None) -> None:
    """Write one deterministic error line to stderr (research D7)."""
    err = sys.stderr if stream is None else stream
    err.write(f"error: {message}\n")
