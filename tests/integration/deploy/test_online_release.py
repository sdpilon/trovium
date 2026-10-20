"""Integration: online install from the release layout (US1/SC-001)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.deploy_support import Layout, deploy, install, report
from tests.integration.deploy.release_server import release_server


def _standard(layout: Layout) -> list[str]:
    return [
        "--library-root",
        str(layout.library),
        "--source",
        str(layout.source),
    ]


def test_pinned_online_install_uses_the_versioned_asset(
    layout: Layout, bundle: Path
) -> None:
    with release_server(bundle, "0.1.0") as (base_url, _root):
        completed = install(
            layout,
            None,
            ["--release-base-url", base_url, "--version", "0.1.0", *_standard(layout)],
        )

    payload = report(completed)
    assert completed.returncode == 0
    assert payload["version"] == "0.1.0"
    assert payload["config_path"] == str(layout.config)
    assert (layout.bin / "trovium-ingest").is_file()
    status = json.loads(deploy(layout, "status", "--json", "compact").stdout)
    assert status["version"] == "0.1.0"
    assert any(
        check["name"] == "self_check" and check["status"] == "pass"
        for check in status["checks"]
    )


def test_default_online_install_resolves_the_latest_version(
    layout: Layout, bundle: Path
) -> None:
    with release_server(bundle, "0.1.0") as (base_url, _root):
        completed = install(
            layout, None, ["--release-base-url", base_url, *_standard(layout)]
        )

    payload = report(completed)
    assert completed.returncode == 0
    assert payload["version"] == "0.1.0"
    assert payload["status"] in {"ok", "degraded"}


def test_online_reinstall_uses_the_installed_check_fast_path(
    layout: Layout, bundle: Path
) -> None:
    with release_server(bundle, "0.1.0") as (base_url, root):
        first = install(
            layout, None, ["--release-base-url", base_url, *_standard(layout)]
        )
        assert first.returncode == 0

        # Remove the downloadable asset: only the check fast path can succeed.
        for asset in (root / "download" / "v0.1.0").iterdir():
            asset.unlink()
        second = install(
            layout,
            None,
            ["--release-base-url", base_url, "--non-interactive"],
        )

    payload = report(second)
    assert second.returncode == 0, payload
    assert payload["status"] == "noop"
    assert payload["actions"] == []
