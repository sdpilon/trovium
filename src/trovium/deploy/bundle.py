"""Release bundle manifest, checksum verification, and wheel metadata."""

from __future__ import annotations

import configparser
import hashlib
import json
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from trovium.deploy.paths import Platform
from trovium.deploy.report import DeployError

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WheelInfo:
    """The trovium wheel and its console scripts."""

    path: Path
    version: str
    commands: tuple[str, ...]
    sha256: str


@dataclass(frozen=True)
class BundleInfo:
    """A verified bundle ready for installation."""

    root: Path
    version: str
    platform: str
    python_version: str
    uv_version: str
    wheel: WheelInfo
    uv_path: Path | None
    python_tarball: Path | None
    files: dict[str, str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeployError(
            "bundle_invalid",
            f"cannot read bundle manifest {path}: {error}",
            "Download the bundle again and verify its checksum sidecar.",
            exit_code=4,
            path=str(path),
        ) from error
    if not isinstance(payload, dict):
        raise DeployError(
            "bundle_invalid",
            "bundle manifest is not a JSON object",
            "Download the bundle again and verify its checksum sidecar.",
            exit_code=4,
        )
    return payload


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise DeployError(
            "bundle_invalid",
            f"unsafe path in bundle manifest: {value}",
            "Download the bundle from the official release and retry.",
            exit_code=4,
            path=value,
        )
    return path


def _verify_files(root: Path, files: dict[str, str]) -> None:
    for name, expected in files.items():
        relative = _safe_relative(name)
        target = root.joinpath(*relative.parts)
        if not target.is_file():
            raise DeployError(
                "bundle_invalid",
                f"bundle file is missing: {name}",
                "Download the bundle again and verify its checksum sidecar.",
                exit_code=4,
                path=name,
            )
        actual = f"sha256:{sha256_file(target)}"
        if actual != expected.lower():
            raise DeployError(
                "bundle_integrity",
                f"bundle digest mismatch for {name}",
                "Download the bundle again and verify its .sha256 sidecar.",
                exit_code=4,
                path=name,
            )


def _wheel_path(root: Path, version: str) -> Path:
    wheels = sorted((root / "wheelhouse").glob("trovium-*.whl"))
    expected = [wheel for wheel in wheels if f"-{version}-" in wheel.name]
    if len(expected) == 1:
        return expected[0]
    if len(wheels) == 1:
        return wheels[0]
    raise DeployError(
        "bundle_invalid",
        "bundle must contain exactly one trovium wheel",
        "Download the bundle again; the wheelhouse is incomplete.",
        exit_code=4,
        path=str(root / "wheelhouse"),
    )


def _wheel_info(path: Path) -> tuple[str, tuple[str, ...]]:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_name = next(
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            )
            metadata = archive.read(metadata_name).decode("utf-8", "replace")
            entry_name = next(
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/entry_points.txt")
            )
            entry_text = archive.read(entry_name).decode("utf-8", "replace")
    except (OSError, KeyError, StopIteration, zipfile.BadZipFile) as error:
        raise DeployError(
            "bundle_invalid",
            f"cannot read wheel metadata from {path}: {error}",
            "Download the bundle again; the wheel is damaged.",
            exit_code=4,
            path=str(path),
        ) from error
    version = ""
    for line in metadata.splitlines():
        if line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
            break
    if not version:
        raise DeployError(
            "bundle_invalid",
            f"wheel {path} has no Version metadata",
            "Download the bundle again; the wheel is damaged.",
            exit_code=4,
            path=str(path),
        )
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(entry_text)
    except configparser.Error as error:
        raise DeployError(
            "bundle_invalid",
            f"wheel {path} has invalid entry_points.txt: {error}",
            "Download the bundle again; the wheel is damaged.",
            exit_code=4,
            path=str(path),
        ) from error
    commands = tuple(
        sorted(
            name for name, _value in parser.items("console_scripts", raw=True) if name
        )
    )
    if not commands:
        raise DeployError(
            "bundle_invalid",
            f"wheel {path} exports no console scripts",
            "The release bundle is incomplete; download it again.",
            exit_code=4,
            path=str(path),
        )
    return version, commands


def _toolchain_file(root: Path, prefix: str) -> Path | None:
    candidates = sorted((root / "toolchain").glob(f"{prefix}*"))
    files = [candidate for candidate in candidates if candidate.is_file()]
    return files[0] if files else None


def load_bundle(
    bundle_dir: Path,
    *,
    platform: Platform,
    uv_override: Path | None = None,
    python_override: Path | None = None,
) -> BundleInfo:
    """Validate a bundle and return its typed contents."""

    root = bundle_dir.expanduser().resolve()
    if not root.is_dir():
        raise DeployError(
            "bundle_invalid",
            f"bundle directory does not exist: {root}",
            "Pass an extracted bundle directory from the release archive.",
            exit_code=4,
            path=str(root),
        )
    manifest = _parse_manifest(root / "manifest.json")
    try:
        schema = int(manifest["schema_version"])
        version = str(manifest["version"])
        bundle_platform = str(manifest["platform"])
        python_version = str(manifest["python_version"])
        uv_version = str(manifest["uv_version"])
        files = {
            str(name): str(digest) for name, digest in dict(manifest["files"]).items()
        }
    except (KeyError, TypeError, ValueError) as error:
        raise DeployError(
            "bundle_invalid",
            f"bundle manifest is incomplete: {error}",
            "Download the bundle again; the manifest is damaged.",
            exit_code=4,
        ) from error
    if schema != MANIFEST_SCHEMA_VERSION:
        raise DeployError(
            "bundle_invalid",
            f"unsupported bundle manifest schema {schema}",
            "Use a bundle produced by the matching release.",
            exit_code=4,
        )
    if bundle_platform != platform.bundle:
        raise DeployError(
            "bundle_invalid",
            f"bundle platform {bundle_platform} does not match {platform.bundle}",
            "Download the bundle built for this server's platform.",
            exit_code=4,
        )
    try:
        major, minor = (int(part) for part in python_version.split(".")[:2])
    except ValueError as error:
        raise DeployError(
            "bundle_invalid",
            f"invalid bundle Python version: {python_version}",
            "Download the bundle again from the official release.",
            exit_code=4,
        ) from error
    if (major, minor) < (3, 13):
        raise DeployError(
            "bundle_invalid",
            f"bundle Python {python_version} is older than 3.13",
            "Download a bundle built with Python 3.13 or newer.",
            exit_code=4,
        )
    _verify_files(root, files)
    wheel = _wheel_path(root, version)
    wheel_version, commands = _wheel_info(wheel)
    if wheel_version != version:
        raise DeployError(
            "bundle_invalid",
            f"wheel version {wheel_version} does not match manifest {version}",
            "Download the bundle again from the official release.",
            exit_code=4,
            path=str(wheel),
        )
    uv_path = uv_override or _toolchain_file(root, "uv-")
    if uv_override is None and uv_path is None:
        raise DeployError(
            "bundle_invalid",
            "bundle has no uv toolchain",
            "Download a complete release bundle or pass a test uv override.",
            exit_code=4,
        )
    python_tarball = (
        None if python_override is not None else _toolchain_file(root, "python-")
    )
    if python_override is None and (
        python_tarball is None or python_tarball.suffix != ".gz"
    ):
        raise DeployError(
            "bundle_invalid",
            "bundle has no Python toolchain archive",
            "Download a complete release bundle or pass a test Python override.",
            exit_code=4,
        )
    return BundleInfo(
        root=root,
        version=version,
        platform=bundle_platform,
        python_version=python_version,
        uv_version=uv_version,
        wheel=WheelInfo(
            path=wheel,
            version=wheel_version,
            commands=commands,
            sha256=sha256_file(wheel),
        ),
        uv_path=uv_path,
        python_tarball=python_tarball,
        files=files,
    )


def extract_python(archive: Path, destination: Path) -> Path:
    """Safely extract the Python toolchain archive and return its interpreter."""

    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(destination, filter="data")
    except (OSError, tarfile.TarError) as error:
        raise DeployError(
            "bundle_invalid",
            f"cannot extract Python toolchain: {error}",
            "Download the bundle again; the Python archive is damaged.",
            exit_code=4,
            path=str(archive),
        ) from error
    interpreter = destination / "bin" / "python3"
    if not interpreter.exists():
        raise DeployError(
            "bundle_invalid",
            "Python toolchain archive has no bin/python3",
            "Download the bundle again; the Python archive is damaged.",
            exit_code=4,
            path=str(archive),
        )
    interpreter.chmod(interpreter.stat().st_mode | 0o755)
    return interpreter


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "BundleInfo",
    "WheelInfo",
    "extract_python",
    "load_bundle",
    "sha256_file",
]
