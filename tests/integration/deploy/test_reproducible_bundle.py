"""Integration: two builds of one version produce one byte-identical archive."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from tests.deploy_support import ROOT

VERSION = "0.9.8"


def _build(out: Path) -> Path:
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            "tools/release/build_bundle.py",
            "--fast",
            "--version",
            VERSION,
            "--out",
            str(out),
        ],
        cwd=ROOT,
        check=True,
        timeout=180,
    )
    archives = sorted(out.glob(f"trovium-{VERSION}-*.tar.gz"))
    assert len(archives) == 1, archives
    return archives[0]


def test_two_builds_of_the_same_version_are_identical(tmp_path: Path) -> None:
    first = _build(tmp_path / "first")
    second = _build(tmp_path / "second")

    assert first.name == second.name
    assert (
        hashlib.sha256(first.read_bytes()).digest()
        == hashlib.sha256(second.read_bytes()).digest()
    )
