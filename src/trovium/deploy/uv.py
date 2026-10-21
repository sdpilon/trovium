"""The single uv subprocess boundary for deployment operations."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from trovium.deploy.report import DeployError


def _run(
    uv_path: Path,
    args: list[str],
    *,
    tool_dir: Path,
    bin_dir: Path,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(tool_dir)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)
    env["UV_NO_PROGRESS"] = "1"
    try:
        return subprocess.run(
            [str(uv_path), *args],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except OSError as error:
        raise DeployError(
            "install_failed",
            f"cannot execute uv at {uv_path}: {error}",
            "Verify the private uv toolchain exists and is executable.",
            path=str(uv_path),
        ) from error
    except subprocess.TimeoutExpired as error:
        raise DeployError(
            "install_failed",
            f"uv timed out after {timeout}s",
            "Check the server load and retry the operation.",
        ) from error


def _require_success(
    result: subprocess.CompletedProcess[str], action: str
) -> subprocess.CompletedProcess[str]:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {result.returncode}"
        raise DeployError(
            "install_failed",
            f"uv {action} failed: {tail}",
            "Inspect the uv output, verify the wheelhouse, and retry.",
        )
    return result


def tool_install(
    uv_path: Path,
    *,
    python_path: Path,
    wheelhouse: Path,
    tool_dir: Path,
    bin_dir: Path,
    wheel: Path,
    force: bool = True,
) -> None:
    """Install the trovium wheel into a uv tool environment."""

    args = [
        "tool",
        "install",
        "--python",
        str(python_path),
        "--no-index",
        "--find-links",
        str(wheelhouse),
    ]
    if force:
        args.append("--force")
    args.append(str(wheel))
    result = _run(uv_path, args, tool_dir=tool_dir, bin_dir=bin_dir)
    _require_success(result, "tool install")


def tool_uninstall(
    uv_path: Path,
    *,
    tool_dir: Path,
    bin_dir: Path,
) -> None:
    """Remove the trovium tool environment."""

    result = _run(
        uv_path,
        ["tool", "uninstall", "trovium"],
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    _require_success(result, "tool uninstall")


__all__ = ["tool_install", "tool_uninstall"]
