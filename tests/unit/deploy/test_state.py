"""Unit tests for the deployment record and lock."""

from __future__ import annotations

from pathlib import Path

import pytest

from trovium.deploy.report import DeployError, now
from trovium.deploy.state import (
    CommandCheck,
    DeploymentRecord,
    LastOperation,
    SelfCheckResult,
    acquire_lock,
    read_record,
    write_record,
)


def _record() -> DeploymentRecord:
    check = SelfCheckResult(
        status="pass",
        checked_at=now(),
        commands=(CommandCheck(name="trovium-ingest", status="pass", exit_code=0),),
        duration_ms=1,
    )
    return DeploymentRecord(
        version="0.1.0",
        previous_version=None,
        installed_at=now(),
        config_path="/tmp/config.ini",
        tool_dir="/tmp/tools/trovium",
        bin_dir="/tmp/bin",
        uv_path="/tmp/toolchain/uv",
        python_path="/tmp/toolchain/bin/python3",
        commands=("trovium-ingest",),
        wheel_cache="/tmp/cache/0.1.0",
        wheel_sha256="abc",
        bundle_platform="linux-x86_64",
        last_self_check=check,
        last_operation=LastOperation(operation="install", status="ok", at=now()),
    )


def test_record_round_trip_and_permissions(tmp_path: Path) -> None:
    path = tmp_path / "deployment.json"
    record = _record()
    write_record(record, path)
    loaded = read_record(path)
    assert loaded is not None
    assert loaded.version == "0.1.0"
    assert loaded.commands == ("trovium-ingest",)
    assert path.stat().st_mode & 0o777 == 0o600


def test_missing_record_returns_none(tmp_path: Path) -> None:
    assert read_record(tmp_path / "missing.json") is None


def test_corrupt_record_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "deployment.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DeployError):
        read_record(path)


def test_lock_can_be_acquired(tmp_path: Path) -> None:
    path = tmp_path / "deploy.lock"
    with acquire_lock(path):
        assert path.exists()
