"""Contract: the machine-readable run report."""

from __future__ import annotations

import json
from pathlib import Path

from tests.deploy_support import Layout, deploy, install, report

REPORT_KEYS = {
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

# Keep these in sync with contracts/report-schema.md. A new emitted name is a
# contract change, not an implementation detail.
DOCUMENTED_ACTIONS = {
    "verify_bundle",
    "cache",
    "preflight",
    "stage",
    "self_check",
    "promote",
    "rollback",
    "write_config",
    "write_record",
    "uv_install",
    "uv_uninstall",
    "remove_command",
    "remove_state",
    "purge_config",
}

DOCUMENTED_CHECKS = {
    "platform",
    "bundle",
    "config",
    "library_path",
    "source_path",
    "source_configured",
    "credentials",
    "installed_commands",
    "command_path",
    "record",
    "rollback",
    "self_check",
}


def _standard(layout: Layout) -> list[str]:
    return [
        "--library-root",
        str(layout.library),
        "--client-url",
        "http://127.0.0.1:8080",
    ]


def test_install_report_lists_ordered_actions(layout: Layout, bundle: Path) -> None:
    credential = "contract-run-report-credential"
    completed = install(
        layout,
        bundle,
        _standard(layout),
        env={"TROVIUM_CLIENT_PASSWORD": credential, "TROVIUM_CLIENT_USERNAME": "admin"},
    )

    payload = report(completed)
    assert completed.returncode == 0, payload
    assert set(payload) == REPORT_KEYS
    names = [action["action"] for action in payload["actions"]]
    order = ["verify_bundle", "cache", "stage", "self_check", "promote"]
    positions = [names.index(name) for name in order]
    assert positions == sorted(positions)
    assert names.index("write_record") > positions[-1]
    assert set(names) <= DOCUMENTED_ACTIONS
    assert {check["name"] for check in payload["checks"]} <= DOCUMENTED_CHECKS
    assert all(action["outcome"] == "ok" for action in payload["actions"])
    assert payload["version"] == "0.1.0"
    assert payload["config_path"] == str(layout.config)
    assert payload["error"] is None
    assert payload["finished_at"]

    assert credential not in completed.stdout
    assert credential not in completed.stderr
    assert credential not in layout.config.read_text(encoding="utf-8")
    record = (layout.state / "trovium" / "deployment.json").read_text()
    assert credential not in record


def test_client_username_is_not_treated_as_a_secret(
    layout: Layout, bundle: Path
) -> None:
    username = layout.root.name  # pytest names the directory after this test
    completed = install(
        layout,
        bundle,
        _standard(layout),
        env={
            "TROVIUM_CLIENT_USERNAME": username,
            "TROVIUM_CLIENT_PASSWORD": "contract-run-report-password",
        },
    )

    payload = report(completed)
    assert completed.returncode == 0, payload
    assert username in str(payload["config_path"])
    assert payload["config_path"] == str(layout.config)
    assert payload["install_root"] is not None
    assert username in payload["install_root"]


def test_status_report_has_no_actions(layout: Layout, bundle: Path) -> None:
    report(install(layout, bundle, _standard(layout)))

    completed = deploy(layout, "status", "--json", "compact")

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["operation"] == "status"
    assert payload["actions"] == []
    assert set(payload) == REPORT_KEYS
    assert {check["name"] for check in payload["checks"]} <= DOCUMENTED_CHECKS
    assert any(check["name"] == "self_check" for check in payload["checks"])


def test_forced_adoption_uses_the_documented_rollback_check(
    layout: Layout, bundle: Path
) -> None:
    layout.bin.mkdir(parents=True)
    (layout.bin / "trovium-ingest").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (layout.bin / "trovium-ingest").chmod(0o755)

    completed = install(layout, bundle, [*_standard(layout), "--force"])

    payload = report(completed)
    assert completed.returncode == 0, payload
    checks = {check["name"]: check for check in payload["checks"]}
    assert set(checks) <= DOCUMENTED_CHECKS
    assert checks["rollback"]["status"] == "warn"
