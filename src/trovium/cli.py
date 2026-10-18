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
from collections.abc import Sequence
from pathlib import Path

from trovium.adapters.qbittorrent import AdapterError
from trovium.adapters.qbittorrent import QbittorrentClient as QbittorrentClient
from trovium.classify import Classification, Kind, classify
from trovium.library import compare_existing, resolve_destination
from trovium.placement import apply_placement, plan_placement
from trovium.record import (
    Category,
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


def build_parser() -> argparse.ArgumentParser:
    """The option set of contracts/cli.md, exactly."""
    parser = argparse.ArgumentParser(
        prog="trovium-ingest",
        description="Ingest media from a download client or a local directory.",
    )
    parser.add_argument("--client-url", default=os.environ.get(CLIENT_URL_ENV))
    parser.add_argument("--source")
    parser.add_argument("--library-root", required=True)
    parser.add_argument(
        "--category", choices=[item.value for item in Category], default=Category.ALL
    )
    parser.add_argument(
        "--mode", choices=[item.value for item in Mode], default=Mode.MOVE
    )
    parser.add_argument(
        "--post-ingest",
        choices=[item.value for item in PostIngest],
        default=PostIngest.KEEP,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--on-fail", choices=[item.value for item in OnFail], default=OnFail.CONTINUE
    )
    parser.add_argument(
        "--json", choices=[item.value for item in JsonStyle], default=JsonStyle.PRETTY
    )
    return parser


class MisuseError(Exception):
    """A refused invocation; carries the message naming the cause."""


def validate(args: argparse.Namespace) -> tuple[Path, Path | None, str | None]:
    """Refuse misuse before any work (contracts/cli.md)."""
    source = Path(args.source).expanduser() if args.source else None
    client_url: str | None = args.client_url

    if source is not None and client_url:
        raise MisuseError("--source cannot be combined with --client-url")
    if source is not None and args.post_ingest != PostIngest.KEEP:
        raise MisuseError("--post-ingest applies only to client mode, not to --source")
    if source is None and not client_url:
        raise MisuseError(
            "no source declared: pass --source or set "
            f"{CLIENT_URL_ENV} (or --client-url)"
        )
    if source is not None:
        if not source.exists():
            raise MisuseError(f"--source does not exist: {source}")
        if not source.is_dir():
            raise MisuseError(f"--source is not a directory: {source}")
        if not os.access(source, os.R_OK | os.X_OK):
            raise MisuseError(f"--source is not readable: {source}")

    library_root = Path(args.library_root).expanduser()
    if not library_root.exists():
        raise MisuseError(f"--library-root does not exist: {library_root}")
    if not library_root.is_dir():
        raise MisuseError(f"--library-root is not a directory: {library_root}")
    if not os.access(library_root, os.W_OK | os.X_OK):
        raise MisuseError(f"--library-root is not writable: {library_root}")

    return library_root, source, client_url


def declared_options(
    args: argparse.Namespace, library_root: Path, source: Path | None
) -> Declared:
    """Echo the run's declared options into the record."""
    return Declared(
        library_root=str(library_root),
        category=Category(args.category),
        mode=Mode(args.mode),
        on_fail=OnFail(args.on_fail),
        post_ingest=None if source is not None else PostIngest(args.post_ingest),
    )


def in_scope(classification: Classification, category: Category) -> bool:
    """Declared scope filter; unresolvable candidates stay visible (T017)."""
    if classification.kind is Kind.UNRESOLVABLE or category is Category.ALL:
        return True
    return classification.kind.value == category.value


def process(
    candidate: Candidate,
    library_root: Path,
    declared: Declared,
    dry_run: bool,
) -> ItemRecord | None:
    """Classify and (unless dry-run) place one candidate.

    Returns ``None`` when the candidate falls outside the declared category
    scope; unresolvable candidates stay visible under any scope (T017).
    """
    if not candidate.files:
        return ItemRecord(
            name=candidate.name,
            source=candidate.source,
            disposition=Disposition.REJECTED_OUT_OF_SCOPE,
            reason="no ingestable media files",
        )
    classification = classify(
        candidate.name, tuple(path.name for path in candidate.files)
    )
    if classification.kind is Kind.UNRESOLVABLE:
        return ItemRecord(
            name=candidate.name,
            source=candidate.source,
            disposition=Disposition.UNRESOLVABLE,
            reason="name grammar not confidently matched",
        )
    if not in_scope(classification, declared.category):
        return None

    destination = resolve_destination(classification, library_root)
    existing = compare_existing(destination, candidate.files)
    plan = plan_placement(declared.mode, candidate.files, destination, existing)
    if not dry_run:
        plan = apply_placement(declared.mode, candidate.files, plan)

    return ItemRecord(
        name=candidate.name,
        source=candidate.source,
        disposition=plan.disposition,
        reason=plan.reason,
        kind=classification.kind.value,
        title=classification.title,
        destination=None if plan.destination is None else str(plan.destination),
        actions=list(plan.actions),
    )


def run_disk(
    source: Path, library_root: Path, declared: Declared, dry_run: bool
) -> RunSummary:
    """The disk-mode run flow (Story P1)."""
    candidates = disk_candidates(source)
    summary = RunSummary(
        source=Source.DISK, dry_run=dry_run, declared=declared, items=[]
    )
    for candidate in candidates:
        record = process(candidate, library_root, declared, dry_run)
        if record is None:
            continue
        summary.items.append(record)
        if record.disposition is Disposition.ERROR and declared.on_fail is OnFail.STOP:
            break
    return summary


def run_client(
    client: QbittorrentClient,
    library_root: Path,
    declared: Declared,
    dry_run: bool,
) -> RunSummary:
    """The client-mode run flow (Story P2); caller handles AdapterError."""
    entries = client.entries()
    candidates = client_candidates(
        tuple(
            (
                entry.name,
                entry.content_path,
                entry.completion,
                entry.client_state,
                entry.category,
            )
            for entry in entries
        )
    )
    summary = RunSummary(
        source=Source.CLIENT, dry_run=dry_run, declared=declared, items=[]
    )
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

        record = process(candidate, library_root, declared, dry_run)
        if record is None:
            continue
        if record.disposition is Disposition.INGESTED and not dry_run:
            try:
                if declared.mode is Mode.MOVE and record.destination is not None:
                    client.set_location(candidate.name, Path(record.destination))
                if declared.post_ingest is PostIngest.PAUSE:
                    client.pause(candidate.name)
                elif declared.post_ingest is PostIngest.DELETE:
                    client.delete(candidate.name)
            except AdapterError as error:
                record = ItemRecord(
                    name=candidate.name,
                    source=Source.CLIENT,
                    disposition=Disposition.ERROR,
                    reason=f"placement succeeded but client update failed: {error}",
                    kind=record.kind,
                    title=record.title,
                    destination=record.destination,
                    actions=record.actions,
                )
        summary.items.append(record)
        if record.disposition is Disposition.ERROR and declared.on_fail is OnFail.STOP:
            break
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: parse, refuse misuse, run, emit the record."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        library_root, source, client_url = validate(args)
    except MisuseError as misuse:
        fail(str(misuse))
        return EXIT_MISUSE

    declared = declared_options(args, library_root, source)
    dry_run = bool(args.dry_run)

    if source is not None:
        summary = run_disk(source, library_root, declared, dry_run)
    else:
        assert client_url is not None  # validate() guarantees it
        client = QbittorrentClient(
            client_url,
            os.environ.get(CLIENT_USERNAME_ENV),
            os.environ.get(CLIENT_PASSWORD_ENV),
        )
        try:
            client.login()
            summary = run_client(client, library_root, declared, dry_run)
        except AdapterError as error:
            fail(str(error))
            return EXIT_CLIENT_FAILURE
        finally:
            client.close()

    emit(summary, JsonStyle(args.json))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
