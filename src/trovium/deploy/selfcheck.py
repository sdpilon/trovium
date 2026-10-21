"""Non-destructive self-checks for every installed console script."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from trovium.deploy.report import now
from trovium.deploy.state import CommandCheck, SelfCheckResult


def _sanitized_env(bin_dir: Path) -> dict[str, str]:
    allowed = {
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "PYTHONIOENCODING",
        "TMPDIR",
        "USER",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["LC_ALL"] = "C"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_selfcheck(
    bin_dir: Path,
    commands: tuple[str, ...],
    *,
    timeout: int = 15,
) -> SelfCheckResult:
    """Run each console script with --help in a sanitized environment."""

    started = time.monotonic()
    env = _sanitized_env(bin_dir)
    results: list[CommandCheck] = []
    for command in commands:
        executable = bin_dir / command
        if not executable.is_file() or not os.access(executable, os.X_OK):
            results.append(
                CommandCheck(
                    name=command,
                    status="fail",
                    exit_code=127,
                    detail=f"missing executable: {executable}",
                )
            )
            continue
        try:
            completed = subprocess.run(
                [str(executable), "--help"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            results.append(
                CommandCheck(
                    name=command,
                    status="fail",
                    exit_code=124,
                    detail=f"--help timed out after {timeout}s",
                )
            )
            continue
        except OSError as error:
            results.append(
                CommandCheck(
                    name=command,
                    status="fail",
                    exit_code=126,
                    detail=f"cannot execute: {error}",
                )
            )
            continue
        output = f"{completed.stdout}\n{completed.stderr}"
        if completed.returncode != 0:
            results.append(
                CommandCheck(
                    name=command,
                    status="fail",
                    exit_code=completed.returncode,
                    detail=f"--help exited {completed.returncode}",
                )
            )
        elif "Traceback (most recent call last)" in output:
            results.append(
                CommandCheck(
                    name=command,
                    status="fail",
                    exit_code=0,
                    detail="--help printed a Python traceback",
                )
            )
        else:
            results.append(
                CommandCheck(
                    name=command,
                    status="pass",
                    exit_code=0,
                    detail="--help exited 0",
                )
            )
    duration_ms = int((time.monotonic() - started) * 1000)
    status = "pass" if all(item.status == "pass" for item in results) else "fail"
    return SelfCheckResult(
        status=status,
        checked_at=now(),
        commands=tuple(results),
        duration_ms=duration_ms,
    )


__all__ = ["run_selfcheck"]
