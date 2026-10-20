"""Contract tests for the trovium-deploy CLI surface."""

from __future__ import annotations

import json

import pytest

from trovium.deploy.cli import EXIT_BUNDLE, EXIT_CHECK_STALE, main


def test_status_without_record_is_not_installed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["status", "--json", "compact"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "not_installed"
    assert payload["operation"] == "status"


def test_check_without_record_is_stale(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["check", "--version", "9.9.9"])
    captured = capsys.readouterr()
    assert code == EXIT_CHECK_STALE
    assert captured.out == ""


def test_install_missing_bundle_emits_error_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["install", "--bundle", "/definitely/missing", "--json", "compact"])
    captured = capsys.readouterr()
    assert code == EXIT_BUNDLE
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "bundle_invalid"
