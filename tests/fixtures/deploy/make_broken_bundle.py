#!/usr/bin/env python3
"""Build a bundle whose staged self-check fails.

The output is a copy of a verified bundle with one extra console script
(``trovium-broken``) that exits non-zero, so promotion must be refused and the
previously active version must stay active. The wheel ``RECORD`` and the bundle
manifest are rehashed, so the only defect is the failing self-check.

Usage:
    uv run python tests/fixtures/deploy/make_broken_bundle.py GOOD.tar.gz OUT.tar.gz
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

PROBE = '''"""Injected fixture: a console script that fails its --help self-check."""

from __future__ import annotations

import sys


def main() -> int:
    sys.stderr.write("injected self-check failure\\n")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
'''

ENTRY = "trovium-broken = trovium._deploy_selfcheck_probe:main\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_digest(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
    return f"sha256={encoded.rstrip(b'=').decode()}"


def rewrite_wheel(wheel: Path) -> None:
    """Add the failing console script and rehash the wheel ``RECORD``."""

    with zipfile.ZipFile(wheel) as archive:
        entries = {
            info.filename: archive.read(info.filename) for info in archive.infolist()
        }

    entry_name = next(
        name for name in entries if name.endswith(".dist-info/entry_points.txt")
    )
    entry_text = entries[entry_name].decode("utf-8")
    if not entry_text.endswith("\n"):
        entry_text += "\n"
    entries[entry_name] = (entry_text + ENTRY).encode("utf-8")
    entries["trovium/_deploy_selfcheck_probe.py"] = PROBE.encode("utf-8")

    record_name = next(name for name in entries if name.endswith(".dist-info/RECORD"))
    lines = [
        f"{name},{_record_digest(data)},{len(data)}"
        for name, data in sorted(entries.items())
        if name != record_name
    ]
    lines.append(f"{record_name},,")
    entries[record_name] = ("\n".join(lines) + "\n").encode("utf-8")

    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    source = Path(sys.argv[1]).resolve()
    destination = Path(sys.argv[2]).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="trovium-broken-") as raw:
        work = Path(raw)
        with tarfile.open(source) as tar:
            tar.extractall(work, filter="fully_trusted")
        roots = [path for path in work.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise SystemExit(f"expected one bundle directory, found {len(roots)}")
        bundle = roots[0]
        wheels = sorted((bundle / "wheelhouse").glob("trovium-*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"expected one trovium wheel, found {len(wheels)}")
        rewrite_wheel(wheels[0])

        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        relative = wheels[0].relative_to(bundle).as_posix()
        manifest["files"][relative] = f"sha256:{_sha256(wheels[0])}"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")

        with tarfile.open(destination, "w:gz") as tar:
            tar.add(bundle, arcname=bundle.name)

    digest = _sha256(destination)
    Path(f"{destination}.sha256").write_text(
        f"{digest}  {destination.name}\n", encoding="utf-8"
    )
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
