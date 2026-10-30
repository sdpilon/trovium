"""``trovium-ingest``: the ingest step's single command-line entry point.

Contract: ``specs/001-ingest-vertical-slice/contracts/cli.md`` (options, env
variables, misuse refusals, exit codes) and
``specs/001-ingest-vertical-slice/contracts/record-schema.md`` (stdout record).
Exit codes: 0 run completed, 2 misuse, 3 run-level client failure (FR-008).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from trovium.adapters.qbittorrent import AdapterError
from trovium.adapters.qbittorrent import QbittorrentClient as QbittorrentClient
from trovium.config import ConfigError, load_config
from trovium.library import compare_existing
from trovium.placement import apply_placement, effective_mode, plan_placement
from trovium.profiles import available_profiles, get_profile
from trovium.profiles.base import (
    CandidateGroup,
    Classification,
    Profile,
    Unresolved,
)
from trovium.record import (
    ActionKind,
    ClientAction,
    Declared,
    Disposition,
    ItemRecord,
    JsonStyle,
    Mode,
    OnFail,
    PostIngest,
    RunSummary,
    Source,
    emit,
    fail,
)
from trovium.sources import (
    Candidate,
    ClientState,
    CompletionState,
    client_candidates,
    disk_candidates,
)

EXIT_OK = 0
EXIT_MISUSE = 2
EXIT_CLIENT_FAILURE = 3

CLIENT_URL_ENV = "TROVIUM_CLIENT_URL"
CLIENT_USERNAME_ENV = "TROVIUM_CLIENT_USERNAME"
CLIENT_PASSWORD_ENV = "TROVIUM_CLIENT_PASSWORD"
LIBRARY_ROOT_ENV = "TROVIUM_LIBRARY_ROOT"
SOURCE_ENV = "TROVIUM_SOURCE"


def build_parser() -> argparse.ArgumentParser:
    """The option set of contracts/cli.md plus config fallbacks."""
    parser = argparse.ArgumentParser(
        prog="trovium-ingest",
        description="Ingest media from a download client or a local directory.",
    )
    parser.add_argument("--client-url", default=None)
    parser.add_argument("--source", default=None)
    parser.add_argument("--library-root", default=None)
    parser.add_argument(
        "--config",
        default=None,
        help="configuration file (default: XDG trovium/config.ini)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="media profile (default: video; see --help for the registry)",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="declared scope; the selected profile defines the values",
    )
    parser.add_argument("--mode", choices=[item.value for item in Mode])
    parser.add_argument(
        "--post-ingest",
        choices=[item.value for item in PostIngest],
        default=None,
        help="client-side policy after a successful placement (client mode only)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--on-fail", choices=[item.value for item in OnFail])
    parser.add_argument("--json", choices=[item.value for item in JsonStyle])
    return parser


class MisuseError(Exception):
    """A refused invocation; carries the message naming the cause."""


@dataclass(frozen=True)
class ResolvedOptions:
    """The effective options after CLI, environment, and config precedence."""

    profile: Profile
    library_root: Path
    source: Path | None
    client_url: str | None
    category: str
    mode: Mode
    post_ingest: PostIngest | None
    on_fail: OnFail
    json_style: JsonStyle
    client_username_env: str
    client_password_env: str


def _first[T](*values: T | None) -> T | None:
    for value in values:
        if value is not None:
            return value
    return None


def resolve_options(args: argparse.Namespace) -> ResolvedOptions:
    """Load config and resolve CLI > environment > config > defaults."""

    try:
        loaded = load_config(args.config, required=args.config is not None)
    except ConfigError as error:
        raise MisuseError(str(error)) from error
    config = loaded.config if loaded is not None else None
    if loaded is not None:
        for warning in loaded.warnings:
            sys.stderr.write(f"warning: {warning}\n")

    source_value = _first(args.source, os.environ.get(SOURCE_ENV))
    client_value = _first(args.client_url, os.environ.get(CLIENT_URL_ENV))
    if source_value is None and client_value is None and config is not None:
        if config.source.mode == "disk":
            source_value = config.source.path
        elif config.source.mode == "client":
            client_value = config.source.client_url

    source = Path(source_value).expanduser().resolve() if source_value else None
    client_url = str(client_value) if client_value else None
    if source is not None and client_url:
        raise MisuseError("--source cannot be combined with --client-url")
    if source is None and not client_url:
        raise MisuseError(
            "no source declared: pass --source or set "
            f"{CLIENT_URL_ENV} (or --client-url, or configure [source])"
        )
    if source is not None and args.post_ingest is not None:
        raise MisuseError("--post-ingest applies only to client mode, not to --source")
    if source is not None:
        if not source.exists():
            raise MisuseError(f"--source does not exist: {source}")
        if not source.is_dir():
            raise MisuseError(f"--source is not a directory: {source}")
        if not os.access(source, os.R_OK | os.X_OK):
            raise MisuseError(f"--source is not readable: {source}")

    library_value = _first(
        args.library_root,
        os.environ.get(LIBRARY_ROOT_ENV),
        config.library_root if config is not None else None,
    )
    if library_value is None:
        raise MisuseError(
            "--library-root is required: pass it, set "
            f"{LIBRARY_ROOT_ENV}, or configure [library] root"
        )
    library_root = Path(library_value).expanduser().resolve()
    if not library_root.exists():
        raise MisuseError(f"--library-root does not exist: {library_root}")
    if not library_root.is_dir():
        raise MisuseError(f"--library-root is not a directory: {library_root}")
    if not os.access(library_root, os.W_OK | os.X_OK):
        raise MisuseError(f"--library-root is not writable: {library_root}")

    profile_value = _first(
        args.profile,
        config.ingest.profile if config is not None else None,
        "video",
    )
    try:
        profile = get_profile(str(profile_value))
    except KeyError as error:
        allowed = ", ".join(available_profiles())
        raise MisuseError(
            f"--profile must be one of: {allowed} (got {profile_value!r})"
        ) from error

    category_value = str(
        _first(
            args.category,
            config.ingest.category if config is not None else None,
            "all",
        )
    )
    if category_value not in profile.categories:
        allowed = ", ".join(profile.categories)
        raise MisuseError(
            f"--category for profile '{profile.name}' must be one of: {allowed}"
        )

    mode_value = _first(
        args.mode,
        config.ingest.mode.value if config is not None else None,
        Mode.AUTO.value,
    )
    on_fail_value = _first(
        args.on_fail,
        config.ingest.on_fail.value if config is not None else None,
        OnFail.CONTINUE.value,
    )
    json_value = _first(
        args.json,
        config.ingest.json.value if config is not None else None,
        JsonStyle.PRETTY.value,
    )
    post_ingest: PostIngest | None = None
    if source is None and client_url:
        post_value = _first(
            args.post_ingest,
            config.ingest.post_ingest.value if config is not None else None,
            PostIngest.KEEP.value,
        )
        post_ingest = PostIngest(str(post_value))

    return ResolvedOptions(
        profile=profile,
        library_root=library_root,
        source=source,
        client_url=client_url,
        category=category_value,
        mode=Mode(str(mode_value)),
        post_ingest=post_ingest,
        on_fail=OnFail(str(on_fail_value)),
        json_style=JsonStyle(str(json_value)),
        client_username_env=(
            config.source.client_username_env
            if config is not None
            else CLIENT_USERNAME_ENV
        ),
        client_password_env=(
            config.source.client_password_env
            if config is not None
            else CLIENT_PASSWORD_ENV
        ),
    )


def declared_options(resolved: ResolvedOptions) -> Declared:
    """Echo the run's declared options into the record."""
    return Declared(
        profile=resolved.profile.name,
        library_root=str(resolved.library_root),
        category=resolved.category,
        mode=resolved.mode,
        on_fail=resolved.on_fail,
        post_ingest=resolved.post_ingest,
    )


