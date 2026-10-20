"""Unit tests for bundle manifest verification and wheel metadata."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from trovium.deploy.bundle import BundleInfo, load_bundle
from trovium.deploy.paths import Platform
from trovium.deploy.report import DeployError


def _hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _wheel(path: Path, *, version: str = "0.1.0") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"trovium-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: trovium\nVersion: {version}\n",
        )
        archive.writestr(
            f"trovium-{version}.dist-info/entry_points.txt",
            "[console_scripts]\ntrovium-ingest = trovium.cli:main\n",
        )


def _bundle(
    tmp_path: Path, *, version: str = "0.1.0", wheel_version: str = "0.1.0"
) -> Path:
    root = tmp_path / "bundle"
    wheel = root / "wheelhouse" / f"trovium-{version}-py3-none-any.whl"
    _wheel(wheel, version=wheel_version)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": version,
                "platform": "linux-x86_64",
                "python_version": "3.13.5",
                "uv_version": "0.12.19",
                "files": {
                    f"wheelhouse/{wheel.name}": _hash(wheel),
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def test_bundle_verifies_and_reads_wheel(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    info = load_bundle(
        root,
        platform=Platform(os="linux", arch="x86_64"),
        uv_override=tmp_path / "uv",
        python_override=tmp_path / "python",
    )
    assert info.version == "0.1.0"
    assert info.wheel.commands == ("trovium-ingest",)


def test_tampered_wheel_is_refused(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    wheel = next((root / "wheelhouse").glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"tamper")
    with pytest.raises(DeployError) as error:
        load_bundle(
            root,
            platform=Platform(os="linux", arch="x86_64"),
            uv_override=tmp_path / "uv",
            python_override=tmp_path / "python",
        )
    assert error.value.code == "bundle_integrity"


def test_wheel_version_mismatch_is_refused(tmp_path: Path) -> None:
    root = _bundle(tmp_path, wheel_version="0.2.0")
    with pytest.raises(DeployError) as error:
        load_bundle(
            root,
            platform=Platform(os="linux", arch="x86_64"),
            uv_override=tmp_path / "uv",
            python_override=tmp_path / "python",
        )
    assert error.value.code == "bundle_invalid"


def test_absolute_manifest_path_is_refused(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"] = {"/etc/passwd": "sha256:" + "0" * 64}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DeployError) as error:
        _load(root, tmp_path)
    assert error.value.code == "bundle_invalid"


def test_traversal_manifest_path_is_refused(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"] = {"../escape": "sha256:" + "0" * 64}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DeployError) as error:
        _load(root, tmp_path)
    assert error.value.code == "bundle_invalid"


def test_missing_manifest_file_is_refused(tmp_path: Path) -> None:
    root = _bundle(tmp_path, version="0.1.0")
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"]["wheelhouse/absent.whl"] = "sha256:" + "0" * 64
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DeployError) as error:
        _load(root, tmp_path)
    assert error.value.code == "bundle_invalid"


def test_wrong_platform_manifest_is_refused(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["platform"] = "linux-aarch64"
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DeployError) as error:
        _load(root, tmp_path)
    assert error.value.code == "bundle_invalid"


def test_incomplete_manifest_is_refused(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "manifest.json").write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(DeployError) as error:
        _load(root, tmp_path)
    assert error.value.code == "bundle_invalid"


def test_unsafe_python_tarball_is_refused(tmp_path: Path) -> None:
    import tarfile

    from trovium.deploy.bundle import extract_python

    archive = tmp_path / "python.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("evil-link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(DeployError) as error:
        extract_python(archive, tmp_path / "python")
    assert error.value.code == "bundle_invalid"


def _load(root: Path, tmp_path: Path) -> BundleInfo:
    return load_bundle(
        root,
        platform=Platform(os="linux", arch="x86_64"),
        uv_override=tmp_path / "uv",
        python_override=tmp_path / "python",
    )
