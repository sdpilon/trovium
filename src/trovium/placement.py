"""Placement operations: the single chokepoint for library writes.

Semantics and the conflict-outcome policy are pinned in
``specs/001-ingest-vertical-slice/data-model.md`` (Behavior matrix, Pinned) and
FR-003. ``plan_placement`` performs no writes; ``apply_placement`` executes a
plan.
"""

from __future__ import annotations

import errno
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from trovium.library import ExistingItem, Sameness
from trovium.record import Action, ActionKind, Disposition, Mode

_LINK_FALLBACK_ERRNOS = frozenset(
    {
        errno.EXDEV,
        errno.EPERM,
        errno.EACCES,
        errno.EMLINK,
        errno.ENOTSUP,
        errno.EOPNOTSUPP,
    }
)


@dataclass(frozen=True)
class Plan:
    """What a placement would do, without doing it."""

    disposition: Disposition
    destination: Path | None = None
    actions: tuple[Action, ...] = field(default=())
    reason: str | None = None


def _filesystem_anchor(path: Path) -> Path | None:
    """Nearest existing path at or above ``path``.

    Plan-time probes may run before the destination directory is created.
    """
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return None


def _same_filesystem(source: Path, destination_dir: Path) -> bool:
    anchor = _filesystem_anchor(destination_dir)
    if anchor is None:
        return False
    try:
        return source.stat().st_dev == anchor.stat().st_dev
    except OSError:
        return False


def _planned_operation(
    mode: Mode, source: Path, destination: Path
) -> tuple[ActionKind, str | None]:
    """Predict the operation and any fallback note (SC-005 parity at plan time)."""
    same_fs = _same_filesystem(source, destination)
    if mode is Mode.HARDLINK and not same_fs:
        return (
            ActionKind.COPY,
            "hardlink unavailable across filesystems; copied instead",
        )
    if mode is Mode.MOVE and not same_fs:
        return ActionKind.MOVE, "cross-volume move: copied then removed source"
    return ActionKind(mode.value), None


def _same_file(source: Path, target: Path) -> bool:
    """True when both paths resolve to the same file (never unlink it then)."""
    try:
        return target.exists() and source.exists() and os.path.samefile(source, target)
    except OSError:
        return False


def plan_placement(
    mode: Mode, files: tuple[Path, ...], destination: Path, existing: ExistingItem
) -> Plan:
    """Compute the placement plan; makes no changes (FR-006 discipline)."""
    if existing.sameness is Sameness.IDENTICAL:
        removals: list[Action] = []
        if mode is Mode.MOVE:
            # move mode completes the move-equivalent by removing the now
            # redundant source; the plan exposes that removal for dry runs.
            # A source that already *is* the destination file must never be
            # removed: the item is a no-op, not a redundant copy.
            for source in files:
                if _same_file(source, destination / source.name):
                    continue
                try:
                    size = source.stat().st_size
                except OSError:
                    size = 0
                removals.append(
                    Action(
                        op=ActionKind.DELETE,
                        source=str(source),
                        destination=str(destination / source.name),
                        bytes=size,
                    )
                )
        return Plan(
            disposition=Disposition.ALREADY_HANDLED,
            destination=destination,
            actions=tuple(removals),
            reason="identical content already in the library",
        )
    if existing.sameness is Sameness.COLLISION:
        return Plan(
            disposition=Disposition.ERROR,
            destination=destination,
            reason=existing.detail or "destination conflict",
        )
    if not files:
        return Plan(
            disposition=Disposition.REJECTED_OUT_OF_SCOPE,
            reason="no ingestable media files",
        )

    actions: list[Action] = []
    for source in files:
        try:
            size = source.stat().st_size
        except OSError as error:
            return Plan(
                disposition=Disposition.ERROR,
                destination=destination,
                reason=f"cannot read {source}: {error.strerror or error}",
            )
        actions.append(
            Action(
                op=_planned_operation(mode, source, destination)[0],
                source=str(source),
                destination=str(destination / source.name),
                bytes=size,
                note=_planned_operation(mode, source, destination)[1],
            )
        )
    return Plan(
        disposition=Disposition.INGESTED,
        destination=destination,
        actions=tuple(actions),
    )


def apply_placement(mode: Mode, files: tuple[Path, ...], plan: Plan) -> Plan:
    """Execute ``plan``; returns a plan whose disposition is the outcome."""
    if plan.disposition is Disposition.ALREADY_HANDLED:
        if mode is not Mode.MOVE or not plan.actions:
            return plan
        # move mode completes the move-equivalent by removing the redundant
        # source; the plan already excludes sources that are the destination
        # file itself, so this can never unlink a placed library file.
        removed: list[Action] = []
        for action in plan.actions:
            if action.op is not ActionKind.DELETE:
                continue
            try:
                Path(action.source).unlink(missing_ok=True)
                removed.append(action)
            except OSError as error:
                return Plan(
                    disposition=Disposition.ERROR,
                    destination=plan.destination,
                    actions=tuple(removed),
                    reason=(
                        "identical content already in the library, but the "
                        f"redundant source could not be removed: "
                        f"{error.strerror or error}"
                    ),
                )
        return Plan(
            disposition=Disposition.ALREADY_HANDLED,
            destination=plan.destination,
            actions=tuple(removed),
            reason="identical content already in the library; redundant source removed",
        )
    if plan.disposition is not Disposition.INGESTED or plan.destination is None:
        return plan

    destination = plan.destination
    actions: list[Action] = []
    applied: list[tuple[Path, Path, ActionKind]] = []
    try:
        for source in files:
            target = destination / source.name
            destination.mkdir(parents=True, exist_ok=True)
            performed, note = _perform(mode, source, target, destination)
            applied.append((source, target, performed))
            actions.append(
                Action(
                    op=performed,
                    source=str(source),
                    destination=str(target),
                    bytes=target.stat().st_size,
                    note=note,
                )
            )
    except OSError as error:
        _rollback(applied)
        return Plan(
            disposition=Disposition.ERROR,
            destination=destination,
            reason=f"cannot place {source.name}: {error.strerror or error}",
        )
    notes = [action.note for action in actions if action.note]
    return Plan(
        disposition=Disposition.INGESTED,
        destination=destination,
        actions=tuple(actions),
        reason="; ".join(notes) if notes else None,
    )


def _rollback(applied: list[tuple[Path, Path, ActionKind]]) -> None:
    """Best-effort undo of the files placed for the failing item."""
    for source, target, op in reversed(applied):
        try:
            if op is ActionKind.MOVE:
                shutil.move(str(target), str(source))
            else:
                target.unlink(missing_ok=True)
        except OSError:
            continue


def _perform(
    mode: Mode, source: Path, target: Path, destination: Path
) -> tuple[ActionKind, str | None]:
    """Perform one placement and report the operation actually used."""
    if mode is Mode.MOVE:
        cross_volume = not _same_filesystem(source, destination)
        shutil.move(str(source), str(target))
        note = "cross-volume move: copied then removed source" if cross_volume else None
        return ActionKind.MOVE, note
    if mode is Mode.COPY:
        shutil.copy2(source, target)
        return ActionKind.COPY, None
    if _same_filesystem(source, destination):
        try:
            os.link(source, target)
            return ActionKind.HARDLINK, None
        except OSError as error:
            if error.errno not in _LINK_FALLBACK_ERRNOS:
                raise
            shutil.copy2(source, target)
            return ActionKind.COPY, "hardlink unavailable; copied instead"
    shutil.copy2(source, target)
    return ActionKind.COPY, "hardlink unavailable across filesystems; copied instead"
