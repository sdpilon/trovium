"""A local release fixture that mirrors the GitHub release asset layout."""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@contextmanager
def release_server(
    bundle: Path, version: str, *, serve_asset: bool = True
) -> Iterator[tuple[str, Path]]:
    """Serve ``VERSION`` and the versioned asset; yield (base_url, release_root)."""

    root = Path(tempfile.mkdtemp(prefix="trovium-release-"))
    latest = root / "releases" / "latest" / "download"
    latest.mkdir(parents=True)
    (latest / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    versioned = root / "download" / f"v{version}"
    versioned.mkdir(parents=True)
    if serve_asset:
        shutil.copy2(bundle, versioned / bundle.name)
        shutil.copy2(Path(f"{bundle}.sha256"), versioned / f"{bundle.name}.sha256")
    handler = partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        address = server.server_address
        raw_host = address[0]
        host = raw_host.decode() if isinstance(raw_host, bytes) else str(raw_host)
        yield f"http://{host}:{address[1]}", root
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        shutil.rmtree(root, ignore_errors=True)
