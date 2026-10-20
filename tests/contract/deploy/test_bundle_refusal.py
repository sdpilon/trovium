"""Contract: every bundle defect is refused with exit 4 and no changes."""

from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.deploy_support import Layout, install, report

Mutation = Callable[[Path, dict[str, Any]], None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tamper_wheel(root: Path, manifest: dict[str, Any]) -> None:
    wheel = next((root / "wheelhouse").glob("trovium-*.whl"))
    data = bytearray(wheel.read_bytes())
    data[100] ^= 0xFF
    wheel.write_bytes(bytes(data))


def _wrong_platform(root: Path, manifest: dict[str, Any]) -> None:
    manifest["platform"] = "linux-s390x"


def _wrong_version(root: Path, manifest: dict[str, Any]) -> None:
    manifest["version"] = "9.9.9"


def _traversal(root: Path, manifest: dict[str, Any]) -> None:
    files = dict(manifest["files"])
    files["../escape.txt"] = "sha256:" + "0" * 64
    manifest["files"] = files


def _rewrite(bundle: Path, destination: Path, mutate: Mutation) -> Path:
    work = Path(tempfile.mkdtemp(prefix="trovium-tamper-"))
    with tarfile.open(bundle) as archive:
        archive.extractall(work, filter="data")
    root = next(path for path in work.iterdir() if path.is_dir())
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(root, manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with tarfile.open(destination, "w:gz") as archive:
        archive.add(root, arcname=root.name)
    Path(f"{destination}.sha256").write_text(
        f"{_sha256(destination)}  {destination.name}\n", encoding="utf-8"
    )
    return destination


@pytest.mark.parametrize(
    ("case", "mutation", "expected"),
    [
        pytest.param("tampered_wheel", _tamper_wheel, "bundle_invalid", id="wheel"),
        pytest.param(
            "wrong_platform", _wrong_platform, "bundle_invalid", id="platform"
        ),
        pytest.param("wrong_version", _wrong_version, "bundle_invalid", id="version"),
        pytest.param("traversal", _traversal, "bundle_invalid", id="traversal"),
    ],
)
def test_bundle_defects_are_refused_before_changes(
    layout: Layout,
    bundle: Path,
    tmp_path: Path,
    case: str,
    mutation: Mutation,
    expected: str,
) -> None:
    tampered = _rewrite(bundle, tmp_path / f"{case}.tar.gz", mutation)

    completed = install(
        layout,
        tampered,
        ["--library-root", str(layout.library), "--source", str(layout.source)],
    )

    payload = report(completed)
    assert completed.returncode == 4, payload
    assert payload["error"]["code"] == expected
    assert not layout.config.exists()
    assert not (layout.bin / "trovium-ingest").exists()
    assert not (layout.state / "trovium" / "deployment.json").exists()


def test_outer_checksum_mismatch_is_refused(
    layout: Layout, bundle: Path, tmp_path: Path
) -> None:
    wrong = "0" * 64

    completed = install(
        layout,
        bundle,
        ["--sha256", wrong, "--library-root", str(layout.library)],
    )

    payload = report(completed)
    assert completed.returncode == 4
    assert payload["error"]["code"] == "bundle_integrity"
    assert not layout.config.exists()


def test_tampered_tarball_with_a_stale_sidecar_is_refused(
    layout: Layout, bundle: Path, tmp_path: Path
) -> None:
    tampered = tmp_path / bundle.name
    data = bytearray(bundle.read_bytes())
    data[-100] ^= 0xFF
    tampered.write_bytes(bytes(data))
    (tmp_path / f"{bundle.name}.sha256").write_text(
        Path(f"{bundle}.sha256").read_text(encoding="utf-8"), encoding="utf-8"
    )

    completed = install(layout, tampered, ["--library-root", str(layout.library)])

    payload = report(completed)
    assert completed.returncode == 4
    assert payload["error"]["code"] == "bundle_integrity"
    assert not layout.config.exists()


def test_local_directory_bundle_is_refused_by_the_bootstrap(
    layout: Layout, bundle: Path, tmp_path: Path
) -> None:
    extracted = tmp_path / "extracted"
    with tarfile.open(bundle) as archive:
        archive.extractall(extracted, filter="data")

    completed = install(layout, extracted, ["--library-root", str(layout.library)])

    payload = report(completed)
    assert completed.returncode == 4
    assert payload["error"]["code"] == "bundle_invalid"
