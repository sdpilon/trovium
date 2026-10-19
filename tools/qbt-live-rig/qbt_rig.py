#!/usr/bin/env python3
"""qbt_rig — a reusable, root-free qBittorrent test rig.

Two local qBittorrent instances plus a minimal HTTP tracker, so any client can
be exercised against a *real* BitTorrent download over loopback: instance B
seeds, instance A downloads, the tracker announces them to each other.

Typical flow:

    ./setup.sh                                   # one-time: fetch the client
    ./qbt_rig.py up
    ./qbt_rig.py fixture movie --title Movie.Production.2024.1080p-iGor.mkv --size-mb 3
    ./qbt_rig.py seed movie                      # add + place + recheck on B
    ./qbt_rig.py fetch movie                     # add + download + verify on A
    eval "$(./qbt_rig.py env)"
    trovium-ingest --library-root "$QBT_RIG_LIBRARY"
    ./qbt_rig.py status
    ./qbt_rig.py down

Everything lives under the rig directory (or $QBT_RIG_WORK); nothing is
installed system-wide and no root is needed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.cookiejar
import json
import os
import random
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

RIG = Path(os.environ.get("QBT_RIG", Path(__file__).resolve().parent))
WORK = Path(os.environ.get("QBT_RIG_WORK", RIG / "work"))
CLIENT = Path(os.environ.get("QBT_RIG_CLIENT", RIG / "client"))
PASSWORD = os.environ.get("QBT_RIG_PASSWORD", "rig-test-pw")
PIECE = 256 * 1024


def _port(env: str, default: int) -> int:
    return int(os.environ.get(env, default))


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


INSTANCES: dict[str, dict[str, int]] = {
    "a": {
        "webui": _port("QBT_RIG_A_WEBUI", 8080),
        "torrent": _port("QBT_RIG_A_TORRENT", 46052),
        "ssl": _port("QBT_RIG_A_SSL", 22150),
    },
    "b": {
        "webui": _port("QBT_RIG_B_WEBUI", 8081),
        "torrent": _port("QBT_RIG_B_TORRENT", 6882),
        "ssl": _port("QBT_RIG_B_SSL", 6883),
    },
}
TRACKER_PORT = _port("QBT_RIG_TRACKER_PORT", 6969)
TRACKER_URL = f"http://127.0.0.1:{TRACKER_PORT}/announce"


# --------------------------------------------------------------------------
# bencode (torrents + tracker responses)
# --------------------------------------------------------------------------


def bencode(obj: object) -> bytes:
    if isinstance(obj, bool):
        raise TypeError("no bools in torrents")
    if isinstance(obj, int):
        return b"i%de" % obj
    if isinstance(obj, str):
        return bencode(obj.encode())
    if isinstance(obj, bytes):
        return b"%d:%s" % (len(obj), obj)
    if isinstance(obj, list):
        return b"l" + b"".join(bencode(item) for item in obj) + b"e"
    if isinstance(obj, dict):
        out = b"d"
        for key in sorted(obj):
            out += bencode(key) + bencode(obj[key])
        return out + b"e"
    raise TypeError(type(obj))


def pieces_for(data: bytes) -> bytes:
    return b"".join(
        hashlib.sha1(data[k : k + PIECE]).digest() for k in range(0, len(data), PIECE)
    )


# --------------------------------------------------------------------------
# instance paths + config
# --------------------------------------------------------------------------


def instance_dir(name: str) -> Path:
    return WORK / name


def downloads(name: str) -> Path:
    return instance_dir(name) / "downloads"


def profile(name: str) -> Path:
    return instance_dir(name) / "profile"


def config_path(name: str) -> Path:
    return profile(name) / "qBittorrent" / "config" / "qBittorrent.conf"


def _pbkdf2(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100_000, dklen=64)
    return f"{base64.b64encode(salt).decode()}:{base64.b64encode(digest).decode()}"


def write_config(name: str) -> None:
    """Write a deterministic test profile (5.x config path; 4.x path is ignored)."""
    ports = INSTANCES[name]
    path = config_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""[LegalNotice]
Accepted=true

[BitTorrent]
Session\\DefaultSavePath={downloads(name)}
Session\\Port={ports["torrent"]}
Session\\SSL\\Port={ports["ssl"]}
Session\\DHTEnabled=false
Session\\LSDEnabled=false
Session\\UPnPEnabled=false
Session\\QueueingSystemEnabled=false

[Preferences]
WebUI\\Enabled=true
WebUI\\Address=127.0.0.1
WebUI\\Port={ports["webui"]}
WebUI\\Username=admin
WebUI\\LocalHostAuth=true
WebUI\\MaxAuthenticationFailCount=100
WebUI\\BanDuration=5
WebUI\\Password_PBKDF2="@ByteArray({_pbkdf2(PASSWORD)})"
"""
    )
    downloads(name).mkdir(parents=True, exist_ok=True)


