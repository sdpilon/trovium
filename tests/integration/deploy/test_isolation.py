"""Integration: isolation, force takeover, and direct-install refusal."""

from __future__ import annotations

import json
import os
import sys
import tarfile
from pathlib import Path

from tests.deploy_support import (
    Layout,
    deploy,
    install,
    report,
    run,
)


def _standard(layout: Layout) -> list[str]:
    return [
        "--library-root",
        str(layout.library),
        "--source",
        str(layout.source),
    ]


def _second_layout(root: Path) -> Layout:
    home = root / "home"
    library = root / "library"
    source = root / "source"
    for directory in (home, library, source):
        directory.mkdir(parents=True)
    return Layout(
        root=root,
        home=home,
        library=library,
        source=source,
        config=root / "config" / "config.ini",
        bin=root / "bin",
        state=root / "state",
        data=root / "data",
        cache=root / "cache",
    )


def test_unmanaged_commands_are_refused_without_force(
    layout: Layout, bundle: Path
) -> None:
    layout.bin.mkdir(parents=True)
    (layout.bin / "trovium-ingest").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (layout.bin / "trovium-ingest").chmod(0o755)

    completed = install(layout, bundle, _standard(layout))

    payload = report(completed)
    assert completed.returncode == 3
    assert payload["error"]["code"] == "unmanaged_install"
    assert (layout.bin / "trovium-ingest").read_text() == "#!/bin/sh\nexit 0\n"


def test_force_adopts_an_unmanaged_install_and_reports_no_rollback(
    layout: Layout, bundle: Path
) -> None:
    layout.bin.mkdir(parents=True)
    (layout.bin / "trovium-ingest").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (layout.bin / "trovium-ingest").chmod(0o755)

    completed = install(layout, bundle, [*_standard(layout), "--force"])

    payload = report(completed)
    assert completed.returncode == 0, payload
    rollback = [check for check in payload["checks"] if check["name"] == "rollback"]
    assert rollback
    assert rollback[0]["status"] == "warn"
    assert "rollback is unavailable" in rollback[0]["detail"]
    record = json.loads((layout.state / "trovium" / "deployment.json").read_text())
    assert record["rollback_available"] is False


def test_install_from_the_active_tool_environment_is_refused(
    layout: Layout, bundle: Path, tmp_path: Path
) -> None:
    report(install(layout, bundle, _standard(layout)))
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(bundle) as archive:
        archive.extractall(extracted, filter="data")

    completed = deploy(
        layout,
        "install",
        "--bundle",
        str(extracted),
        "--non-interactive",
        "--library-root",
        str(layout.library),
        "--uv",
        os.environ.get("UV", "uv"),
        "--python",
        sys.executable,
        "--json",
        "compact",
    )

    payload = report(completed)
    assert completed.returncode == 5
    assert payload["error"]["code"] == "install_failed"
    assert "install.sh" in payload["error"]["remedy"]
    assert (layout.bin / "trovium-ingest").is_file()


def test_two_users_do_not_share_commands_config_or_state(
    layout: Layout, bundle: Path, newer_bundle: Path, tmp_path: Path
) -> None:
    second = _second_layout(tmp_path / "second")
    first_report = report(install(layout, bundle, _standard(layout)))
    second_report = report(install(second, bundle, _standard(second)))
    assert first_report["status"] == "ok"
    assert second_report["status"] == "ok"

    first_config = layout.config.read_bytes()
    first_record = (layout.state / "trovium" / "deployment.json").read_bytes()

    upgrade = report(install(second, newer_bundle, _standard(second)))
    assert upgrade["version"] == "0.2.0"
    assert layout.config.read_bytes() == first_config
    assert (layout.state / "trovium" / "deployment.json").read_bytes() == first_record

    uninstall = deploy(second, "uninstall", "--json", "compact")
    assert uninstall.returncode == 0
    assert not (second.bin / "trovium-ingest").exists()

    health = run(layout, [str(layout.bin / "trovium-ingest"), "--help"])
    assert health.returncode == 0
    assert layout.config.read_bytes() == first_config
    status = deploy(layout, "status", "--json", "compact")
    assert json.loads(status.stdout)["version"] == "0.1.0"
