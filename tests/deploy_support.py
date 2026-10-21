"""Helpers shared by the deployment integration tests and their fixtures."""

from __future__ import annotations

import fcntl
import json
import os
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(
    os.environ.get(
        "TROVIUM_ACCEPT_CACHE", Path(tempfile.gettempdir()) / "trovium-accept-bundles"
    )
)


def platform_name() -> str:
    machine = platform.machine().lower()
    arch = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    return f"{platform.system().lower()}-{arch.get(machine, machine)}"


PLATFORM = platform_name()


@dataclass(frozen=True)
class Layout:
    """One isolated per-user deployment tree."""

    root: Path
    home: Path
    library: Path
    source: Path
    config: Path
    bin: Path
    state: Path
    data: Path
    cache: Path

    @property
    def environment(self) -> dict[str, str]:
        return {
            "HOME": str(self.home),
            "TROVIUM_BIN_DIR": str(self.bin),
            "TROVIUM_CONFIG_FILE": str(self.config),
            "TROVIUM_STATE_HOME": str(self.state),
            "TROVIUM_DATA_HOME": str(self.data),
            "TROVIUM_CACHE_HOME": str(self.cache),
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
        }


def make_layout(root: Path) -> Layout:
    """Create the directory tree for one isolated deployment."""

    home = root / "home"
    library = root / "library"
    source = root / "source"
    for directory in (home, library, source / "Show.S01"):
        directory.mkdir(parents=True)
    (source / "Show.S01" / "Show.S01E01.mkv").write_text("episode", encoding="utf-8")
    return Layout(
        root=root,
        home=home,
        library=library,
        source=source,
        config=root / "config" / "config.ini",
        bin=root / "bin",
        state=root / "state",
        data=root / "data",
        cache=root / "cache",
    )


def extract_bundle(bundle: Path, destination: Path) -> Path:
    """Extract a bundle tarball and return its top-level directory."""

    import tarfile

    destination.mkdir(parents=True)
    with tarfile.open(bundle) as archive:
        archive.extractall(destination, filter="data")
    roots = [path for path in destination.iterdir() if path.is_dir()]
    assert len(roots) == 1
    return roots[0]


@contextmanager
def _bundle_lock(directory: Path) -> Iterator[None]:
    """Serialize bundle builds across concurrent test processes."""

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def build_bundle(version: str) -> Path:

    directory = CACHE / version / PLATFORM
    bundle = directory / f"trovium-{version}-{PLATFORM}.tar.gz"
    with _bundle_lock(directory):
        if bundle.is_file() and Path(f"{bundle}.sha256").is_file():
            return bundle
        build = directory / "build"
        shutil.rmtree(build, ignore_errors=True)
        build.mkdir(parents=True)
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "tools/release/build_bundle.py",
                "--fast",
                "--version",
                version,
                "--out",
                str(build),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            env={**os.environ, "UV_CACHE_DIR": str(CACHE / "uv-cache")},
        )
        shutil.copy2(build / bundle.name, bundle)
        shutil.copy2(Path(f"{build / bundle.name}.sha256"), Path(f"{bundle}.sha256"))
        shutil.rmtree(build, ignore_errors=True)
    return bundle


def build_broken_bundle(version: str = "0.2.1") -> Path:
    """Build (or reuse) a bundle whose staged self-check fails."""

    good = build_bundle(version)
    directory = CACHE / "broken" / version / PLATFORM
    broken = directory / "broken-bundle.tar.gz"
    with _bundle_lock(directory):
        if broken.is_file() and Path(f"{broken}.sha256").is_file():
            return broken
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "tests/fixtures/deploy/make_broken_bundle.py",
                str(good),
                str(broken),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            env={**os.environ, "UV_CACHE_DIR": str(CACHE / "uv-cache")},
        )
    return broken


def run(
    layout: Layout,
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path = ROOT,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Run a command in the layout's environment with stdin closed."""

    environment = {**layout.environment, **(env or {})}
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def install(
    layout: Layout,
    bundle_path: Path | None,
    args: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the documented bootstrap, with a local bundle when one is given."""

    command = ["bash", "install.sh"]
    if bundle_path is not None:
        command += ["--bundle", str(bundle_path)]
    command += [
        "--non-interactive",
        *(args or []),
        "--json",
        "compact",
    ]
    return run(layout, command, env=env)


def report(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Parse the single JSON report on stdout."""

    assert completed.stdout.strip(), completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def deploy(
    layout: Layout, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the installed trovium-deploy command."""

    return run(layout, [str(layout.bin / "trovium-deploy"), *args], env=env)
