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


def test_status_precedence_is_error_then_degraded_then_ok() -> None:
    from trovium.deploy.report import status_for

    assert status_for([]) is ReportStatus.OK
    assert (
        status_for([Check(name="a", status=CheckStatus.PASS, detail="ok")])
        is ReportStatus.OK
    )
    assert (
        status_for([Check(name="a", status=CheckStatus.WARN, detail="warn")])
        is ReportStatus.DEGRADED
    )
    assert (
        status_for(
            [
                Check(name="a", status=CheckStatus.WARN, detail="warn"),
                Check(name="b", status=CheckStatus.FAIL, detail="fail"),
            ]
        )
        is ReportStatus.ERROR
    )


def test_report_keeps_stable_nulls_and_error_shape() -> None:
    payload = Report(operation=Operation.STATUS).to_json()
    for key in (
        "version",
        "previous_version",
        "config_path",
        "install_root",
        "bin_dir",
        "error",
        "finished_at",
    ):
        assert payload[key] is None
    assert payload["commands"] == []
    assert payload["actions"] == []
    assert payload["checks"] == []
    assert payload["next_steps"] == []

    failure = Report(
        operation=Operation.INSTALL,
        status=ReportStatus.ERROR,
        error=ErrorInfo(code="x", message="m", remedy="r"),
    ).finish()
    rendered = render(failure, JsonStyle.COMPACT)
    assert json.loads(rendered)["error"] == {
        "code": "x",
        "message": "m",
        "remedy": "r",
        "path": None,
    }


def test_registered_secrets_are_redacted_everywhere() -> None:
    from trovium.deploy.report import clear_secrets, register_secrets

    credential = "unit-credential-value"
    register_secrets([credential, None, ""])
    try:
        report = Report(
            operation=Operation.INSTALL,
            version="0.1.0",
            actions=[
                Action(
                    action="write_config",
                    target=f"/tmp/{credential}",
                    outcome=ActionOutcome.OK,
                    detail=f"value {credential}",
                )
            ],
            next_steps=[f"export PASSWORD={credential}"],
        ).finish()
        compact = render(report, JsonStyle.COMPACT)
        pretty = render(report, JsonStyle.PRETTY)
        assert credential not in compact
        assert credential not in pretty
        assert "***" in compact
    finally:
        clear_secrets()
