"""Tests for the release bundle builder helpers."""

from __future__ import annotations

import json
from pathlib import Path

from tools.release.build_bundle import manifest_for, sha256_file


def test_manifest_lists_hashed_files(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
    manifest = manifest_for(
        bundle,
        version="0.1.0",
        platform="linux-x86_64",
        uv_version="0.12.19",
        python_version="3.13.5",
    )
    files = manifest["files"]
    assert isinstance(files, dict)
    assert "install.sh" in files
    assert "manifest.json" not in files
    assert files["install.sh"] == f"sha256:{sha256_file(bundle / 'install.sh')}"
    assert json.dumps(manifest)
