"""``trovium-deploy``: install, check, status, and uninstall trovium."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from trovium.deploy.installer import InstallOptions, check, install, status, uninstall
from trovium.deploy.report import (
    DeployError,
    Operation,
    Report,
    ReportStatus,
    emit,
    failure_report,
    human_summary,
)
from trovium.deploy.state import read_record
from trovium.record import JsonStyle

EXIT_OK = 0
EXIT_CHECK_STALE = 1
EXIT_MISUSE = 2
EXIT_PREFLIGHT = 3
EXIT_BUNDLE = 4
EXIT_INSTALL = 5
EXIT_LOCK = 6
EXIT_CONFIG = 7


def _json_style(value: str) -> JsonStyle:
    return JsonStyle(value)


def _test_override(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line surface from contracts/cli.md."""

    parser = argparse.ArgumentParser(
        prog="trovium-deploy",
        description="Install, upgrade, inspect, or uninstall trovium.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="install or upgrade")
    install_parser.add_argument("--bundle", type=Path, required=True)
    install_parser.add_argument("--non-interactive", action="store_true")
    install_parser.add_argument("--library-root", type=Path)
    source_group = install_parser.add_mutually_exclusive_group()
    source_group.add_argument("--source", type=Path)
    source_group.add_argument("--client-url")
    install_parser.add_argument("--config", type=Path)
    install_parser.add_argument(
        "--profile",
        help="media profile for the generated config (default: video)",
    )
    install_parser.add_argument("--force", action="store_true")
    install_parser.add_argument(
        "--json",
        choices=[item.value for item in JsonStyle],
        default=JsonStyle.PRETTY.value,
    )
    install_parser.add_argument("--uv", type=Path, help=argparse.SUPPRESS)
    install_parser.add_argument("--python", type=Path, help=argparse.SUPPRESS)

    check_parser = subparsers.add_parser("check", help="fast current-version check")
    check_parser.add_argument("--version", required=True)
    check_parser.add_argument(
        "--json",
        choices=[item.value for item in JsonStyle],
        default=JsonStyle.PRETTY.value,
    )

    status_parser = subparsers.add_parser(
        "status", help="read-only installation status"
    )
    status_parser.add_argument("--config", type=Path)
    status_parser.add_argument(
        "--json",
        choices=[item.value for item in JsonStyle],
        default=JsonStyle.PRETTY.value,
    )

    uninstall_parser = subparsers.add_parser(
        "uninstall", help="remove the installation"
    )
    uninstall_parser.add_argument("--purge", action="store_true")
    uninstall_parser.add_argument("--config", type=Path)
    uninstall_parser.add_argument(
        "--json",
        choices=[item.value for item in JsonStyle],
        default=JsonStyle.PRETTY.value,
    )
    return parser


def _operation(command: str) -> Operation:
    if command == "uninstall":
        return Operation.UNINSTALL
    if command == "status":
        return Operation.STATUS
    return Operation.INSTALL


def _failure_with_context(operation: Operation, failure: DeployError) -> Report:
    """Name the failure and keep the active installation visible in the report."""

    report = failure_report(operation, failure, failure.report)
    try:
        record = read_record()
    except DeployError:
        return report
    if record is not None:
        if report.version is None:
            report.version = record.version
        if report.previous_version is None:
            report.previous_version = record.version
        if report.config_path is None:
            report.config_path = record.config_path
        if report.install_root is None:
            report.install_root = record.tool_dir
        if report.bin_dir is None:
            report.bin_dir = record.bin_dir
        if not report.commands:
            report.commands = list(record.commands)
    return report


def _dispatch(args: argparse.Namespace) -> Report | None:
    if args.command == "install":
        return install(
            InstallOptions(
                bundle=args.bundle,
                non_interactive=bool(args.non_interactive),
                library_root=args.library_root,
                source=args.source,
                client_url=args.client_url,
                config=args.config,
                profile=args.profile,
                force=bool(args.force),
                json_style=_json_style(args.json),
                uv_override=args.uv or _test_override("TROVIUM_TEST_UV"),
                python_override=args.python or _test_override("TROVIUM_TEST_PYTHON"),
            )
        )
    if args.command == "check":
        return check(args.version)
    if args.command == "status":
        return status(args.config)
    return uninstall(purge=bool(args.purge), config_override=args.config)


def _requested_json_style(argv: Sequence[str]) -> JsonStyle:
    """Read ``--json`` before parsing so a parse error can still honour it."""

    values = list(argv)
    for index, item in enumerate(values[:-1]):
        if item == "--json":
            try:
                return _json_style(values[index + 1])
            except ValueError:
                return JsonStyle.PRETTY
    return JsonStyle.PRETTY


def _requested_operation(argv: Sequence[str]) -> Operation:
    """Name the attempted operation when argparse cannot (missing/bad options)."""

    commands = {
        Operation.INSTALL.value,
        Operation.STATUS.value,
        Operation.UNINSTALL.value,
    }
    for item in argv:
        if item in commands:
            return _operation(item)
    return Operation.INSTALL


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: dispatch, emit one report, and map the exit code."""

    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(raw)
    except SystemExit as exit_error:
        code = exit_error.code if isinstance(exit_error.code, int) else EXIT_MISUSE
        if code == 0:  # --help and --version exit successfully
            return 0
        failure = DeployError(
            "misuse",
            "invalid command line arguments",
            "Run trovium-deploy --help and retry.",
            exit_code=EXIT_MISUSE,
        )
        misuse_report = failure_report(_requested_operation(raw), failure)
        emit(misuse_report, _requested_json_style(raw))
        human_summary(misuse_report)
        return code
    operation = _operation(args.command)
    try:
        report = _dispatch(args)
    except DeployError as failure:
        report = _failure_with_context(operation, failure)
        emit(report, _json_style(getattr(args, "json", JsonStyle.PRETTY.value)))
        human_summary(report)
        return failure.exit_code
    except Exception as error:  # pragma: no cover - defensive boundary
        unexpected = DeployError(
            "internal",
            f"unexpected deployment failure: {error}",
            "Inspect the error and retry; report a bug if it recurs.",
        )
        report = _failure_with_context(operation, unexpected)
        emit(report, _json_style(getattr(args, "json", JsonStyle.PRETTY.value)))
        human_summary(report)
        return EXIT_INSTALL
    if report is None:
        return EXIT_CHECK_STALE
    emit(report, _json_style(getattr(args, "json", JsonStyle.PRETTY.value)))
    human_summary(report)
    if report.status is ReportStatus.ERROR:
        return EXIT_PREFLIGHT
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