def in_scope(kind: str, category: str) -> bool:
    """Declared scope filter; unresolvable candidates never reach this."""
    return category == "all" or kind == category


def process(
    candidate: Candidate,
    library_root: Path,
    declared: Declared,
    dry_run: bool,
    *,
    profile: Profile,
    guard: Callable[[Candidate, Classification, Mode], str | None] | None = None,
    planned: Mapping[Path, Path] | None = None,
) -> ItemRecord:
    """Classify and (unless dry-run) place one candidate.

    Every candidate produces a record: ones outside the declared category
    scope are reported as ``rejected_out_of_scope`` with a scope reason rather
    than vanishing (SC-003); a candidate whose files are not visible on this
    host is a named error, not "no media" (SC-003, Edge Cases).
    """
    if candidate.unresolved_reason is not None:
        return ItemRecord(
            name=candidate.name,
            source=candidate.source,
            disposition=Disposition.UNRESOLVABLE,
            reason=candidate.unresolved_reason,
        )
    if not candidate.files:
        root = candidate.root
        if root is not None and not root.exists():
            return ItemRecord(
                name=candidate.name,
                source=candidate.source,
                disposition=Disposition.ERROR,
                reason=f"source path not visible on this host: {root}",
            )
        where = f" in {root}" if root is not None else ""
        return ItemRecord(
            name=candidate.name,
            source=candidate.source,
            disposition=Disposition.REJECTED_OUT_OF_SCOPE,
            reason=f"no ingestable media files{where}",
        )
    group = CandidateGroup(
        name=candidate.name, files=candidate.files, root=candidate.root
    )
    classification = profile.classify(group)
    if isinstance(classification, Unresolved):
        return ItemRecord(
            name=candidate.name,
            source=candidate.source,
            disposition=Disposition.UNRESOLVABLE,
            reason=classification.reason,
        )
    if classification is None:
        return ItemRecord(
            name=candidate.name,
            source=candidate.source,
            disposition=Disposition.UNRESOLVABLE,
            reason=f"{profile.name} name grammar not confidently matched",
        )
    if not in_scope(classification.kind, declared.category):
        return ItemRecord(
            name=candidate.name,
            source=candidate.source,
            disposition=Disposition.REJECTED_OUT_OF_SCOPE,
            reason=f"outside the declared category scope ({declared.category})",
            kind=classification.kind,
            title=classification.title,
            details=dict(classification.details) or None,
        )

    destination = profile.destination(classification, library_root)
    mode = effective_mode(
        declared.mode,
        seeding=(
            candidate.source is Source.CLIENT
            and candidate.client_state is ClientState.SEEDING
        ),
        files=candidate.files,
        destination=destination,
    )
    refusal = guard(candidate, classification, mode) if guard is not None else None

    existing = compare_existing(destination, candidate.files, planned=planned)
    plan = plan_placement(mode, candidate.files, destination, existing)
    if refusal is not None:
        if plan.disposition is Disposition.INGESTED:
            return ItemRecord(
                name=candidate.name,
                source=candidate.source,
                disposition=Disposition.ERROR,
                reason=refusal,
                kind=classification.kind,
                title=classification.title,
                details=dict(classification.details) or None,
            )
        if plan.disposition is Disposition.ALREADY_HANDLED:
            # the client seeds from those copies; suppress the move cleanup
            plan = replace(
                plan,
                actions=(),
                reason="identical content already in the library",
            )
    if not dry_run:
        plan = apply_placement(mode, candidate.files, plan)

    return ItemRecord(
        name=candidate.name,
        source=candidate.source,
        disposition=plan.disposition,
        reason=plan.reason,
        kind=classification.kind,
        title=classification.title,
        details=dict(classification.details) or None,
        destination=None if plan.destination is None else str(plan.destination),
        actions=list(plan.actions),
    )


