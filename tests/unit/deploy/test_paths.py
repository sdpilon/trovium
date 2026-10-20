"""Unit tests for XDG paths and platform policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from trovium.deploy.paths import (
    ALLOW_MUSL_ENV,
    Platform,
    bin_dir,
    bundle_cache_dir,
    config_file,
    ensure_supported,
    path_contains,
    state_dir,
    tool_dir,
)
from trovium.deploy.report import DeployError


def test_xdg_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TROVIUM_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("TROVIUM_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("TROVIUM_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("TROVIUM_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setenv("TROVIUM_CONFIG_FILE", str(tmp_path / "config.ini"))
    assert state_dir() == tmp_path / "state" / "trovium"
    assert bin_dir() == tmp_path / "bin"
    assert config_file() == tmp_path / "config.ini"
    assert tool_dir() == tmp_path / "data" / "trovium" / "tools" / "trovium"
    assert bundle_cache_dir("0.1.0", "linux-x86_64") == (
        tmp_path / "cache" / "trovium" / "bundles" / "0.1.0" / "linux-x86_64"
    )


def test_musl_is_refused_unless_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    platform = Platform(os="linux", arch="x86_64", libc="musl")
    with pytest.raises(DeployError):
        ensure_supported(platform)
    monkeypatch.setenv(ALLOW_MUSL_ENV, "1")
    ensure_supported(platform)


def test_path_contains(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert path_contains(tmp_path)
    assert not path_contains(tmp_path / "other")
