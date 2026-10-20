"""Unit tests for the uv subprocess boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from trovium.deploy.report import DeployError
from trovium.deploy.uv import tool_install, tool_uninstall


def _fake_uv(path: Path, *, exit_code: int = 0) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$UV_TEST_LOG"\n'
        'printf "UV_TOOL_DIR=%s\\n" "$UV_TOOL_DIR" >> "$UV_TEST_LOG"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_tool_install_uses_private_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "uv.log"
    monkeypatch.setenv("UV_TEST_LOG", str(log))
    uv = tmp_path / "uv"
    _fake_uv(uv)
    wheel = tmp_path / "trovium-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    tool_install(
        uv,
        python_path=tmp_path / "python",
        wheelhouse=tmp_path / "wheelhouse",
        tool_dir=tmp_path / "tools",
        bin_dir=tmp_path / "bin",
        wheel=wheel,
    )
    text = log.read_text(encoding="utf-8")
    assert "tool\ninstall" in text
    assert "--no-index" in text
    assert "--find-links" in text
    assert f"UV_TOOL_DIR={tmp_path / 'tools'}" in text


def test_tool_install_failure_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "uv.log"
    monkeypatch.setenv("UV_TEST_LOG", str(log))
    uv = tmp_path / "uv"
    _fake_uv(uv, exit_code=7)
    with pytest.raises(DeployError) as error:
        tool_install(
            uv,
            python_path=tmp_path / "python",
            wheelhouse=tmp_path / "wheelhouse",
            tool_dir=tmp_path / "tools",
            bin_dir=tmp_path / "bin",
            wheel=tmp_path / "wheel.whl",
        )
    assert error.value.code == "install_failed"


def test_tool_uninstall_uses_private_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = tmp_path / "uv.log"
    monkeypatch.setenv("UV_TEST_LOG", str(log))
    uv = tmp_path / "uv"
    _fake_uv(uv)
    tool_uninstall(uv, tool_dir=tmp_path / "tools", bin_dir=tmp_path / "bin")
    text = log.read_text(encoding="utf-8")
    assert "tool\nuninstall\ntrovium" in text
    assert f"UV_TOOL_DIR={tmp_path / 'tools'}" in text
