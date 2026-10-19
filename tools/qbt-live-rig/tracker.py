#!/usr/bin/env python3
"""Minimal BitTorrent HTTP tracker for qbt_rig (localhost only).

Both instances announce to 127.0.0.1:$QBT_RIG_TRACKER_PORT (default 6969); the
tracker returns the other peers for the same info hash. Every announce is
appended to work/tracker.announces.jsonl as evidence.
"""

from __future__ import annotations

import ipaddress
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qbt_rig import TRACKER_PORT, WORK, bencode

LOG = Path(os.environ.get("QBT_RIG_WORK", WORK)) / "tracker.announces.jsonl"
peers: dict[bytes, dict[bytes, tuple[str, int]]] = {}
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if parts.path != "/announce":
            self.send_error(404)
            return

        query: dict[bytes, bytes] = {}
        for item in parts.query.split("&"):
            if "=" in item:
                key, value = item.split("=", 1)
                query[key.encode()] = unquote_to_bytes(value)

        info_hash = query.get(b"info_hash", b"")
        peer_id = query.get(b"peer_id", b"")
        try:
            port = int(query.get(b"port", b"0"))
        except ValueError:
            port = 0
        event = query.get(b"event", b"started").decode(errors="replace")
        ip = self.client_address[0]

        with lock:
            table = peers.setdefault(info_hash, {})
            if event == "stopped":
                table.pop(peer_id, None)
            elif port:
                table[peer_id] = (ip, port)
            others = sorted(
                (addr, prt)
                for pid, (addr, prt) in table.items()
                if pid != peer_id and prt
            )
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a") as handle:
                handle.write(
                    json.dumps(
                        {
                            "t": round(time.time(), 3),
                            "hash": info_hash.hex(),
                            "peer_id": peer_id.hex(),
                            "ip": ip,
                            "port": port,
                            "event": event,
                            "peers_returned": [f"{a}:{p}" for a, p in others],
                        }
                    )
                    + "\n"
                )

        if query.get(b"compact") == b"0":
            peer_payload: object = [
                {"ip": addr, "port": prt, "peer id": pid}
                for pid, (addr, prt) in peers.get(info_hash, {}).items()
                if pid != peer_id
            ]
        else:
            peer_payload = b"".join(
                ipaddress.IPv4Address(addr).packed + prt.to_bytes(2, "big")
                for addr, prt in others
            )

        body = bencode(
            {
                "interval": 30,
                "min interval": 10,
                "complete": len(others),
                "incomplete": 0,
                "peers": peer_payload,
            }
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


if __name__ == "__main__":
    print(f"tracker on 127.0.0.1:{TRACKER_PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", TRACKER_PORT), Handler).serve_forever()
