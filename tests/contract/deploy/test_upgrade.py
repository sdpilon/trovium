"""Contract: upgrade and downgrade report fields and atomic activation."""

from __future__ import annotations

import json
from pathlib import Path

from tests.deploy_support import Layout, deploy, install, report


def _standard(layout: Layout) -> list[str]:
    return ["--library-root", str(layout.library), "--source", str(layout.source)]


def test_upgrade_report_fields_and_config_preservation(
    layout: Layout, bundle: Path, newer_bundle: Path
) -> None:
    report(install(layout, bundle, _standard(layout)))
    with layout.config.open("a", encoding="utf-8") as handle:
        handle.write("\n# operator note\n")
    before = layout.config.read_bytes()

    payload = report(install(layout, newer_bundle, _standard(layout)))

    assert payload["operation"] == "upgrade"
    assert payload["version"] == "0.2.0"
    assert payload["previous_version"] == "0.1.0"
    assert layout.config.read_bytes() == before
    assert payload["commands"] == [
        "trovium-deploy",
        "trovium-ingest",
        "trovium-rename",
    ]


def test_downgrade_by_pinned_bundle(
    layout: Layout, bundle: Path, newer_bundle: Path
) -> None:
    report(install(layout, newer_bundle, _standard(layout)))

    payload = report(install(layout, bundle, _standard(layout)))

    assert payload["operation"] == "upgrade"
    assert payload["version"] == "0.1.0"
    assert payload["previous_version"] == "0.2.0"


def test_failed_upgrade_does_not_activate_the_new_version(
    layout: Layout, bundle: Path, newer_bundle: Path, broken_bundle: Path
) -> None:
    report(install(layout, newer_bundle, _standard(layout)))
    record_before = (layout.state / "trovium" / "deployment.json").read_bytes()

    completed = install(layout, broken_bundle, _standard(layout))

    payload = report(completed)
    assert completed.returncode == 5
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "self_check_failed"
    assert payload["version"] == "0.2.0"
    assert payload["config_path"] == str(layout.config)
    assert (layout.state / "trovium" / "deployment.json").read_bytes() == record_before
    status = json.loads(deploy(layout, "status", "--json", "compact").stdout)
    assert status["version"] == "0.2.0"
    assert status["status"] in {"ok", "degraded"}