def _record_planned_placement(planned: dict[Path, Path], record: ItemRecord) -> None:
    """Remember a dry-run placement so later candidates can see it."""
    if record.disposition is not Disposition.INGESTED:
        return
    for action in record.actions:
        planned[Path(action.destination)] = Path(action.source)


def run_disk(
    source: Path,
    library_root: Path,
    declared: Declared,
    dry_run: bool,
    profile: Profile,
) -> RunSummary:
    """The disk-mode run flow (Story P1)."""
    candidates = disk_candidates(source, profile)
    summary = RunSummary(
        source=Source.DISK, dry_run=dry_run, declared=declared, items=[]
    )
    planned: dict[Path, Path] = {}
    for candidate in candidates:
        record = process(
            candidate,
            library_root,
            declared,
            dry_run,
            profile=profile,
            planned=planned if dry_run else None,
        )
        summary.items.append(record)
        if dry_run:
            _record_planned_placement(planned, record)
        if record.disposition is Disposition.ERROR and declared.on_fail is OnFail.STOP:
            break
    return summary


def _item_mode(
    candidate: Candidate, declared: Declared, destination: str | None
) -> Mode:
    """The effective mode for a processed candidate (``auto`` resolved)."""
    if destination is None:
        return declared.mode
    return effective_mode(
        declared.mode,
        seeding=(
            candidate.source is Source.CLIENT
            and candidate.client_state is ClientState.SEEDING
        ),
        files=candidate.files,
        destination=Path(destination),
    )


