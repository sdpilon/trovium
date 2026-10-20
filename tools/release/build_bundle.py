#!/usr/bin/env python3
"""Build a trovium release bundle for local tests or CI publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform as platform_module
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_SCHEMA_VERSION = 1
TOOLCHAIN_LOCK = ROOT / "tools" / "release" / "toolchain.lock.json"


@dataclass(frozen=True)
class LockedAsset:
    """One pinned artifact downloaded and verified at build time."""

    name: str
    url: str
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_platform() -> str:
    system = platform_module.system().lower()
    machine = platform_module.machine().lower()
    arch = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }.get(machine)
    if system not in {"linux", "darwin"} or arch is None:
        raise SystemExit(f"unsupported build platform: {system}/{machine}")
    return f"{system}-{arch}"


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def load_toolchain_lock(path: Path = TOOLCHAIN_LOCK) -> dict[str, Any]:
    """Read the pinned uv and CPython versions plus their digests."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read toolchain lock {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SystemExit(f"unsupported toolchain lock schema in {path}")
    for tool in ("uv", "python"):
        section = payload.get(tool)
        if not isinstance(section, dict) or not isinstance(section.get("assets"), dict):
            raise SystemExit(f"toolchain lock is missing the {tool} assets")
    return payload


def select_locked_assets(
    lock: dict[str, Any], platform_name: str
) -> tuple[LockedAsset, LockedAsset]:
    """Resolve the pinned uv and CPython artifacts for one bundle platform."""

    selected: list[LockedAsset] = []
    for tool in ("uv", "python"):
        section = lock[tool]
        asset = section["assets"].get(platform_name)
        if asset is None:
            supported = ", ".join(sorted(section["assets"]))
            raise SystemExit(
                f"toolchain lock has no {tool} asset for {platform_name}; "
                f"supported platforms: {supported}"
            )
        digest = str(asset.get("sha256", ""))
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise SystemExit(
                f"toolchain lock has an invalid digest for {tool} {platform_name}"
            )
        selected.append(
            LockedAsset(
                name=str(asset["name"]),
                url=f"{section['release_base'].rstrip('/')}/{asset['name']}",
                sha256=digest,
            )
        )
    return selected[0], selected[1]


def download_verified(asset: LockedAsset, destination: Path) -> Path:
    """Download an artifact and refuse it when the pinned digest does not match."""

    digest = hashlib.sha256()
    try:
        with (
            urllib.request.urlopen(asset.url) as response,
            destination.open("wb") as handle,
        ):
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                digest.update(chunk)
                handle.write(chunk)
    except OSError as error:
        raise SystemExit(f"cannot download {asset.url}: {error}") from error
    if digest.hexdigest() != asset.sha256:
        destination.unlink(missing_ok=True)
        raise SystemExit(f"checksum mismatch for {asset.url}")
    return destination


def prepare_locked_toolchain(
    lock: dict[str, Any], platform_name: str, workdir: Path
) -> tuple[Path, Path]:
    """Download, verify, and extract the pinned uv and CPython for a platform."""

    uv_asset, python_asset = select_locked_assets(lock, platform_name)
    uv_archive = download_verified(uv_asset, workdir / uv_asset.name)
    python_archive = download_verified(python_asset, workdir / python_asset.name)
    uv_dir = workdir / "uv"
    python_dir = workdir / "python"
    uv_dir.mkdir()
    python_dir.mkdir()
    with tarfile.open(uv_archive) as tar:
        tar.extractall(uv_dir, filter="data")
    with tarfile.open(python_archive) as tar:
        tar.extractall(python_dir, filter="data")
    uv_binary = next(path for path in uv_dir.rglob("uv") if path.is_file())
    uv_binary.chmod(0o755)
    interpreter = python_dir / "python" / "bin" / "python3"
    if not interpreter.is_file():
        raise SystemExit(f"pinned CPython archive is missing {interpreter}")
    return uv_binary, python_dir / "python"


def write_locked_licenses(bundle: Path, lock: dict[str, Any]) -> None:
    """Record the license texts of the bundled uv and CPython artifacts."""

    licenses = lock.get("licenses")
    if not isinstance(licenses, dict):
        return
    uv_urls = licenses.get("uv")
    if isinstance(uv_urls, list):
        texts = []
        for url in uv_urls:
            with urllib.request.urlopen(str(url)) as response:
                texts.append(response.read().decode("utf-8", "replace"))
        (bundle / "LICENSES" / "uv-LICENSE").write_text(
            "\n\n".join(texts), encoding="utf-8"
        )
    python_url = licenses.get("python")
    if isinstance(python_url, str):
        with urllib.request.urlopen(python_url) as response:
            (bundle / "LICENSES" / "python-LICENSE").write_text(
                response.read().decode("utf-8", "replace"), encoding="utf-8"
            )


