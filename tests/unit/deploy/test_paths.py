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


def test_prompt_without_a_terminal_is_misuse(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    from trovium.deploy.paths import prompt

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    def _no_tty(*args: object, **kwargs: object) -> object:
        raise OSError("no terminal")

    monkeypatch.setattr(builtins, "open", _no_tty)
    with pytest.raises(DeployError) as error:
        prompt("Library root")
    assert error.value.code == "misuse"
    assert "terminal" in error.value.message


def test_unwritable_directory_is_named(tmp_path: Path) -> None:
    from trovium.deploy.paths import ensure_directory

    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    with pytest.raises(DeployError) as error:
        ensure_directory(blocked)
    assert error.value.code == "unwritable_path"


def test_two_xdg_roots_are_disjoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv("TROVIUM_STATE_HOME", str(first / "state"))
    monkeypatch.setenv("TROVIUM_DATA_HOME", str(first / "data"))
    monkeypatch.setenv("TROVIUM_CACHE_HOME", str(first / "cache"))
    monkeypatch.setenv("TROVIUM_BIN_DIR", str(first / "bin"))
    first_paths = {state_dir(), tool_dir(), bin_dir()}

    monkeypatch.setenv("TROVIUM_STATE_HOME", str(second / "state"))
    monkeypatch.setenv("TROVIUM_DATA_HOME", str(second / "data"))
    monkeypatch.setenv("TROVIUM_CACHE_HOME", str(second / "cache"))
    monkeypatch.setenv("TROVIUM_BIN_DIR", str(second / "bin"))
    second_paths = {state_dir(), tool_dir(), bin_dir()}

    assert first_paths.isdisjoint(second_paths)


def test_unknown_machine_is_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    import platform as platform_module

    from trovium.deploy.paths import detect_platform

    monkeypatch.setattr(platform_module, "system", lambda: "Linux")
    monkeypatch.setattr(platform_module, "machine", lambda: "sparc64")
    with pytest.raises(DeployError) as error:
        detect_platform()
    assert error.value.code == "unsupported_platform"


def test_libc_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    import platform as platform_module

    from trovium.deploy import paths as paths_module

    monkeypatch.setattr(platform_module, "system", lambda: "Linux")
    monkeypatch.setattr(platform_module, "libc_ver", lambda: ("glibc", "2.39"))
    assert paths_module._libc() == "glibc"
    monkeypatch.setattr(platform_module, "libc_ver", lambda: ("musl", "1.2.5"))
    assert paths_module._libc() == "musl"
    monkeypatch.setattr(platform_module, "system", lambda: "Darwin")
    assert paths_module._libc() is None


def test_ensure_executable_sets_the_execute_bit(tmp_path: Path) -> None:
    from trovium.deploy.paths import ensure_executable

    binary = tmp_path / "binary"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o600)
    ensure_executable(binary)
    assert binary.stat().st_mode & 0o111
