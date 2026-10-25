"""Unit tests for the deployment record and lock."""

from __future__ import annotations

import json
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


def test_record_rejects_relative_paths(tmp_path: Path) -> None:
    record = _record()
    payload = record.to_json()
    payload["bin_dir"] = "relative/bin"
    with pytest.raises(DeployError):
        read_record(_write_payload(tmp_path, payload))


def test_record_rejects_an_empty_command_list(tmp_path: Path) -> None:
    payload = _record().to_json()
    payload["commands"] = []
    with pytest.raises(DeployError):
        read_record(_write_payload(tmp_path, payload))


def test_atomic_replacement_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "deployment.json"
    record = _record()
    write_record(record, path)
    first = path.read_bytes()
    write_record(record, path)
    assert path.read_bytes() == first
    assert not list(tmp_path.glob(".deployment.json.tmp"))


def test_extra_keys_survive_a_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "deployment.json"
    payload = _record().to_json()
    payload["rollback_available"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = read_record(path)
    assert loaded is not None
    assert loaded.extra["rollback_available"] is False


def test_lock_contention_is_named(tmp_path: Path) -> None:
    import fcntl

    path = tmp_path / "deploy.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(DeployError) as error, acquire_lock(path):
            pass
        assert error.value.code == "lock_held"
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_payload(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
