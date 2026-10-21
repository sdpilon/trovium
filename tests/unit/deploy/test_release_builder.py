"""Tests for the release bundle builder helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
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


def test_toolchain_lock_pins_both_tools_for_linux() -> None:
    from tools.release import build_bundle as builder

    lock = builder.load_toolchain_lock()
    assert lock["schema_version"] == 1
    for platform_name in ("linux-x86_64", "linux-aarch64"):
        uv_asset, python_asset = builder.select_locked_assets(lock, platform_name)
        assert uv_asset.url.startswith("https://github.com/astral-sh/uv/releases/")
        assert uv_asset.name.endswith("unknown-linux-gnu.tar.gz")
        assert len(uv_asset.sha256) == 64
        assert python_asset.name.startswith("cpython-3.13.16+")
        assert len(python_asset.sha256) == 64


def test_toolchain_lock_refuses_an_unsupported_platform() -> None:
    import pytest
    from tools.release import build_bundle as builder

    lock = builder.load_toolchain_lock()
    with pytest.raises(SystemExit):
        builder.select_locked_assets(lock, "darwin-aarch64")


def test_toolchain_lock_refuses_an_invalid_digest() -> None:
    import copy

    import pytest
    from tools.release import build_bundle as builder

    lock = copy.deepcopy(builder.load_toolchain_lock())
    lock["uv"]["assets"]["linux-x86_64"]["sha256"] = "not-a-digest"
    with pytest.raises(SystemExit):
        builder.select_locked_assets(lock, "linux-x86_64")


def test_tarball_writing_is_reproducible(tmp_path: Path) -> None:
    import os

    from tools.release.build_bundle import write_tarball

    bundle = tmp_path / "bundle"
    (bundle / "wheelhouse").mkdir(parents=True)
    payload = bundle / "wheelhouse" / "trovium-0.1.0-py3-none-any.whl"
    payload.write_bytes(b"wheel")
    (bundle / "manifest.json").write_text("{}\n", encoding="utf-8")

    first = tmp_path / "first.tar.gz"
    os.utime(payload, (100, 100))
    write_tarball(bundle, first)
    second = tmp_path / "second.tar.gz"
    os.utime(payload, (200, 200))
    write_tarball(bundle, second)

    assert first.read_bytes() == second.read_bytes()


def test_build_wheel_stages_the_requested_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.release import build_bundle as builder

    source = tmp_path / "source"
    (source / "src" / "trovium").mkdir(parents=True)
    (source / "src" / "trovium" / "__init__.py").write_text("", encoding="utf-8")
    (source / "pyproject.toml").write_text(
        '[project]\nname = "trovium"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (source / "README.md").write_text("readme", encoding="utf-8")
    (source / "LICENSE").write_text("license", encoding="utf-8")
    (source / "uv.lock").write_text("lock", encoding="utf-8")
    destination = tmp_path / "dist"
    destination.mkdir()
    seen: dict[str, str] = {}

    def _fake_run(command: list[str], cwd: Path | None = None) -> None:
        assert cwd is not None
        seen["pyproject"] = (cwd / "pyproject.toml").read_text(encoding="utf-8")
        (destination / "trovium-0.2.0-py3-none-any.whl").write_bytes(b"wheel")

    monkeypatch.setattr(builder, "run", _fake_run)
    wheel = builder.build_wheel(source, "0.2.0", destination)

    assert wheel.name == "trovium-0.2.0-py3-none-any.whl"
    assert 'version = "0.2.0"' in seen["pyproject"]
    assert 'version = "0.1.0"' not in seen["pyproject"]


def test_locked_licenses_are_written_into_the_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.release import build_bundle as builder

    bundle = tmp_path / "bundle"
    (bundle / "LICENSES").mkdir(parents=True)

    class _Response:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    bodies = {
        "https://example.invalid/LICENSE-APACHE": b"apache",
        "https://example.invalid/LICENSE-MIT": b"mit",
        "https://example.invalid/PYTHON": b"python-license",
    }

    def _urlopen(url: str) -> _Response:
        return _Response(bodies[url])

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    builder.write_locked_licenses(
        bundle,
        {
            "licenses": {
                "uv": [
                    "https://example.invalid/LICENSE-APACHE",
                    "https://example.invalid/LICENSE-MIT",
                ],
                "python": "https://example.invalid/PYTHON",
            }
        },
    )

    uv_license = (bundle / "LICENSES" / "uv-LICENSE").read_text()
    assert "apache" in uv_license
    assert "mit" in uv_license
    assert (bundle / "LICENSES" / "python-LICENSE").read_text() == "python-license"