def client_env() -> dict[str, str]:
    """Environment with the extracted client's libs, on any APT multiarch."""
    candidates = sorted((CLIENT / "usr/lib").glob("*-linux-gnu"))
    lib = candidates[0] if candidates else CLIENT / "usr/lib/x86_64-linux-gnu"
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = f"{lib}:{lib / 'libproxy'}"
    env["QT_PLUGIN_PATH"] = str(lib / "qt6/plugins")
    return env


# --------------------------------------------------------------------------
# qBittorrent WebUI API
# --------------------------------------------------------------------------


def _multipart(
    files: dict[str, tuple[str, bytes]], fields: dict[str, str]
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    for key, (filename, content) in files.items():
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; '
                f'filename="{filename}"\r\n'
                "Content-Type: application/x-bittorrent\r\n\r\n"
            ).encode()
            + content
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class Qbt:
    def __init__(self, name: str, *, attempts: int = 40) -> None:
        self.name = name
        self.base = f"http://127.0.0.1:{INSTANCES[name]['webui']}"
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        last: Exception | None = None
        for _ in range(attempts):
            try:
                self._login()
                return
            except Exception as error:
                last = error
                time.sleep(0.5)
        raise RuntimeError(f"instance {name} did not come up: {last}")

    def _login(self) -> None:
        body = urllib.parse.urlencode(
            {"username": "admin", "password": PASSWORD}
        ).encode()
        request = urllib.request.Request(f"{self.base}/api/v2/auth/login", data=body)
        with self.opener.open(request, timeout=5) as response:
            text = response.read().decode().strip()
        if text != "Ok.":
            raise RuntimeError(f"login rejected: {text!r}")

    def api(
        self,
        path: str,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes]] | None = None,
    ) -> bytes:
        if files is not None:
            body, content_type = _multipart(files, data or {})
            request = urllib.request.Request(
                f"{self.base}{path}", data=body, headers={"Content-Type": content_type}
            )
        elif data is not None:
            request = urllib.request.Request(
                f"{self.base}{path}", data=urllib.parse.urlencode(data).encode()
            )
        else:
            request = urllib.request.Request(f"{self.base}{path}")
        with self.opener.open(request, timeout=120) as response:
            return bytes(response.read())

    def json(self, path: str, **kwargs: object) -> object:
        raw = self.api(path, **kwargs)  # type: ignore[arg-type]
        return json.loads(raw) if raw else None

    def torrents(self) -> list[dict[str, object]]:
        result = self.json("/api/v2/torrents/info")
        assert isinstance(result, list)
        return result

    def torrent(self, info_hash: str) -> dict[str, object] | None:
        result = self.json(f"/api/v2/torrents/info?hashes={info_hash}")
        assert isinstance(result, list)
        return result[0] if result else None

    def transfer(self) -> dict[str, object]:
        result = self.json("/api/v2/transfer/info")
        assert isinstance(result, dict)
        return result

    def add(
        self,
        torrent: Path,
        savepath: Path,
        category: str = "test",
        *,
        stopped: bool = True,
    ) -> None:
        flag = "true" if stopped else "false"
        self.api(
            "/api/v2/torrents/add",
            data={
                "savepath": str(savepath),
                "stopped": flag,  # 5.x name
                "paused": flag,  # 4.x name
                "autoTMM": "false",
                "category": category,
            },
            files={"torrents": (torrent.name, torrent.read_bytes())},
        )

    def start(self, info_hash: str | None = None) -> None:
        hashes = info_hash or "all"
        try:
            self.api("/api/v2/torrents/start", data={"hashes": hashes})
        except urllib.error.HTTPError:
            # 4.x name; 5.x renamed resume -> start
            self.api("/api/v2/torrents/resume", data={"hashes": hashes})

    def pause(self, info_hash: str) -> None:
        # /pause is 404 on qBittorrent >= 5; /stop is the current endpoint.
        try:
            self.api("/api/v2/torrents/stop", data={"hashes": info_hash})
        except urllib.error.HTTPError:
            self.api("/api/v2/torrents/pause", data={"hashes": info_hash})

    def recheck(self, info_hash: str | None = None) -> None:
        self.api("/api/v2/torrents/recheck", data={"hashes": info_hash or "all"})

    def delete(self, info_hash: str | None = None, *, files: bool = False) -> None:
        self.api(
            "/api/v2/torrents/delete",
            data={
                "hashes": info_hash or "all",
                "deleteFiles": "true" if files else "false",
            },
        )

    def wait_registered(
        self, info_hash: str, timeout: float = 15.0
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        last: dict[str, object] | None = None
        while time.monotonic() < deadline:
            last = self.torrent(info_hash)
            if last is not None:
                return last
            time.sleep(0.2)
        raise RuntimeError(f"torrent {info_hash[:8]} did not register: {last}")

    def wait_checked(self, info_hash: str, timeout: float = 30.0) -> dict[str, object]:
        """Wait for a recheck to finish before touching the stopped/running state."""
        deadline = time.monotonic() + timeout
        last: dict[str, object] | None = None
        while time.monotonic() < deadline:
            last = self.torrent(info_hash)
            if last is not None and not str(last["state"]).startswith("checking"):
                return last
            time.sleep(0.3)
        raise RuntimeError(f"recheck did not finish for {info_hash[:8]}: {last}")

    def start_verified(
        self, info_hash: str, timeout: float = 20.0
    ) -> dict[str, object]:
        """Start and confirm the torrent is actually running (not queued/checking)."""
        inactive = {
            "stoppedDL",
            "stoppedUP",
            "pausedDL",
            "pausedUP",
            "checkingUP",
            "checkingDL",
            "queuedUP",
            "queuedDL",
            "allocating",
            "metaDL",
            "moving",
        }
        deadline = time.monotonic() + timeout
        last: dict[str, object] | None = None
        while time.monotonic() < deadline:
            self.start(info_hash)
            time.sleep(0.3)
            last = self.torrent(info_hash)
            if last is not None and str(last["state"]) not in inactive:
                return last
        raise RuntimeError(f"could not start {info_hash[:8]}: {last}")

    def wait_complete(self, info_hash: str, timeout: float = 90.0) -> dict[str, object]:
        transient = {
            "checkingUP",
            "checkingDL",
            "queuedUP",
            "queuedDL",
            "allocating",
            "metaDL",
            "downloading",
        }
        deadline = time.monotonic() + timeout
        last: dict[str, object] | None = None
        while time.monotonic() < deadline:
            last = self.torrent(info_hash)
            if last is None:
                time.sleep(0.5)
                continue
            progress = last.get("progress")
            if (
                isinstance(progress, (int, float))
                and progress >= 1.0
                and str(last["state"]) not in transient
            ):
                return last
            time.sleep(0.5)
        raise RuntimeError(
            f"torrent {info_hash[:8]} not complete after {timeout}s: {last}"
        )


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _tracker_ready(timeout: float = 10.0) -> bool:
    probe = (
        f"http://127.0.0.1:{TRACKER_PORT}/announce"
        "?info_hash=00000000000000000000&peer_id=-rig-probe-000000000&port=1&compact=1"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(probe, timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return None


def cmd_up(args: argparse.Namespace) -> int:
    binary = CLIENT / "usr/bin/qbittorrent-nox"
    if not binary.exists():
        print(f"client missing: run {RIG / 'setup.sh'} first", file=sys.stderr)
        return 1
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "evidence").mkdir(exist_ok=True)
    (WORK / "library").mkdir(exist_ok=True)

    tracker_pid = WORK / "tracker.pid"
    tracker_handle = _read_pid(tracker_pid)
    if tracker_handle is not None and _alive_rig(tracker_handle, "tracker.py"):
        print(f"tracker already running (pid {tracker_pid.read_text().strip()})")
    else:
        if not _port_free(TRACKER_PORT):
            print(
                f"port {TRACKER_PORT} is already in use (another tracker? set "
                "QBT_RIG_TRACKER_PORT)",
                file=sys.stderr,
            )
            return 1
        log_path = WORK / "tracker.log"
        log = log_path.open("w")
        process = subprocess.Popen(
            [sys.executable, str(RIG / "tracker.py")],
            env={**os.environ, "QBT_RIG_WORK": str(WORK)},
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        tracker_pid.write_text(str(process.pid))
        if not _tracker_ready():
            print(f"tracker failed to start; see {log_path}", file=sys.stderr)
            print(log_path.read_text()[-500:], file=sys.stderr)
            return 1
        print(f"tracker started (pid {process.pid}) on :{TRACKER_PORT}")

    for name in ("a", "b"):
        pid_file = instance_dir(name) / "client.pid"
        running_pid = _read_pid(pid_file)
        if running_pid is not None and _alive_rig(running_pid, "qbittorrent"):
            print(
                f"instance {name} already running (pid {pid_file.read_text().strip()})"
            )
            continue
        if not _port_free(INSTANCES[name]["webui"]):
            print(
                f"WebUI port {INSTANCES[name]['webui']} for instance {name} is already "
                "in use (set QBT_RIG_%s_WEBUI)" % name.upper(),
                file=sys.stderr,
            )
            return 1
        write_config(name)
        log = (instance_dir(name) / "client.log").open("w")
        process = subprocess.Popen(
            [str(binary), f"--profile={profile(name)}"],
            env=client_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        pid_file.write_text(str(process.pid))
        Qbt(name)  # readiness: retries login until the WebUI answers
        print(
            f"instance {name} up: webui :{INSTANCES[name]['webui']} "
            f"torrent :{INSTANCES[name]['torrent']} (pid {process.pid})"
        )
    return 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cmdline(pid: int) -> str:
    """Best-effort process command line; empty when it cannot be determined."""
    try:
        raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
        return raw.replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip()


def _alive_rig(pid: int, marker: str) -> bool:
    """True when the pid is alive and plausibly the process we started."""
    if not _alive(pid):
        return False
    cmdline = _cmdline(pid)
    return not cmdline or marker in cmdline


def cmd_down(args: argparse.Namespace) -> int:
    targets = [
        (WORK / "tracker.pid", "tracker", "tracker.py"),
        (instance_dir("a") / "client.pid", "instance a", "qbittorrent"),
        (instance_dir("b") / "client.pid", "instance b", "qbittorrent"),
    ]
    failures = 0
    for pid_file, label, marker in targets:
        if not pid_file.exists():
            continue
        try:
            pid = int(pid_file.read_text())
        except ValueError:
            pid_file.unlink(missing_ok=True)
            print(f"{label}: unreadable pid file removed", file=sys.stderr)
            continue
        if not _alive(pid):
            pid_file.unlink(missing_ok=True)
            print(f"{label}: not running (stale pid file removed)")
            continue
        if not _alive_rig(pid, marker):
            pid_file.unlink(missing_ok=True)
            print(
                f"{label}: pid {pid} is not a {marker} process; left it alone and "
                "removed the stale pid file",
                file=sys.stderr,
            )
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pid_file.unlink(missing_ok=True)
            print(f"{label}: exited before the signal was sent")
            continue
        for _ in range(20):
            if not _alive(pid):
                break
            time.sleep(0.25)
        if _alive(pid):
            failures += 1
            print(
                f"{label}: still running after 5s (pid {pid}); pid file kept",
                file=sys.stderr,
            )
        else:
            pid_file.unlink(missing_ok=True)
            print(f"{label}: stopped (pid {pid})")
    return 1 if failures else 0


def cmd_fixture(args: argparse.Namespace) -> int:
    case = args.name
    seed = (
        args.seed
        if args.seed is not None
        else int(hashlib.sha256(case.encode()).hexdigest()[:8], 16)
    )
    rng = random.Random(seed)
    out = WORK / "fixtures"
    out.mkdir(parents=True, exist_ok=True)

    entries: list[tuple[str, bytes]] = []
    if args.root is None and args.files <= 1:
        layout = "single"
        name = args.title or f"{case}.mkv"
        entries = [(name, bytes(rng.randbytes(args.size_mb * 1024 * 1024)))]
        info: dict[str, object] = {
            "name": name,
            "length": len(entries[0][1]),
            "piece length": PIECE,
            "pieces": pieces_for(entries[0][1]),
        }
    else:
        # --root always means a multi-file torrent, even with a single media
        # file: qBittorrent then reports a directory content_path, which is the
        # shape client-mode move has to cope with.
        layout = "multi"
        root = args.root or case
        count = max(1, args.files)
        if count == 1:
            names = [f"{root}.mkv"]
        else:
            names = [f"{root}E{index:02d}.mkv" for index in range(1, count + 1)]
        entries = [
            (name, bytes(rng.randbytes(args.size_mb * 1024 * 1024))) for name in names
        ]
        concat = b"".join(data for _, data in entries)
        info = {
            "name": root,
            "piece length": PIECE,
            "pieces": pieces_for(concat),
            "files": [{"length": len(data), "path": [name]} for name, data in entries],
        }

    torrent = {
        "announce": args.tracker,
        "created by": "qbt_rig fixture",
        "info": info,
    }
    blob = bencode(torrent)
    torrent_path = out / f"{case}.torrent"
    torrent_path.write_bytes(blob)
    info_hash = hashlib.sha1(bencode(info)).hexdigest()

    payload_dir = out / case
    file_records = []
    for name, data in entries:
        rel = name if layout == "single" else f"{info['name']}/{name}"
        target = payload_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        file_records.append(
            {
                "rel": rel,
                "path": str(target),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    manifest = {
        "case": case,
        "layout": layout,
        "torrent_name": info["name"],
        "torrent": str(torrent_path),
        "info_hash": info_hash,
        "files": file_records,
        "tracker": args.tracker,
    }
    manifest_path = out / f"{case}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


class FixtureFile(TypedDict):
    rel: str
    path: str
    bytes: int
    sha256: str


class Fixture(TypedDict):
    case: str
    layout: str
    torrent_name: str
    torrent: str
    info_hash: str
    files: list[FixtureFile]
    tracker: str


def _manifest(case: str) -> Fixture:
    path = WORK / "fixtures" / f"{case}.json"
    if not path.exists():
        raise SystemExit(
            f"no such fixture: {case} (run: qbt_rig.py fixture {case} ...)"
        )
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"invalid fixture manifest: {path}")
    return cast(Fixture, data)


def _place(case: str, target_root: Path) -> None:
    manifest = _manifest(case)
    for record in manifest["files"]:
        target = target_root / record["rel"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record["path"], target)


def _verify(case: str, target_root: Path) -> bool:
    manifest = _manifest(case)
    ok = True
    for record in manifest["files"]:
        target = target_root / record["rel"]
        digest = (
            hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ""
        )
        match = digest == record["sha256"]
        ok &= match
        print(f"  {'MATCH' if match else 'MISMATCH'} {record['rel']}")
    return ok


def cmd_seed(args: argparse.Namespace) -> int:
    manifest = _manifest(args.name)
    client = Qbt("b")
    client.add(Path(manifest["torrent"]), downloads("b"))
    client.wait_registered(str(manifest["info_hash"]))
    _place(args.name, downloads("b"))
    client.recheck(str(manifest["info_hash"]))
    client.wait_checked(str(manifest["info_hash"]))
    client.start_verified(str(manifest["info_hash"]))
    state = client.wait_complete(str(manifest["info_hash"]))
    print(
        f"seeded {args.name} on b: info_hash={manifest['info_hash']} "
        f"state={state['state']} progress={state['progress']}"
    )
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    manifest = _manifest(args.name)
    client = Qbt("a")
    client.add(Path(manifest["torrent"]), downloads("a"), stopped=False)
    client.wait_registered(str(manifest["info_hash"]))
    state = client.wait_complete(str(manifest["info_hash"]))
    downloaded = state.get("downloaded")
    if not isinstance(downloaded, (int, float)) or downloaded <= 0:
        print(
            f"{args.name}: no peer data was downloaded (the torrent completed from "
            "existing files); run reset and fetch again to prove a transfer",
            file=sys.stderr,
        )
        return 1
    print(
        f"downloaded {args.name} on a: state={state['state']} "
        f"progress={state['progress']} bytes={downloaded} "
        f"save_path={state['save_path']}"
    )
    if not _verify(args.name, downloads("a")):
        print("payload mismatch after transfer", file=sys.stderr)
        return 1
    return 0


def _as_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"expected a number, got {type(value).__name__}")


def cmd_status(args: argparse.Namespace) -> int:
    for name in ("a", "b"):
        try:
            client = Qbt(name, attempts=2)
        except RuntimeError as error:
            print(f"{name}: {error}")
            continue
        transfer = client.transfer()
        print(
            f"[{name}] http://127.0.0.1:{INSTANCES[name]['webui']} "
            f"downloaded={transfer['dl_info_data']} uploaded={transfer['up_info_data']}"
        )
        for torrent in client.torrents():
            print(
                f"  {str(torrent['hash'])[:8]} {torrent['state']!s:<12} "
                f"progress={_as_float(torrent['progress']):.2f} "
                f"save={torrent['save_path']} name={torrent['name']!r}"
            )
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    evidence = WORK / "evidence" / f"{args.label}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    instances: dict[str, object] = {}
    payload: dict[str, object] = {
        "taken_at": datetime.now(UTC).isoformat(),
        "instances": instances,
    }
    for name in ("a", "b"):
        try:
            client = Qbt(name, attempts=2)
        except RuntimeError:
            continue
        instances[name] = {
            "transfer": client.transfer(),
            "torrents": client.torrents(),
        }
    evidence.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {evidence}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    for name in ("a", "b"):
        try:
            client = Qbt(name, attempts=2)
        except RuntimeError:
            continue
        client.delete()
        shutil.rmtree(downloads(name), ignore_errors=True)
        downloads(name).mkdir(parents=True, exist_ok=True)
        print(f"reset instance {name}: torrents removed, downloads cleared")
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    port = INSTANCES[args.instance]["webui"]
    exports = {
        "TROVIUM_CLIENT_URL": f"http://127.0.0.1:{port}",
        "TROVIUM_CLIENT_USERNAME": "admin",
        "TROVIUM_CLIENT_PASSWORD": PASSWORD,
        "QBT_RIG_LIBRARY": str(WORK / "library"),
        "QBT_RIG_FIXTURES": str(WORK / "fixtures"),
    }
    for key, value in exports.items():
        print(f"export {key}={shlex.quote(value)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("up", help="start the tracker and both instances")
    sub.add_parser("down", help="stop everything")
    sub.add_parser("status", help="show both instances")
    sub.add_parser("reset", help="remove all torrents + downloads (library untouched)")

    fixture = sub.add_parser("fixture", help="build payload + .torrent")
    fixture.add_argument("name", help="case name (manifest id)")
    fixture.add_argument("--title", help="single-file torrent name / file name")
    fixture.add_argument("--root", help="multi-file torrent root folder")
    fixture.add_argument(
        "--files", type=_positive_int, default=1, help="number of media files"
    )
    fixture.add_argument(
        "--size-mb", type=_positive_int, default=2, help="size per file (>= 1)"
    )
    fixture.add_argument("--seed", type=int, help="deterministic payload seed")
    fixture.add_argument("--tracker", default=TRACKER_URL)

    seed = sub.add_parser("seed", help="add + place + recheck + start on B")
    seed.add_argument("name")

    fetch = sub.add_parser("fetch", help="add + download + verify on A")
    fetch.add_argument("name")

    snapshot = sub.add_parser("snapshot", help="write instance state to evidence/")
    snapshot.add_argument("label")

    env = sub.add_parser("env", help="print shell exports for a CLI")
    env.add_argument("--instance", choices=("a", "b"), default="a")

    args = parser.parse_args(argv)
    handlers = {
        "up": cmd_up,
        "down": cmd_down,
        "status": cmd_status,
        "reset": cmd_reset,
        "fixture": cmd_fixture,
        "seed": cmd_seed,
        "fetch": cmd_fetch,
        "snapshot": cmd_snapshot,
        "env": cmd_env,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
