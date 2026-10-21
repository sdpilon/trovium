"""Typed deployment run reports and failures.

The external contract is
``specs/002-server-deployment/contracts/report-schema.md``.  Every invocation
writes one JSON object to stdout; a human summary goes to stderr.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TextIO

from trovium.record import JsonStyle

_SECRET_VALUES: set[str] = set()
REDACTED = "***"


def register_secrets(values: Iterable[str | None]) -> None:
    """Remember credential values so any report that includes them is redacted."""

    for value in values:
        if value and len(value) >= 3:
            _SECRET_VALUES.add(value)


def clear_secrets() -> None:
    """Forget registered secrets (used between invocations in tests)."""

    _SECRET_VALUES.clear()


def redact_text(text: str) -> str:
    """Replace every registered secret in ``text`` with a fixed marker."""

    redacted = text
    for value in sorted(_SECRET_VALUES, key=len, reverse=True):
        redacted = redacted.replace(value, REDACTED)
    return redacted


class Operation(StrEnum):
    """The operation a report describes."""

    INSTALL = "install"
    UPGRADE = "upgrade"
    STATUS = "status"
    UNINSTALL = "uninstall"


class ReportStatus(StrEnum):
    """Top-level report state."""

    OK = "ok"
    NOOP = "noop"
    DEGRADED = "degraded"
    NOT_INSTALLED = "not_installed"
    ERROR = "error"


class ActionOutcome(StrEnum):
    """Outcome of one action."""

    OK = "ok"
    SKIPPED = "skipped"
    FAILED = "failed"


class CheckStatus(StrEnum):
    """Outcome of one validation check."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class Action:
    """One step taken or considered during an operation."""

    action: str
    target: str
    outcome: ActionOutcome
    detail: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "outcome": self.outcome.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Check:
    """One validation observation."""

    name: str
    status: CheckStatus
    detail: str
    remedy: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "remedy": self.remedy,
        }


@dataclass(frozen=True)
class ErrorInfo:
    """A named failure with a remedy."""

    code: str
    message: str
    remedy: str
    path: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "remedy": self.remedy,
            "path": self.path,
        }


@dataclass
class Report:
    """The full machine-readable result of one deployment invocation."""

    operation: Operation
    status: ReportStatus = ReportStatus.OK
    version: str | None = None
    previous_version: str | None = None
    config_path: str | None = None
    install_root: str | None = None
    bin_dir: str | None = None
    commands: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    error: ErrorInfo | None = None
    finished_at: str | None = None
    schema_version: int = 1

    def finish(self) -> Report:
        if self.status is ReportStatus.ERROR and self.error is None:
            self.error = _error_for_checks(self.checks)
        if self.finished_at is None:
            self.finished_at = now()
        return self

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation.value,
            "status": self.status.value,
            "version": self.version,
            "previous_version": self.previous_version,
            "config_path": self.config_path,
            "install_root": self.install_root,
            "bin_dir": self.bin_dir,
            "commands": self.commands,
            "actions": [action.to_json() for action in self.actions],
            "checks": [check.to_json() for check in self.checks],
            "next_steps": self.next_steps,
            "error": None if self.error is None else self.error.to_json(),
            "finished_at": self.finished_at,
        }


class DeployError(Exception):
    """A deployment refusal with a stable code and an operator remedy."""

    def __init__(
        self,
        code: str,
        message: str,
        remedy: str,
        *,
        exit_code: int = 5,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.remedy = remedy
        self.exit_code = exit_code
        self.path = path
        self.report: Report | None = None


def now() -> str:
    """Return an ISO 8601 UTC timestamp with a trailing Z."""

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def fresh_report(operation: Operation) -> Report:
    """Create a report with the request's operation."""

    report = Report(operation=operation)
    report.finish()
    return report


def failure_report(
    operation: Operation, failure: DeployError, partial: Report | None = None
) -> Report:
    """Build the standard error report for a deployment failure.

    When the operation already produced a report, keep its actions and
    observations so a failure still shows what happened before it stopped.
    """

    report = partial if partial is not None else Report(operation=operation)
    report.operation = operation
    report.status = ReportStatus.ERROR
    report.error = ErrorInfo(
        code=failure.code,
        message=failure.message,
        remedy=failure.remedy,
        path=failure.path,
    )
    report.checks.append(
        Check(
            name="failure",
            status=CheckStatus.FAIL,
            detail=failure.message,
            remedy=failure.remedy,
        )
    )
    return report.finish()


def status_for(checks: Iterable[Check]) -> ReportStatus:
    """Derive the top-level status: error > degraded > ok."""

    items = list(checks)
    if any(check.status is CheckStatus.FAIL for check in items):
        return ReportStatus.ERROR
    if any(check.status is CheckStatus.WARN for check in items):
        return ReportStatus.DEGRADED
    return ReportStatus.OK


def _error_for_checks(checks: Iterable[Check]) -> ErrorInfo:
    """Give an error-status report the named failure the contract requires."""

    failing = next(
        (check for check in checks if check.status is CheckStatus.FAIL), None
    )
    if failing is None:
        return ErrorInfo(
            "install_failed",
            "installation is not healthy",
            "Run trovium-deploy status and fix the failing check.",
        )
    code = {
        "library_path": "unwritable_path",
        "config": "config_invalid",
        "installed_commands": "install_failed",
        "self_check": "self_check_failed",
    }.get(failing.name, "install_failed")
    return ErrorInfo(
        code,
        failing.detail,
        failing.remedy or "Fix the failing check and retry.",
    )


def render(report: Report, style: JsonStyle) -> str:

    indent = 2 if style is JsonStyle.PRETTY else None
    payload = json.dumps(report.to_json(), indent=indent, ensure_ascii=False)
    return redact_text(payload)


def emit(report: Report, style: JsonStyle, stream: TextIO | None = None) -> None:
    """Write the JSON report to stdout (or a supplied stream)."""

    out = sys.stdout if stream is None else stream
    out.write(render(report, style))
    out.write("\n")


def human_summary(report: Report, stream: TextIO | None = None) -> None:
    """Write a concise, secret-free summary to stderr."""

    err = sys.stderr if stream is None else stream
    lines: list[str] = []
    if report.status is ReportStatus.ERROR and report.error is not None:
        lines.append(f"error: {report.error.message}\n")
        lines.append(f"remedy: {report.error.remedy}\n")
    elif report.status is ReportStatus.NOT_INSTALLED:
        lines.append("trovium is not installed\n")
    else:
        status_text = report.status.value
        if report.version:
            lines.append(f"trovium {report.version}: {status_text}\n")
        else:
            lines.append(f"trovium: {status_text}\n")
        if report.config_path:
            lines.append(f"config: {report.config_path}\n")
        if report.next_steps:
            lines.append(f"next: {report.next_steps[0]}\n")
    err.write(redact_text("".join(lines)))
