"""Contract: install.sh and trovium-deploy option handling and report shape."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.deploy_support import Layout, install, report, run

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


def _bootstrap(
    layout: Layout, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return run(layout, ["bash", "install.sh", *args, "--json", "compact"], env=env)


def _standard(layout: Layout) -> list[str]:
    return [
        "--library-root",
        str(layout.library),
        "--source",
        str(layout.source),
    ]


def test_help_lists_the_documented_surface(layout: Layout) -> None:
    completed = run(layout, ["bash", "install.sh", "--help"])

    assert completed.returncode == 0
    for option in (
        "--version",
        "--bundle",
        "--sha256",
        "--release-base-url",
        "--status",
        "--uninstall",
        "--purge",
        "--non-interactive",
        "--library-root",
        "--source",
        "--client-url",
        "--config",
        "--force",
        "--json",
    ):
        assert option in completed.stdout


def test_unknown_option_is_misuse_with_a_full_report(layout: Layout) -> None:
    completed = _bootstrap(layout, "--nonsense")

    payload = report(completed)
    assert completed.returncode == 2
    assert set(payload) == REPORT_KEYS
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "misuse"
    for key in ("version", "config_path", "install_root", "bin_dir"):
        assert payload[key] is None
    assert payload["commands"] == []
    assert payload["actions"] == []


def test_purge_requires_uninstall(layout: Layout) -> None:
    completed = _bootstrap(layout, "--purge")

    payload = report(completed)
    assert completed.returncode == 2
    assert payload["error"]["code"] == "misuse"


@pytest.mark.parametrize(
    "option",
    ["--version", "--bundle", "--sha256", "--release-base-url"],
)
def test_option_without_a_value_is_misuse(layout: Layout, option: str) -> None:
    completed = run(layout, ["bash", "install.sh", option])

    payload = report(completed)
    assert completed.returncode == 2
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "misuse"
    assert option in payload["error"]["message"]


def test_early_prerequisite_failure_emits_the_full_schema(
    layout: Layout, tmp_path: Path
) -> None:
    shim = tmp_path / "shim"
    shim.mkdir()
    for name in ("bash", "date", "sed", "tr", "mktemp", "find", "awk", "shasum"):
        found = shutil.which(name)
        if found is not None:
            (shim / name).symlink_to(found)
    completed = _bootstrap(
        layout, "--bundle", "/nonexistent.tar.gz", env={"PATH": str(shim)}
    )

    payload = report(completed)
    assert completed.returncode == 3
    assert set(payload) == REPORT_KEYS
    assert payload["error"]["code"] == "missing_prerequisite"
    assert payload["error"]["remedy"]
    assert payload["finished_at"]


def test_json_styles_contain_the_same_data(layout: Layout) -> None:
    compact = run(
        layout,
        ["bash", "install.sh", "--nonsense", "--json", "compact"],
    )
    pretty = run(
        layout,
        ["bash", "install.sh", "--nonsense", "--json", "pretty"],
    )

    assert compact.returncode == pretty.returncode == 2
    compact_payload = json.loads(compact.stdout)
    pretty_payload = json.loads(pretty.stdout)
    # Two invocations can cross a one-second boundary; everything except the
    # completion timestamp must be identical between the styles.
    assert compact_payload.pop("finished_at")
    assert pretty_payload.pop("finished_at")
    assert compact_payload == pretty_payload


def test_bootstrap_never_prints_client_credentials(
    layout: Layout, bundle: Path
) -> None:
    credential = "super-credential-contract-value"
    completed = install(
        layout,
        bundle,
        _standard(layout),
        env={"TROVIUM_CLIENT_PASSWORD": credential, "TROVIUM_CLIENT_USERNAME": "admin"},
    )

    assert completed.returncode == 0, completed.stderr
    assert credential not in completed.stdout
    assert credential not in completed.stderr
    assert credential not in layout.config.read_text(encoding="utf-8")


def test_status_and_uninstall_reject_install_only_options(layout: Layout) -> None:
    for mode in ("--status", "--uninstall"):
        completed = _bootstrap(layout, mode, "--library-root", "/tmp/x")

        payload = report(completed)
        assert completed.returncode == 2
        assert payload["error"]["code"] == "misuse"


def test_credentialed_release_url_is_refused_and_redacted(layout: Layout) -> None:
    completed = _bootstrap(
        layout,
        "--release-base-url",
        "https://user:super-credential@example.invalid/releases",
        "--version",
        "0.1.0",
    )

    payload = report(completed)
    assert completed.returncode == 2
    assert payload["error"]["code"] == "misuse"
    assert "super-credential" not in completed.stdout
    assert "super-credential" not in completed.stderr
    assert "example.invalid" not in payload["error"]["message"]


def test_non_http_release_url_is_refused(layout: Layout) -> None:
    completed = _bootstrap(
        layout, "--release-base-url", "file:///tmp/releases", "--version", "0.1.0"
    )

    payload = report(completed)
    assert completed.returncode == 2
    assert payload["error"]["code"] == "misuse"


def test_client_url_with_userinfo_is_a_config_failure(
    layout: Layout, bundle: Path
) -> None:
    completed = install(
        layout,
        bundle,
        [
            "--library-root",
            str(layout.library),
            "--client-url",
            "http://u:p@127.0.0.1/x",
        ],
    )

    payload = report(completed)
    assert completed.returncode == 7, payload
    assert payload["error"]["code"] == "config_invalid"
    assert "u:p" not in completed.stdout
    assert "u:p" not in completed.stderr
    assert not layout.config.exists()


def test_missing_downloader_names_the_prerequisite(
    layout: Layout, tmp_path: Path
) -> None:
    shim = tmp_path / "shim"
    shim.mkdir()
    for name in (
        "bash",
        "date",
        "sed",
        "tr",
        "mktemp",
        "find",
        "awk",
        "tar",
        "shasum",
        "sha256sum",
        "uname",
        "dirname",
        "head",
    ):
        found = shutil.which(name)
        if found is not None:
            (shim / name).symlink_to(found)

    completed = _bootstrap(layout, "--version", "0.9.0", env={"PATH": str(shim)})

    payload = report(completed)
    assert completed.returncode == 3
    assert payload["error"]["code"] == "missing_prerequisite"
    assert "curl" in payload["error"]["message"]


def test_unwritable_command_path_fails_before_writing_anything(
    layout: Layout, bundle: Path, tmp_path: Path
) -> None:
    blocked = tmp_path / "blocked-bin"
    blocked.write_text("not a directory", encoding="utf-8")

    completed = install(
        layout,
        bundle,
        ["--library-root", str(layout.library), "--source", str(layout.source)],
        env={"TROVIUM_BIN_DIR": str(blocked)},
    )

    payload = report(completed)
    assert completed.returncode == 3
    assert payload["error"]["code"] == "unwritable_path"
    assert not layout.config.exists()
    assert not (layout.state / "trovium" / "deployment.json").exists()
