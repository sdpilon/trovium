"""Integration: offline installation from a local bundle (US2, SC-010)."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

from tests.deploy_support import Layout, deploy, install, report, run

ALLOWED_WHEELS = {
    "anyio",
    "certifi",
    "h11",
    "httpcore",
    "httpx",
    "idna",
    "trovium",
    "typing_extensions",
}


def test_offline_install_succeeds_without_network_access(
    layout: Layout, bundle: Path
) -> None:
    completed = install(
        layout,
        bundle,
        ["--library-root", str(layout.library), "--source", str(layout.source)],
        env={
            "UV_OFFLINE": "1",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
        },
    )

    payload = report(completed)
    assert completed.returncode == 0, payload
    assert payload["status"] in {"ok", "degraded"}
    assert payload["version"] == "0.1.0"

    help_result = run(layout, [str(layout.bin / "trovium-ingest"), "--help"])
    assert help_result.returncode == 0, help_result.stderr
    status = deploy(layout, "status", "--json", "compact")
    assert status.returncode == 0
    assert json.loads(status.stdout)["version"] == "0.1.0"


def test_bundle_ships_only_the_runtime_dependency_set(bundle: Path) -> None:
    with tarfile.open(bundle) as archive:
        names = archive.getnames()

    wheels = {
        Path(name).name.split("-")[0]
        for name in names
        if name.endswith(".whl") and "/wheelhouse/" in name
    }
    assert wheels == ALLOWED_WHEELS
    assert any(name.endswith("/LICENSES/LICENSE") for name in names)
    assert not any("/toolchain/" in name for name in names), (
        "a fast local bundle uses the host toolchain"
    )