def _planned_client_actions(
    declared: Declared,
    mode: Mode,
    torrent_hash: str,
    destination: str | None,
    *,
    include_policy: bool = True,
) -> list[ClientAction]:
    """The client operations a real run would perform for this item (FR-006)."""
    planned: list[ClientAction] = []
    pause_first = (
        include_policy
        and declared.post_ingest is PostIngest.PAUSE
        and mode is Mode.MOVE
        and destination is not None
    )
    if pause_first:
        planned.append(
            ClientAction(op="pause", detail=f"planned: hashes={torrent_hash}")
        )
    if mode is Mode.MOVE and destination is not None:
        planned.append(
            ClientAction(
                op="setLocation",
                detail=f"planned: hashes={torrent_hash} location={destination}",
            )
        )
    if not include_policy:
        return planned
    if declared.post_ingest is PostIngest.PAUSE and not pause_first:
        planned.append(
            ClientAction(op="pause", detail=f"planned: hashes={torrent_hash}")
        )
    elif declared.post_ingest is PostIngest.DELETE:
        planned.append(
            ClientAction(op="delete", detail=f"planned: hashes={torrent_hash}")
        )
    if pause_first:
        planned.append(
            ClientAction(op="recheck", detail=f"planned: hashes={torrent_hash}")
        )
    return planned


MULTI_FILE_MOVE_REASON = (
    "multi-file torrent cannot be ingested with --mode move: the client expects "
    "its files under <save_path>/<torrent name>/, which the flat library layout "
    "does not provide; use --mode copy or --mode hardlink to keep seeding"
)


def _client_move_guard(
    candidate: Candidate, _classification: Classification, mode: Mode
) -> str | None:
    """Refuse client move for folder torrents after scope/classification."""
    if mode is Mode.MOVE and candidate.root is not None and candidate.root.is_dir():
        return MULTI_FILE_MOVE_REASON
    return None


