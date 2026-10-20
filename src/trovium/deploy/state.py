"""Deployment record, atomic writes, and the deployment lock."""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trovium.deploy import paths
from trovium.deploy.report import DeployError, now

RECORD_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CommandCheck:
    """One installed command's self-check result."""

    name: str
    status: str
    exit_code: int
    detail: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "exit_code": self.exit_code,
            "detail": self.detail,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> CommandCheck:
        return cls(
            name=str(payload["name"]),
            status=str(payload["status"]),
            exit_code=int(payload["exit_code"]),
            detail=None if payload.get("detail") is None else str(payload["detail"]),
        )


@dataclass(frozen=True)
class SelfCheckResult:
    """The result of running every installed command with --help."""

    status: str
    checked_at: str
    commands: tuple[CommandCheck, ...] = ()
    duration_ms: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked_at": self.checked_at,
            "commands": [command.to_json() for command in self.commands],
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> SelfCheckResult:
        return cls(
            status=str(payload["status"]),
            checked_at=str(payload["checked_at"]),
            commands=tuple(
                CommandCheck.from_json(item) for item in payload.get("commands", [])
            ),
            duration_ms=int(payload.get("duration_ms", 0)),
        )


@dataclass(frozen=True)
class LastOperation:
    """The last deployment operation recorded for status."""

    operation: str
    status: str
    at: str
    error_code: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "at": self.at,
            "error_code": self.error_code,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> LastOperation:
        return cls(
            operation=str(payload["operation"]),
            status=str(payload["status"]),
            at=str(payload["at"]),
            error_code=(
                None
                if payload.get("error_code") is None
                else str(payload["error_code"])
            ),
        )


@dataclass(frozen=True)
class DeploymentRecord:
    """The per-user state of one trovium installation."""

    version: str
    previous_version: str | None
    installed_at: str
    config_path: str
    tool_dir: str
    bin_dir: str
    uv_path: str
    python_path: str
    commands: tuple[str, ...]
    wheel_cache: str
    wheel_sha256: str
    bundle_platform: str
    last_self_check: SelfCheckResult
    last_operation: LastOperation
    schema_version: int = RECORD_SCHEMA_VERSION
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "version": self.version,
            "previous_version": self.previous_version,
            "installed_at": self.installed_at,
            "config_path": self.config_path,
            "tool_dir": self.tool_dir,
            "bin_dir": self.bin_dir,
            "uv_path": self.uv_path,
            "python_path": self.python_path,
            "commands": list(self.commands),
            "wheel_cache": self.wheel_cache,
            "wheel_sha256": self.wheel_sha256,
            "bundle_platform": self.bundle_platform,
            "last_self_check": self.last_self_check.to_json(),
            "last_operation": self.last_operation.to_json(),
        }
        payload.update(self.extra)
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> DeploymentRecord:
        try:
            return cls(
                schema_version=int(payload.get("schema_version", 0)),
                version=str(payload["version"]),
                previous_version=(
                    None
                    if payload.get("previous_version") is None
                    else str(payload["previous_version"])
                ),
                installed_at=str(payload["installed_at"]),
                config_path=str(payload["config_path"]),
                tool_dir=str(payload["tool_dir"]),
                bin_dir=str(payload["bin_dir"]),
                uv_path=str(payload["uv_path"]),
                python_path=str(payload["python_path"]),
                commands=tuple(str(item) for item in payload.get("commands", [])),
                wheel_cache=str(payload["wheel_cache"]),
                wheel_sha256=str(payload["wheel_sha256"]),
                bundle_platform=str(payload["bundle_platform"]),
                last_self_check=SelfCheckResult.from_json(
                    payload.get("last_self_check", {})
                ),
                last_operation=LastOperation.from_json(
                    payload.get("last_operation", {})
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DeployError(
                "internal",
                f"deployment record is invalid: {error}",
                "Reinstall trovium or remove the damaged record after inspecting it.",
            ) from error


def read_record(path: Path | None = None) -> DeploymentRecord | None:
    """Read the deployment record, returning None when absent."""

    target = paths.record_path() if path is None else path
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeployError(
            "internal",
            f"cannot read deployment record {target}: {error}",
            "Inspect the record and reinstall if it is damaged.",
            path=str(target),
        ) from error
    if not isinstance(payload, dict):
        raise DeployError(
            "internal",
            f"deployment record {target} is not a JSON object",
            "Inspect the record and reinstall if it is damaged.",
            path=str(target),
        )
    return DeploymentRecord.from_json(payload)


def write_record(record: DeploymentRecord, path: Path | None = None) -> Path:
    """Atomically replace the deployment record with mode 0600."""

    target = paths.record_path() if path is None else path
    paths.ensure_directory(target.parent)
    temporary = target.with_name(f".{target.name}.tmp")
    payload = json.dumps(record.to_json(), indent=2, ensure_ascii=False) + "\n"
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(target)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise DeployError(
            "unwritable_path",
            f"cannot write deployment record {target}: {error}",
            "Check the state directory permissions and retry.",
            exit_code=3,
            path=str(target),
        ) from error
    return target


@contextmanager
def acquire_lock(path: Path | None = None) -> Iterator[None]:
    """Serialize deployment operations, failing clearly on contention."""

    target = paths.lock_path() if path is None else path
    paths.ensure_directory(target.parent)
    try:
        handle = target.open("a+", encoding="utf-8")
    except OSError as error:
        raise DeployError(
            "unwritable_path",
            f"cannot open deployment lock {target}: {error}",
            "Check the state directory permissions and retry.",
            exit_code=3,
            path=str(target),
        ) from error
    deadline = time.monotonic() + 1.0
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.monotonic() >= deadline:
                    raise DeployError(
                        "lock_held",
                        f"another deployment operation holds {target}",
                        "Wait for the other operation to finish, then retry.",
                        exit_code=6,
                        path=str(target),
                    ) from error
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def record_operation(
    record: DeploymentRecord,
    *,
    operation: str,
    status: str,
    error_code: str | None = None,
) -> DeploymentRecord:
    """Return a copy with the last operation updated."""

    return DeploymentRecord(
        version=record.version,
        previous_version=record.previous_version,
        installed_at=record.installed_at,
        config_path=record.config_path,
        tool_dir=record.tool_dir,
        bin_dir=record.bin_dir,
        uv_path=record.uv_path,
        python_path=record.python_path,
        commands=record.commands,
        wheel_cache=record.wheel_cache,
        wheel_sha256=record.wheel_sha256,
        bundle_platform=record.bundle_platform,
        last_self_check=record.last_self_check,
        last_operation=LastOperation(
            operation=operation,
            status=status,
            at=now(),
            error_code=error_code,
        ),
        schema_version=record.schema_version,
        extra=record.extra,
    )


__all__ = [
    "RECORD_SCHEMA_VERSION",
    "CommandCheck",
    "DeploymentRecord",
    "LastOperation",
    "SelfCheckResult",
    "acquire_lock",
    "read_record",
    "record_operation",
    "write_record",
]
