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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_SCHEMA_VERSION = 1


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
    requirements = destination.parent / "requirements.txt"
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
    venv = destination.parent / "venv"
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
    args = parser.parse_args()
    if not args.local and not args.fast:
        args.local = True
    platform_name = args.platform or normalized_platform()
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
        uv_version, python_version = copy_toolchain(
            bundle, uv_path=args.uv, python_dir=args.python
        )
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
