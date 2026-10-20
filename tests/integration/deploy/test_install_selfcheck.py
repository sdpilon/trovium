"""Integration: a failed staged self-check never reaches promotion (US1)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.deploy_support import Layout, deploy, install, report, run


def _standard(layout: Layout) -> list[str]:
    return [
        "--library-root",
        str(layout.library),
        "--source",
        str(layout.source),
    ]


def test_failed_staged_self_check_keeps_the_active_version(
    layout: Layout, bundle: Path, broken_bundle: Path
) -> None:
    baseline = report(install(layout, bundle, _standard(layout)))
    assert baseline["version"] == "0.1.0"
    record_before = (layout.state / "trovium" / "deployment.json").read_bytes()

    completed = install(layout, broken_bundle, _standard(layout))

    payload = report(completed)
    assert completed.returncode == 5
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "self_check_failed"
    assert payload["version"] == "0.1.0"
    assert "trovium-broken" in payload["error"]["message"]
    assert (layout.state / "trovium" / "deployment.json").read_bytes() == record_before

    status = json.loads(deploy(layout, "status", "--json", "compact").stdout)
    assert status["version"] == "0.1.0"
    help_result = run(layout, [str(layout.bin / "trovium-ingest"), "--help"])
    assert help_result.returncode == 0


def test_failed_first_install_promotes_nothing(
    layout: Layout, broken_bundle: Path
) -> None:
    completed = install(layout, broken_bundle, _standard(layout))

    payload = report(completed)
    assert completed.returncode == 5
    assert payload["error"]["code"] == "self_check_failed"
    assert not (layout.state / "trovium" / "deployment.json").exists()
    assert not (layout.bin / "trovium-ingest").exists()
    assert not (layout.bin / "trovium-deploy").exists()
