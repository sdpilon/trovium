"""Unit tests for the installed-command self-check."""

from __future__ import annotations

from pathlib import Path

from trovium.deploy.selfcheck import run_selfcheck


def _script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)


def test_all_commands_pass(tmp_path: Path) -> None:
    _script(tmp_path / "good", "exit 0")
    result = run_selfcheck(tmp_path, ("good",))
    assert result.status == "pass"
    assert result.commands[0].exit_code == 0


def test_failing_command_is_named(tmp_path: Path) -> None:
    _script(tmp_path / "bad", "echo boom >&2; exit 7")
    result = run_selfcheck(tmp_path, ("bad",))
    assert result.status == "fail"
    assert result.commands[0].name == "bad"
    assert result.commands[0].exit_code == 7


def test_missing_command_fails(tmp_path: Path) -> None:
    result = run_selfcheck(tmp_path, ("missing",))
    assert result.status == "fail"
    assert result.commands[0].exit_code == 127
