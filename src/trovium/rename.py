"""``trovium-rename``: canonicalize placed files from an ingest record.

The step is record-driven and profile-aware. It reads the record produced by
``trovium-ingest`` (stdin by default), asks the record's profile for one target
name per file, and renames the placed files. It never guesses a classification
and never overwrites an existing target.

Safety default: only ``mode = move`` records are renamed. A copy/hardlink
record can still have its source present, so renaming its library copy breaks
the ingest no-op rerun and, with hardlinks, seeding. Client items whose record
says the torrent was relocated into the library are skipped for the same
reason. ``--allow-unsafe`` is the explicit override for a user who has stopped
seeding and removed the source.
"""

from __future__ import annotations

import contextlib
import json
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from trovium.profiles import get_profile
from trovium.profiles.base import Classification, Profile
from trovium.record import Action, ActionKind, JsonStyle, OnFail, fail

EXIT_OK = 0
EXIT_MISUSE = 2


class RecordError(Exception):
    """The input record cannot be renamed as supplied."""


class RenameDisposition(StrEnum):
    """Outcome of one record item."""

    RENAMED = "renamed"
    ALREADY_HANDLED = "already_handled"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True)
class RenameDeclared:
    """The run options echoed from the input record."""

    profile: str
    library_root: str | None
    mode: str

    def to_json(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "library_root": self.library_root,
            "mode": self.mode,
        }


@dataclass
class RenameItem:
    """One record item's rename outcome."""

    name: str
    disposition: RenameDisposition
    kind: str | None = None
    title: str | None = None
    details: dict[str, object] | None = None
    destination: str | None = None
    reason: str | None = None
    actions: list[Action] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "kind": self.kind,
            "title": self.title,
            "destination": self.destination,
            "actions": [action.to_json() for action in self.actions],
        }
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class RenameSummary:
    """The record of one rename run."""

    dry_run: bool
    declared: RenameDeclared
    items: list[RenameItem] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counts = {disposition.value: 0 for disposition in RenameDisposition}
        for item in self.items:
            counts[item.disposition.value] += 1
        counts["total"] = len(self.items)
        return counts

    def to_json(self) -> dict[str, Any]:
        return {
            "source": "rename",
            "dry_run": self.dry_run,
            "declared": self.declared.to_json(),
            "items": [item.to_json() for item in self.items],
            "counts": self.counts(),
        }


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="trovium-rename",
        description="Rename placed files from a trovium-ingest record.",
    )
    parser.add_argument(
        "--record",
        default=None,
        help="ingest record path, or - for stdin (default: stdin)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-unsafe",
        action="store_true",
        help=(
            "allow copy/hardlink and client-relocated items; use only after "
            "seeding stops and the source is gone"
        ),
    )
    parser.add_argument("--on-fail", choices=[item.value for item in OnFail])
    parser.add_argument("--json", choices=[item.value for item in JsonStyle])
    return parser


def _read_text(path: str | None) -> str:
    if path is None or path == "-":
        if sys.stdin.isatty():
            raise RecordError(
                "no record on stdin: pipe trovium-ingest or pass --record PATH"
            )
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise RecordError(f"cannot read record {path}: {error}") from error


def read_record(path: str | None) -> tuple[dict[str, Any], Profile]:
    """Parse and validate an ingest (or previous rename) record."""
    text = _read_text(path)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise RecordError(f"invalid record JSON: {error}") from error
    if not isinstance(payload, dict):
        raise RecordError("record must be a JSON object")
    declared = payload.get("declared")
    if not isinstance(declared, dict):
        raise RecordError("record has no declared object")
    profile_name = declared.get("profile")
    if not isinstance(profile_name, str) or not profile_name:
        raise RecordError(
            "record has no declared.profile; re-run ingest with this release"
        )
    try:
        profile = get_profile(profile_name)
    except KeyError as error:
        raise RecordError(str(error)) from error
    if not isinstance(declared.get("mode"), str):
        raise RecordError("record has no declared.mode")
    if not isinstance(payload.get("items"), list):
        raise RecordError("record has no items array")
    return payload, profile


def _declared(payload: dict[str, Any]) -> RenameDeclared:
    declared = payload["declared"]
    library_root = declared.get("library_root")
    return RenameDeclared(
        profile=str(declared["profile"]),
        library_root=library_root if isinstance(library_root, str) else None,
        mode=str(declared["mode"]),
    )


def _client_relocated(item: dict[str, Any]) -> bool:
    actions = item.get("client_actions")
    if not isinstance(actions, list):
        return False
    return any(
        isinstance(action, dict) and action.get("op") == "setLocation"
        for action in actions
    )


