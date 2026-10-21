"""XDG paths, platform detection, permissions, and prompts."""

from __future__ import annotations

import os
import platform as platform_module
import sys
from dataclasses import dataclass
from pathlib import Path

from trovium.config import config_path as _config_path
from trovium.deploy.report import DeployError

STATE_HOME_ENV = "TROVIUM_STATE_HOME"
DATA_HOME_ENV = "TROVIUM_DATA_HOME"
CACHE_HOME_ENV = "TROVIUM_CACHE_HOME"
BIN_DIR_ENV = "TROVIUM_BIN_DIR"
ALLOW_MUSL_ENV = "TROVIUM_ALLOW_MUSL"


@dataclass(frozen=True)
class Platform:
    """Normalized host identity used to choose a bundle."""

    os: str
    arch: str
    libc: str | None = None

    @property
    def bundle(self) -> str:
        return f"{self.os}-{self.arch}"


def _xdg(env: str, fallback: str) -> Path:
    value = os.environ.get(env)
    return Path(value).expanduser() if value else Path.home() / fallback


def state_dir() -> Path:
    return _xdg(STATE_HOME_ENV, ".local/state") / "trovium"


def data_dir() -> Path:
    return _xdg(DATA_HOME_ENV, ".local/share") / "trovium"


def cache_dir() -> Path:
    return _xdg(CACHE_HOME_ENV, ".cache") / "trovium"


def bin_dir() -> Path:
    value = os.environ.get(BIN_DIR_ENV)
    return Path(value).expanduser() if value else Path.home() / ".local/bin"


def config_file() -> Path:
    """The canonical config path, shared with the ingest step."""

    return _config_path()


def record_path() -> Path:
    return state_dir() / "deployment.json"


def lock_path() -> Path:
    return state_dir() / "deploy.lock"


def tool_dir() -> Path:
    return data_dir() / "tools" / "trovium"


def toolchain_root() -> Path:
    return data_dir() / "toolchain"


def staging_root() -> Path:
    return state_dir() / "staging"


def wheel_cache_dir(version: str) -> Path:
    return state_dir() / "cache" / version


def bundle_cache_dir(version: str, bundle_platform: str) -> Path:
    return cache_dir() / "bundles" / version / bundle_platform


def ensure_directory(path: Path, mode: int = 0o700) -> None:
    """Create a user-owned directory and keep it owner-only."""

    try:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(mode)
    except OSError as error:
        raise DeployError(
            "unwritable_path",
            f"cannot create {path}: {error}",
            "Check the parent directory permissions and retry.",
            exit_code=3,
            path=str(path),
        ) from error


def validate_writable_path(path: Path) -> None:
    """Refuse a destination that cannot be created or written.

    Nothing is created: the nearest existing ancestor must be a writable
    directory, and the path itself must be a directory when it exists.
    """

    probe = path
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    if path.exists() and not path.is_dir():
        raise DeployError(
            "unwritable_path",
            f"{path} is not a directory",
            "Remove the file or point the matching TROVIUM_* override at a directory.",
            exit_code=3,
            path=str(path),
        )
    if not probe.is_dir():
        raise DeployError(
            "unwritable_path",
            f"{probe} is not a directory",
            "Fix the parent path and retry.",
            exit_code=3,
            path=str(probe),
        )
    if not os.access(probe, os.W_OK | os.X_OK):
        raise DeployError(
            "unwritable_path",
            f"{path} is not writable",
            "Fix the directory permissions and retry.",
            exit_code=3,
            path=str(path),
        )


def ensure_file_private(path: Path) -> None:

    try:
        path.chmod(0o600)
    except OSError as error:
        raise DeployError(
            "unwritable_path",
            f"cannot secure {path}: {error}",
            "Check the file permissions and retry.",
            exit_code=3,
            path=str(path),
        ) from error


def ensure_executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o755)
    except OSError as error:
        raise DeployError(
            "unwritable_path",
            f"cannot make {path} executable: {error}",
            "Check the file permissions and retry.",
            exit_code=3,
            path=str(path),
        ) from error


def _normalize_arch(machine: str) -> str | None:
    lowered = machine.lower()
    if lowered in {"x86_64", "amd64"}:
        return "x86_64"
    if lowered in {"aarch64", "arm64"}:
        return "aarch64"
    return None


def _libc() -> str | None:
    if platform_module.system().lower() != "linux":
        return None
    try:
        libc, _version = platform_module.libc_ver()
    except OSError:
        libc = ""
    if libc == "musl" or any(Path("/lib").glob("ld-musl-*")):
        return "musl"
    return "glibc"


def detect_platform() -> Platform:
    """Normalize the host or fail with a named unsupported platform."""

    system = platform_module.system().lower()
    machine = platform_module.machine()
    arch = _normalize_arch(machine)
    if system not in {"linux", "darwin"} or arch is None:
        raise DeployError(
            "unsupported_platform",
            f"unsupported platform: {system}/{machine}",
            "Server deployment supports Linux x86_64/aarch64 and macOS "
            "x86_64/aarch64 for development.",
            exit_code=3,
        )
    return Platform(os=system, arch=arch, libc=_libc())


def ensure_supported(platform: Platform) -> None:
    """Refuse musl until the static toolchain is verified there."""

    if platform.libc == "musl" and os.environ.get(ALLOW_MUSL_ENV) != "1":
        raise DeployError(
            "unsupported_platform",
            "musl-based Linux is not a verified deployment target yet",
            "Use a glibc-based Linux server, or set "
            f"{ALLOW_MUSL_ENV}=1 only after verifying the static toolchain.",
            exit_code=3,
        )


def path_contains(directory: Path) -> bool:
    """Return True when a directory is present in PATH."""

    target = os.path.normcase(os.path.abspath(directory))
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and os.path.normcase(os.path.abspath(entry)) == target:
            return True
    return False


def is_interactive() -> bool:
    return sys.stdin.isatty()


def prompt(label: str) -> str:
    """Prompt on stdin or /dev/tty; never read a piped script as input."""

    if sys.stdin.isatty():
        return input(f"{label}: ").strip()
    try:
        with open("/dev/tty", "r+", encoding="utf-8") as tty:
            tty.write(f"{label}: ")
            tty.flush()
            return tty.readline().strip()
    except OSError as error:
        raise DeployError(
            "misuse",
            f"no interactive terminal for {label!r}",
            "Pass the value explicitly, use a config file, or use "
            "--non-interactive with all required inputs.",
            exit_code=2,
        ) from error


__all__ = [
    "ALLOW_MUSL_ENV",
    "Platform",
    "bin_dir",
    "bundle_cache_dir",
    "cache_dir",
    "config_file",
    "data_dir",
    "detect_platform",
    "ensure_directory",
    "ensure_executable",
    "ensure_file_private",
    "ensure_supported",
    "is_interactive",
    "lock_path",
    "path_contains",
    "prompt",
    "record_path",
    "staging_root",
    "state_dir",
    "tool_dir",
    "toolchain_root",
    "validate_writable_path",
    "wheel_cache_dir",
]
