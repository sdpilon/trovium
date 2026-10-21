"""Contract: uninstall, purge, and the no-installation no-op."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from tests.deploy_support import Layout, deploy, install, report, run


def _standard(layout: Layout) -> list[str]:
    return ["--library-root", str(layout.library), "--source", str(layout.source)]


def _bootstrap_uninstall(
    layout: Layout, bundle: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    return run(
        layout,
        [
            "bash",
            "install.sh",
            "--bundle",
            str(bundle),
            "--uninstall",
            *args,
            "--json",
            "compact",
        ],
    )


def _inventory(layout: Layout) -> dict[str, str]:
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(layout.library.rglob("*"))
        if path.is_file()
    }


def test_uninstall_removes_commands_and_keeps_config_and_media(
    layout: Layout, bundle: Path
) -> None:
    report(install(layout, bundle, _standard(layout)))
    before = _inventory(layout)

    completed = deploy(layout, "uninstall", "--json", "compact")

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["status"] == "ok"
    assert not (layout.bin / "trovium-ingest").exists()
    assert not (layout.bin / "trovium-deploy").exists()
    assert layout.config.exists()
    assert not (layout.state / "trovium" / "deployment.json").exists()
    assert _inventory(layout) == before


def test_purge_removes_only_the_config(layout: Layout, bundle: Path) -> None:
    report(install(layout, bundle, _standard(layout)))
    before = _inventory(layout)

    completed = deploy(layout, "uninstall", "--purge", "--json", "compact")

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert not layout.config.exists()
    assert _inventory(layout) == before
    assert any(action["action"] == "purge_config" for action in payload["actions"])


def test_repeated_uninstall_is_a_noop(layout: Layout, bundle: Path) -> None:
    report(install(layout, bundle, _standard(layout)))
    deploy(layout, "uninstall", "--json", "compact")

    completed = _bootstrap_uninstall(layout, bundle)

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["status"] == "noop"
    assert layout.config.exists()


def test_purge_without_a_record_removes_only_the_config(
    layout: Layout, bundle: Path
) -> None:
    layout.config.parent.mkdir(parents=True)
    layout.config.write_text("[library]\nroot = /media\n", encoding="utf-8")
    layout.config.chmod(0o600)

    completed = _bootstrap_uninstall(layout, bundle, "--purge")

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["status"] == "ok"
    assert [action["action"] for action in payload["actions"]] == ["purge_config"]
    assert not layout.config.exists()


def test_purge_reports_an_unremovable_config(layout: Layout, bundle: Path) -> None:
    layout.config.parent.mkdir(parents=True)
    layout.config.mkdir()  # a directory where the config file belongs

    completed = _bootstrap_uninstall(layout, bundle, "--purge")

    payload = json.loads(completed.stdout)
    assert completed.returncode == 3
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "unwritable_path"
    assert layout.config.is_dir()


def test_uninstall_without_a_record_and_without_purge_is_a_noop(
    layout: Layout, bundle: Path
) -> None:
    layout.config.parent.mkdir(parents=True)
    layout.config.write_text("[library]\nroot = /media\n", encoding="utf-8")

    completed = _bootstrap_uninstall(layout, bundle)

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["status"] == "noop"
    assert payload["actions"] == []
    assert layout.config.exists()


def test_uninstall_removes_every_cached_version(
    layout: Layout, bundle: Path, newer_bundle: Path
) -> None:
    report(install(layout, bundle, _standard(layout)))
    report(install(layout, newer_bundle, _standard(layout)))
    cache = layout.state / "trovium" / "cache"
    assert any(cache.iterdir())

    completed = deploy(layout, "uninstall", "--json", "compact")

    assert completed.returncode == 0
    assert not cache.exists() or not any(cache.iterdir())


def test_uninstall_reports_incomplete_cleanup_as_a_failure(
    layout: Layout, bundle: Path
) -> None:
    report(install(layout, bundle, _standard(layout)))
    cache = layout.state / "trovium" / "cache"
    victim = next(path for path in cache.iterdir() if path.is_dir())
    victim.chmod(0o500)
    try:
        completed = deploy(layout, "uninstall", "--json", "compact")
        payload = json.loads(completed.stdout)
        assert completed.returncode == 3
        assert payload["status"] == "error"
        assert payload["error"]["code"] == "unwritable_path"
        assert "cannot remove" in payload["error"]["message"]
        assert (layout.state / "trovium" / "deployment.json").exists()
        assert any(action["action"] == "uv_uninstall" for action in payload["actions"])
    finally:
        victim.chmod(0o700)
