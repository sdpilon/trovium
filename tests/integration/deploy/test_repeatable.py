"""Integration: repeatable installs and the check/bundle-cache fast paths (US2)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from tests.deploy_support import (
    Layout,
    deploy,
    install,
    report,
)
from tests.integration.deploy.release_server import release_server

STANDARD = ("--library-root", "--source")


def _standard(layout: Layout) -> list[str]:
    return [
        "--library-root",
        str(layout.library),
        "--source",
        str(layout.source),
    ]


def test_check_reports_current_and_stale_versions(layout: Layout, bundle: Path) -> None:
    report(install(layout, bundle, _standard(layout)))

    current = deploy(layout, "check", "--version", "0.1.0", "--json", "compact")
    assert current.returncode == 0
    payload = json.loads(current.stdout)
    assert payload["status"] == "noop"
    assert payload["version"] == "0.1.0"

    stale = deploy(layout, "check", "--version", "9.9.9", "--json", "compact")
    assert stale.returncode == 1
    assert stale.stdout.strip() == ""


def test_identical_install_finishes_quickly(layout: Layout, bundle: Path) -> None:
    report(install(layout, bundle, _standard(layout)))

    started = time.monotonic()
    second = report(install(layout, bundle, _standard(layout)))
    elapsed = time.monotonic() - started

    assert second["status"] == "noop"
    assert elapsed < 30


def test_cached_bundle_is_reused_without_the_release_server(
    layout: Layout, bundle: Path
) -> None:
    with release_server(bundle, "0.1.0") as (base_url, _root):
        first = install(
            layout,
            None,
            ["--release-base-url", base_url, "--version", "0.1.0", *_standard(layout)],
        )
        assert first.returncode == 0

    # The release server is gone; the verified cache must carry the reinstall.
    cached = layout.cache / "trovium" / "bundles" / "0.1.0"
    assert any(cached.iterdir())

    second = install(
        layout,
        None,
        [
            "--release-base-url",
            base_url,
            "--version",
            "0.1.0",
            *_standard(layout),
        ],
        env={"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9"},
    )
    payload = report(second)
    assert second.returncode == 0, payload
    assert payload["version"] == "0.1.0"


def test_status_is_read_only(layout: Layout, bundle: Path) -> None:
    report(install(layout, bundle, _standard(layout)))
    record_path = layout.state / "trovium" / "deployment.json"
    before = record_path.read_bytes()

    status = deploy(layout, "status", "--json", "compact")

    assert status.returncode == 0
    assert status.stdout
    assert record_path.read_bytes() == before
