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


def _same_filesystem(source: Path, destination_dir: Path) -> bool:
    try:
        return source.stat().st_dev == destination_dir.stat().st_dev
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
            # redundant source; the plan exposes that removal for dry runs
            for source in files:
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
                op=ActionKind(mode.value),
                source=str(source),
                destination=str(destination / source.name),
                bytes=size,
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
        if mode is not Mode.MOVE:
            return plan
        # move mode completes the move-equivalent: the source copy is now
        # redundant once identical content is verified in the library
        try:
            for source in files:
                source.unlink(missing_ok=True)
        except OSError as error:
            return Plan(
                disposition=Disposition.ERROR,
                destination=plan.destination,
                reason=(
                    "identical content already in the library, but the redundant "
                    f"source could not be removed: {error.strerror or error}"
                ),
            )
        return Plan(
            disposition=Disposition.ALREADY_HANDLED,
            destination=plan.destination,
            actions=plan.actions,
            reason="identical content already in the library; redundant source removed",
        )
    if plan.disposition is not Disposition.INGESTED or plan.destination is None:
        return plan

    destination = plan.destination
    actions: list[Action] = []
    for source in files:
        target = destination / source.name
        try:
            destination.mkdir(parents=True, exist_ok=True)
            _perform(mode, source, target, destination)
            actions.append(
                Action(
                    op=ActionKind(mode.value),
                    source=str(source),
                    destination=str(target),
                    bytes=target.stat().st_size,
                )
            )
        except OSError as error:
            return Plan(
                disposition=Disposition.ERROR,
                destination=destination,
                actions=tuple(actions),
                reason=f"cannot place {source.name}: {error.strerror or error}",
            )
    return Plan(
        disposition=Disposition.INGESTED,
        destination=destination,
        actions=tuple(actions),
    )


def _perform(mode: Mode, source: Path, target: Path, destination: Path) -> None:
    if mode is Mode.MOVE:
        shutil.move(str(source), str(target))
        return
    if mode is Mode.COPY:
        shutil.copy2(source, target)
        return
    if _same_filesystem(source, destination):
        try:
            os.link(source, target)
            return
        except OSError as error:
            if error.errno not in _LINK_FALLBACK_ERRNOS:
                raise
    shutil.copy2(source, target)
