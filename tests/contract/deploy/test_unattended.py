"""Contract: unattended install, inputs, and precedence."""

from __future__ import annotations

import json
from pathlib import Path

from tests.deploy_support import Layout, install, report


def _standard(layout: Layout) -> list[str]:
    return ["--library-root", str(layout.library), "--source", str(layout.source)]


def test_non_interactive_missing_input_fails_before_changes(
    layout: Layout, bundle: Path
) -> None:
    completed = install(layout, bundle, [])

    payload = report(completed)
    assert completed.returncode == 2
    assert payload["error"]["code"] == "misuse"
    assert "library root" in payload["error"]["message"]
    assert "TROVIUM_LIBRARY_ROOT" in payload["error"]["remedy"]
    assert not layout.config.exists()
    assert not (layout.state / "trovium" / "deployment.json").exists()


def test_config_file_supplies_all_inputs_and_is_preserved(
    layout: Layout, tmp_path: Path, bundle: Path
) -> None:
    supplied = tmp_path / "supplied.ini"
    supplied.write_text(
        "[meta]\nschema_version = 1\n"
        f"[library]\nroot = {layout.library}\n"
        f"[source]\nmode = disk\npath = {layout.source}\n",
        encoding="utf-8",
    )
    supplied.chmod(0o600)
    before = supplied.read_bytes()

    completed = install(layout, bundle, ["--config", str(supplied)])

    payload = report(completed)
    assert completed.returncode == 0, payload
    assert payload["config_path"] == str(layout.config)
    assert supplied.read_bytes() == before
    canonical = layout.config.read_text(encoding="utf-8")
    assert f"root = {layout.library}" in canonical
    assert any(action["action"] == "write_config" for action in payload["actions"])


def test_environment_inputs_are_used_when_flags_are_absent(
    layout: Layout, bundle: Path
) -> None:
    env = {
        "TROVIUM_LIBRARY_ROOT": str(layout.library),
        "TROVIUM_SOURCE": str(layout.source),
    }

    completed = install(layout, bundle, [], env=env)

    payload = report(completed)
    assert completed.returncode == 0, payload
    text = layout.config.read_text(encoding="utf-8")
    assert f"root = {layout.library}" in text
    assert f"path = {layout.source}" in text


def test_cli_inputs_win_over_environment(
    layout: Layout, tmp_path: Path, bundle: Path
) -> None:
    other = tmp_path / "other-library"
    other.mkdir()

    completed = install(
        layout,
        bundle,
        ["--library-root", str(layout.library)],
        env={"TROVIUM_LIBRARY_ROOT": str(other)},
    )

    payload = report(completed)
    assert completed.returncode == 0, payload
    text = layout.config.read_text(encoding="utf-8")
    assert f"root = {layout.library}" in text
    assert str(other) not in text


def test_conflicting_environment_sources_are_misuse(
    layout: Layout, bundle: Path
) -> None:
    completed = install(
        layout,
        bundle,
        [],
        env={
            "TROVIUM_LIBRARY_ROOT": str(layout.library),
            "TROVIUM_SOURCE": str(layout.source),
            "TROVIUM_CLIENT_URL": "http://127.0.0.1:8080",
        },
    )

    payload = report(completed)
    assert completed.returncode == 2
    assert payload["error"]["code"] == "misuse"


def test_unattended_report_records_no_prompts(layout: Layout, bundle: Path) -> None:
    completed = install(layout, bundle, _standard(layout))

    payload = report(completed)
    assert completed.returncode == 0
    # stdin is /dev/null, so a prompt would have failed the install.
    assert payload["actions"]
    assert all(action["outcome"] == "ok" for action in payload["actions"])
    status = json.loads((layout.state / "trovium" / "deployment.json").read_text())
    assert status["last_operation"]["operation"] == "install"
