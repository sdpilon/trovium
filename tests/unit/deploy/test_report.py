"""Contract-level tests for deployment report serialization."""

from __future__ import annotations

import json

from trovium.deploy.report import (
    Action,
    ActionOutcome,
    Check,
    CheckStatus,
    ErrorInfo,
    Operation,
    Report,
    ReportStatus,
    render,
)
from trovium.record import JsonStyle


def test_report_has_every_contract_key() -> None:
    report = Report(
        operation=Operation.INSTALL,
        status=ReportStatus.NOOP,
        version="0.1.0",
        previous_version="0.1.0",
        checks=[Check(name="record", status=CheckStatus.PASS, detail="current")],
        actions=[Action(action="verify_bundle", target="x", outcome=ActionOutcome.OK)],
    ).finish()
    payload = report.to_json()
    assert set(payload) == {
        "schema_version",
        "operation",
        "status",
        "version",
        "previous_version",
        "config_path",
        "install_root",
        "bin_dir",
        "commands",
        "actions",
        "checks",
        "next_steps",
        "error",
        "finished_at",
    }
    assert payload["finished_at"].endswith("Z")


def test_error_report_and_style_parity() -> None:
    report = Report(
        operation=Operation.INSTALL,
        status=ReportStatus.ERROR,
        error=ErrorInfo(code="bundle_integrity", message="bad", remedy="retry"),
    ).finish()
    compact = json.loads(render(report, JsonStyle.COMPACT))
    pretty = json.loads(render(report, JsonStyle.PRETTY))
    assert compact == pretty
    assert compact["error"]["code"] == "bundle_integrity"