def _plan_item(
    item: dict[str, Any], profile: Profile, *, allow_unsafe: bool
) -> RenameItem:
    name = str(item.get("name") or "item")
    kind = item.get("kind")
    title = item.get("title")
    destination = item.get("destination")
    details = item.get("details")
    detail_map: dict[str, object] = (
        {str(key): value for key, value in details.items()}
        if isinstance(details, dict)
        else {}
    )

    def result(disposition: RenameDisposition, reason: str | None = None) -> RenameItem:
        return RenameItem(
            name=name,
            disposition=disposition,
            kind=kind if isinstance(kind, str) else None,
            title=title if isinstance(title, str) else None,
            details=detail_map or None,
            destination=destination if isinstance(destination, str) else None,
            reason=reason,
        )

    if not isinstance(destination, str) or not destination:
        return result(RenameDisposition.SKIPPED, "item has no library destination")
    if not isinstance(kind, str) or not isinstance(title, str):
        return result(RenameDisposition.SKIPPED, "item has no classification")
    if not allow_unsafe and _client_relocated(item):
        return result(
            RenameDisposition.SKIPPED,
            "client was relocated into the library; renaming would break "
            "seeding (pass --allow-unsafe after the client stops seeding)",
        )

    directory = Path(destination)
    if not directory.is_dir():
        return result(
            RenameDisposition.ERROR, f"destination is not a directory: {directory}"
        )
    try:
        files = tuple(sorted(path for path in directory.iterdir() if path.is_file()))
    except OSError as error:
        return result(RenameDisposition.ERROR, f"cannot list {directory}: {error}")
    if not files:
        return result(
            RenameDisposition.SKIPPED, f"destination has no files: {directory}"
        )

    classification = Classification(
        profile=profile.name, kind=kind, title=title, details=detail_map
    )
    plans = profile.plan_names(classification, files)
    if {plan.source for plan in plans} != set(files):
        return result(
            RenameDisposition.ERROR,
            "profile did not return a name plan for every file",
        )

    targets: dict[str, str] = {}
    for plan in plans:
        if plan.name is None:
            continue
        key = plan.name.casefold()
        if key in targets:
            return result(
                RenameDisposition.ERROR,
                f"duplicate target name: {plan.name}",
            )
        targets[key] = plan.name

    actions: list[Action] = []
    skipped: list[str] = []
    for plan in plans:
        if plan.name is None:
            skipped.append(f"{plan.source.name}: {plan.reason or 'cannot be renamed'}")
            continue
        if Path(plan.name).name != plan.name or plan.name in {"", ".", ".."}:
            return result(
                RenameDisposition.ERROR, f"invalid target name: {plan.name!r}"
            )
        target = directory / plan.name
        if target == plan.source:
            continue
        if target.exists():
            if not plan.source.exists():
                continue
            return result(
                RenameDisposition.ERROR, f"target already exists: {plan.name}"
            )
        if not plan.source.exists():
            return result(
                RenameDisposition.ERROR, f"source missing: {plan.source.name}"
            )
        try:
            size = plan.source.stat().st_size
        except OSError as error:
            return result(
                RenameDisposition.ERROR, f"cannot read {plan.source.name}: {error}"
            )
        actions.append(
            Action(
                op=ActionKind.RENAME,
                source=str(plan.source),
                destination=str(target),
                bytes=size,
            )
        )

    if skipped and actions:
        return result(
            RenameDisposition.ERROR,
            "cannot rename every file: " + "; ".join(skipped),
        )
    if skipped:
        return result(RenameDisposition.SKIPPED, "; ".join(skipped))
    if not actions:
        return result(RenameDisposition.ALREADY_HANDLED)
    renamed = result(RenameDisposition.RENAMED)
    renamed.actions = actions
    return renamed


def _apply(item: RenameItem) -> None:
    applied: list[tuple[Path, Path]] = []
    try:
        for action in item.actions:
            source = Path(action.source)
            target = Path(action.destination)
            if target.exists():
                raise FileExistsError(f"target appeared during the run: {target}")
            source.rename(target)
            applied.append((source, target))
    except OSError as error:
        for source, target in reversed(applied):
            with contextlib.suppress(OSError):
                target.rename(source)
        item.disposition = RenameDisposition.ERROR
        item.reason = f"rename failed and was rolled back: {error}"
        item.actions = []


def rename_items(
    payload: dict[str, Any],
    profile: Profile,
    *,
    dry_run: bool,
    allow_unsafe: bool,
    on_fail: OnFail,
) -> RenameSummary:
    """Plan (and unless dry-run, apply) every item in the record."""
    items: list[RenameItem] = []
    for index, raw in enumerate(payload["items"]):
        if not isinstance(raw, dict):
            item = RenameItem(
                name=f"item {index + 1}",
                disposition=RenameDisposition.ERROR,
                reason="record item is not an object",
            )
        else:
            item = _plan_item(raw, profile, allow_unsafe=allow_unsafe)
            if not dry_run and item.disposition is RenameDisposition.RENAMED:
                _apply(item)
        items.append(item)
        if item.disposition is RenameDisposition.ERROR and on_fail is OnFail.STOP:
            break
    return RenameSummary(dry_run=dry_run, declared=_declared(payload), items=items)


def render(summary: RenameSummary, style: JsonStyle) -> str:
    indent = 2 if style is JsonStyle.PRETTY else None
    return json.dumps(summary.to_json(), indent=indent, ensure_ascii=False)


def emit(summary: RenameSummary, style: JsonStyle) -> None:
    sys.stdout.write(render(summary, style))
    sys.stdout.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    args: Namespace = build_parser().parse_args(argv)
    try:
        payload, profile = read_record(args.record)
    except RecordError as error:
        fail(str(error))
        return EXIT_MISUSE

    mode = str(payload["declared"]["mode"])
    if mode != "move" and not args.allow_unsafe:
        fail(
            f"refusing to rename a {mode!r} ingest: renaming the library copy "
            "can break seeding and the ingest no-op rerun; pass --allow-unsafe "
            "after the source is gone"
        )
        return EXIT_MISUSE
    if args.allow_unsafe:
        sys.stderr.write(
            "warning: --allow-unsafe permits renaming seeding or copy-mode "
            "files; the source must be gone before the next ingest\n"
        )

    on_fail = OnFail(args.on_fail) if args.on_fail else OnFail.CONTINUE
    summary = rename_items(
        payload,
        profile,
        dry_run=bool(args.dry_run),
        allow_unsafe=bool(args.allow_unsafe),
        on_fail=on_fail,
    )
    emit(summary, JsonStyle(args.json) if args.json else JsonStyle.PRETTY)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
