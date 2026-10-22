"""``trovium-run``: the configured ingest -> rename pipeline.

The runner is a thin composition of the two shipped steps. It owns no
classification, placement, or naming logic; it resolves the same options as
ingest, runs the ingest engine, and then hands the record to the rename engine
when that is safe. The combined record is the unit a scheduler invokes.
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from typing import Any

from trovium import cli, rename
from trovium.adapters.qbittorrent import AdapterError
from trovium.record import JsonStyle, Mode, fail

EXIT_OK = cli.EXIT_OK
EXIT_MISUSE = cli.EXIT_MISUSE
EXIT_CLIENT_FAILURE = cli.EXIT_CLIENT_FAILURE


def build_parser() -> ArgumentParser:
    parser = cli.build_parser()
    parser.prog = "trovium-run"
    parser.description = "Run the configured ingest and rename pipeline."
    parser.add_argument(
        "--skip-rename",
        action="store_true",
        help="run ingest only; leave the placed files unchanged",
    )
    parser.add_argument(
        "--allow-unsafe",
        action="store_true",
        help=(
            "pass --allow-unsafe to rename: permits copy/hardlink and "
            "client-relocated items"
        ),
    )
    return parser


def _skip_reason(args: Namespace, resolved: cli.ResolvedOptions) -> str | None:
    if args.skip_rename:
        return "skipped by --skip-rename"
    if args.dry_run:
        return "dry-run: files are not placed, so rename was not planned"
    if resolved.mode is not Mode.MOVE and not args.allow_unsafe:
        return (
            f"mode is {resolved.mode.value!r}; rename requires move or --allow-unsafe"
        )
    return None


def render(payload: dict[str, Any], style: JsonStyle) -> str:
    indent = 2 if style is JsonStyle.PRETTY else None
    return json.dumps(payload, indent=indent, ensure_ascii=False)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        resolved = cli.resolve_options(args)
    except cli.MisuseError as error:
        fail(str(error))
        return EXIT_MISUSE

    try:
        ingest = cli.run_resolved(resolved=resolved, dry_run=bool(args.dry_run))
    except AdapterError as error:
        fail(str(error))
        return EXIT_CLIENT_FAILURE

    ingest_record = ingest.to_json()
    skipped = _skip_reason(args, resolved)
    rename_record: dict[str, Any] | None = None
    if skipped is None:
        rename_record = rename.rename_items(
            ingest_record,
            resolved.profile,
            dry_run=False,
            allow_unsafe=bool(args.allow_unsafe),
            on_fail=resolved.on_fail,
        ).to_json()

    payload = {
        "source": "run",
        "dry_run": bool(args.dry_run),
        "profile": resolved.profile.name,
        "library_root": str(resolved.library_root),
        "ingest": ingest_record,
        "rename": rename_record,
        "rename_skipped": skipped,
    }
    sys.stdout.write(render(payload, resolved.json_style))
    sys.stdout.write("\n")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