def build_wheel(source: Path, version: str, destination: Path) -> Path:
    """Build the wheel, staging a temp source tree for a version override."""

    with tempfile.TemporaryDirectory(prefix="trovium-src-") as raw:
        staging = Path(raw)
        for name in ("pyproject.toml", "README.md", "LICENSE", "uv.lock"):
            source_file = source / name
            if source_file.exists():
                shutil.copy2(source_file, staging / name)
        shutil.copytree(source / "src", staging / "src")
        pyproject = (staging / "pyproject.toml").read_text(encoding="utf-8")
        pyproject = pyproject.replace('version = "0.1.0"', f'version = "{version}"', 1)
        (staging / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        run(["uv", "build", "--wheel", "--out-dir", str(destination)], cwd=staging)
    wheels = sorted(destination.glob("trovium-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one trovium wheel, found {len(wheels)}")
    return wheels[0]


def build_wheelhouse(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    workspace = destination.parent.parent
    requirements = workspace / "requirements.txt"
    run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements.txt",
            "-o",
            str(requirements),
        ],
        cwd=source,
    )
    venv = workspace / "venv"
    run(["uv", "venv", "--seed", str(venv)])
    python = venv / "bin" / "python"
    run(
        [
            str(python),
            "-m",
            "pip",
            "download",
            "--require-hashes",
            "-r",
            str(requirements),
            "-d",
            str(destination),
        ]
    )


def copy_toolchain(
    bundle: Path,
    *,
    uv_path: Path | None,
    python_dir: Path | None,
) -> tuple[str, str]:
    uv_version = "0.0.0"
    python_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    if uv_path is not None:
        uv_output = subprocess.run(
            [str(uv_path), "--version"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.split()
        uv_version = uv_output[1] if len(uv_output) > 1 else uv_version
        target = bundle / "toolchain" / f"uv-{uv_version}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(uv_path, target)
        target.chmod(0o755)
    if python_dir is not None:
        interpreter = python_dir / "bin" / "python3"
        python_output = subprocess.run(
            [str(interpreter), "--version"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        python_version = python_output.split()[-1]
        archive = bundle / "toolchain" / f"python-{python_version}.tar.gz"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz") as tar:
            for child in sorted(python_dir.iterdir()):
                tar.add(child, arcname=child.name)
    return uv_version, python_version


def manifest_for(
    bundle: Path, *, version: str, platform: str, uv_version: str, python_version: str
) -> dict[str, object]:
    files: dict[str, str] = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files[path.relative_to(bundle).as_posix()] = f"sha256:{sha256_file(path)}"
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "version": version,
        "platform": platform,
        "python_version": python_version,
        "uv_version": uv_version,
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--uv", type=Path, default=None)
    parser.add_argument("--python", type=Path, default=None)
    parser.add_argument(
        "--locked",
        action="store_true",
        help="download and verify the pinned uv/CPython artifacts from the lock",
    )
    args = parser.parse_args()
    if not args.local and not args.fast:
        args.local = True
    platform_name = args.platform or normalized_platform()
    lock: dict[str, Any] | None = None
    if args.locked:
        lock = load_toolchain_lock()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trovium-bundle-") as raw:
        staging = Path(raw)
        dist = staging / "dist"
        wheel = build_wheel(ROOT, args.version, dist)
        bundle = staging / f"trovium-{args.version}-{platform_name}"
        wheelhouse = bundle / "wheelhouse"
        build_wheelhouse(ROOT, wheelhouse)
        shutil.copy2(wheel, wheelhouse / wheel.name)
        shutil.copy2(ROOT / "install.sh", bundle / "install.sh")
        (bundle / "LICENSES").mkdir()
        shutil.copy2(ROOT / "LICENSE", bundle / "LICENSES" / "LICENSE")
        if lock is not None:
            args.uv, args.python = prepare_locked_toolchain(
                lock, platform_name, staging / "toolchain-dl"
            )
        uv_version, python_version = copy_toolchain(
            bundle, uv_path=args.uv, python_dir=args.python
        )
        if lock is not None:
            write_locked_licenses(bundle, lock)
        manifest = manifest_for(
            bundle,
            version=args.version,
            platform=platform_name,
            uv_version=uv_version,
            python_version=python_version,
        )
        (bundle / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        tarball = args.out / f"{bundle.name}.tar.gz"
        with tarfile.open(tarball, "w:gz") as tar:
            tar.add(bundle, arcname=bundle.name)
        digest = sha256_file(tarball)
        (Path(str(tarball) + ".sha256")).write_text(
            f"{digest}  {tarball.name}\n", encoding="utf-8"
        )
        (args.out / "VERSION").write_text(f"{args.version}\n", encoding="utf-8")
        latest = args.out / f"trovium-latest-{platform_name}.tar.gz"
        shutil.copy2(tarball, latest)
        shutil.copy2(
            Path(str(tarball) + ".sha256"),
            Path(str(latest) + ".sha256"),
        )
        print(tarball)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