def run_client(
    client: QbittorrentClient,
    library_root: Path,
    declared: Declared,
    dry_run: bool,
    profile: Profile,
) -> RunSummary:
    """The client-mode run flow (Story P2); caller handles AdapterError."""
    entries = client.entries()
    candidates = client_candidates(
        tuple(
            (
                entry.hash,
                entry.name,
                entry.content_path,
                entry.root_path,
                entry.completion,
                entry.client_state,
                entry.category,
            )
            for entry in entries
        ),
        profile,
    )
    summary = RunSummary(
        source=Source.CLIENT, dry_run=dry_run, declared=declared, items=[]
    )
    planned: dict[Path, Path] = {}
    for candidate in candidates:
        if candidate.completion is CompletionState.INCOMPLETE:
            summary.items.append(
                ItemRecord(
                    name=candidate.name,
                    source=Source.CLIENT,
                    disposition=Disposition.NOT_YET_COMPLETE,
                    reason="download not yet complete",
                )
            )
            continue

        record = process(
            candidate,
            library_root,
            declared,
            dry_run,
            profile=profile,
            guard=_client_move_guard,
            planned=planned if dry_run else None,
        )
        if dry_run:
            _record_planned_placement(planned, record)
        torrent_hash = candidate.client_hash
        assert torrent_hash is not None  # client candidates always carry hash
        mode = _item_mode(candidate, declared, record.destination)

        removed_sources = record.disposition is Disposition.ALREADY_HANDLED and any(
            action.op is ActionKind.DELETE for action in record.actions
        )
        if dry_run and (record.disposition is Disposition.INGESTED or removed_sources):
            record.client_actions.extend(
                _planned_client_actions(
                    declared,
                    mode,
                    torrent_hash,
                    record.destination,
                    include_policy=record.disposition is Disposition.INGESTED,
                )
            )

        if not dry_run and (
            record.disposition is Disposition.INGESTED or removed_sources
        ):
            try:
                pause_first = (
                    record.disposition is Disposition.INGESTED
                    and declared.post_ingest is PostIngest.PAUSE
                    and mode is Mode.MOVE
                    and record.destination is not None
                )
                if pause_first:
                    client.pause(torrent_hash)
                    record.client_actions.append(
                        ClientAction(op="pause", detail=f"hashes={torrent_hash}")
                    )
                if mode is Mode.MOVE and record.destination is not None:
                    client.set_location(torrent_hash, Path(record.destination))
                    record.client_actions.append(
                        ClientAction(
                            op="setLocation",
                            detail=(
                                f"hashes={torrent_hash} location={record.destination}"
                            ),
                        )
                    )
                if pause_first:
                    client.recheck(torrent_hash)
                    record.client_actions.append(
                        ClientAction(op="recheck", detail=f"hashes={torrent_hash}")
                    )
                    client.wait_until_complete(torrent_hash)
                if record.disposition is Disposition.INGESTED:
                    if declared.post_ingest is PostIngest.PAUSE and not pause_first:
                        client.pause(torrent_hash)
                        record.client_actions.append(
                            ClientAction(op="pause", detail=f"hashes={torrent_hash}")
                        )
                    elif declared.post_ingest is PostIngest.DELETE:
                        client.delete(torrent_hash)
                        record.client_actions.append(
                            ClientAction(op="delete", detail=f"hashes={torrent_hash}")
                        )
            except AdapterError as error:
                record = ItemRecord(
                    name=candidate.name,
                    source=Source.CLIENT,
                    disposition=Disposition.ERROR,
                    reason=f"placement succeeded but client update failed: {error}",
                    kind=record.kind,
                    title=record.title,
                    details=record.details,
                    destination=record.destination,
                    actions=record.actions,
                    client_actions=record.client_actions,
                )
        summary.items.append(record)
        if record.disposition is Disposition.ERROR and declared.on_fail is OnFail.STOP:
            break
    return summary


def run_resolved(*, resolved: ResolvedOptions, dry_run: bool) -> RunSummary:
    """Run the declared source and return the record, without emitting it.

    Raises ``AdapterError`` for a run-level client failure; callers map that
    to exit code 3. This is the reusable half of ``main`` that the pipeline
    runner composes.
    """
    declared = declared_options(resolved)
    if resolved.source is not None:
        return run_disk(
            resolved.source,
            resolved.library_root,
            declared,
            dry_run,
            resolved.profile,
        )

    assert resolved.client_url is not None  # resolve_options() guarantees it
    client = QbittorrentClient(
        resolved.client_url,
        os.environ.get(resolved.client_username_env),
        os.environ.get(resolved.client_password_env),
    )
    try:
        client.login()
        return run_client(
            client,
            resolved.library_root,
            declared,
            dry_run,
            resolved.profile,
        )
    finally:
        client.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: parse, refuse misuse, run, emit the record."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        resolved = resolve_options(args)
    except MisuseError as misuse:
        fail(str(misuse))
        return EXIT_MISUSE

    try:
        summary = run_resolved(resolved=resolved, dry_run=bool(args.dry_run))
    except AdapterError as error:
        fail(str(error))
        return EXIT_CLIENT_FAILURE

    emit(summary, resolved.json_style)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
