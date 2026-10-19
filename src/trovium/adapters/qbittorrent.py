"""The single qBittorrent adapter (constitutions XVIII, XXVII).

Every client interaction goes through this module; no other module knows the
qBittorrent API. Malformed or unparseable responses fail closed with a named
cause (constitution VI).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from trovium.sources import ClientState, CompletionState

_REQUIRED_KEYS = ("hash", "name", "progress", "state", "save_path")
_COMPLETE_STATES = frozenset(
    {"uploading", "stalledUP", "forcedUP", "pausedUP", "queuedUP", "checkingUP"}
)


class AdapterError(RuntimeError):
    """A named client failure: unreachable, unauthenticated, or unparseable."""


@dataclass(frozen=True)
class ClientEntry:
    """One torrent as reported by the client, in adapter-neutral terms."""

    hash: str
    name: str
    content_path: Path
    root_path: Path
    completion: CompletionState
    client_state: ClientState
    category: str | None


class QbittorrentClient:
    """Minimal qBittorrent WebUI API v2 client."""

    def __init__(
        self,
        base_url: str,
        username: str | None,
        password: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._client = httpx.Client(
            base_url=self._base_url,
            transport=transport,
            timeout=timeout,
        )

    def __enter__(self) -> QbittorrentClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._client.close()

    def _request(
        self, method: str, url: str, data: dict[str, str] | None = None
    ) -> httpx.Response:
        try:
            return self._client.request(method, url, data=data)
        except httpx.HTTPError as error:
            raise AdapterError(
                f"client unreachable at {self._base_url}: {error}"
            ) from error

    def login(self) -> None:
        """Authenticate; raises AdapterError on failure (FR-008)."""
        if self._username is None or self._password is None:
            raise AdapterError(
                "client credentials missing: set TROVIUM_CLIENT_USERNAME and "
                "TROVIUM_CLIENT_PASSWORD"
            )
        response = self._request(
            "POST",
            "/api/v2/auth/login",
            data={"username": self._username, "password": self._password},
        )
        if response.status_code != httpx.codes.OK or response.text.strip() != "Ok.":
            raise AdapterError("client authentication failed: invalid credentials")

    def entries(self) -> tuple[ClientEntry, ...]:
        """All torrents as adapter-neutral entries; fails closed on malformed data."""
        response = self._request("GET", "/api/v2/torrents/info")
        if response.status_code != httpx.codes.OK:
            raise AdapterError(
                f"client returned HTTP {response.status_code} for torrents/info"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise AdapterError(
                f"malformed client response: not JSON: {error}"
            ) from error
        if not isinstance(payload, list):
            raise AdapterError("malformed client response: torrents/info is not a list")

        entries: list[ClientEntry] = []
        for raw in payload:
            entries.append(self._entry(raw))
        return tuple(entries)

    def _entry(self, raw: object) -> ClientEntry:
        if not isinstance(raw, dict):
            raise AdapterError(
                "malformed client response: torrent entry is not an object"
            )
        for key in _REQUIRED_KEYS:
            if key not in raw:
                raise AdapterError(
                    f"malformed client response: torrent missing '{key}'"
                )
        torrent_hash = raw["hash"]
        name = raw["name"]
        progress = raw["progress"]
        state = raw["state"]
        save_path = raw["save_path"]
        if not isinstance(torrent_hash, str) or not torrent_hash:
            raise AdapterError("malformed client response: torrent 'hash' is empty")
        if not isinstance(name, str) or not name:
            raise AdapterError("malformed client response: torrent 'name' is empty")
        if not isinstance(progress, (int, float)) or isinstance(progress, bool):
            raise AdapterError(
                "malformed client response: torrent 'progress' is not a number"
            )
        if not isinstance(state, str):
            raise AdapterError(
                "malformed client response: torrent 'state' is not a string"
            )
        if not isinstance(save_path, str) or not save_path:
            raise AdapterError(
                "malformed client response: torrent 'save_path' is empty"
            )
        content_path = raw.get("content_path")
        resolved = (
            Path(content_path)
            if isinstance(content_path, str) and content_path
            else Path(save_path) / name
        )
        root_path = raw.get("root_path")
        resolved_root = (
            Path(root_path) if isinstance(root_path, str) and root_path else resolved
        )
        complete = float(progress) >= 1.0 or state in _COMPLETE_STATES
        category = raw.get("category")
        return ClientEntry(
            hash=torrent_hash,
            name=name,
            content_path=resolved,
            root_path=resolved_root,
            completion=CompletionState.COMPLETE
            if complete
            else CompletionState.INCOMPLETE,
            client_state=ClientState.SEEDING if complete else ClientState.NONE,
            category=category if isinstance(category, str) else None,
        )

    def set_location(self, torrent_hash: str, location: Path) -> None:
        """Point this torrent at the new location after a move placement (FR-010)."""
        self._post(
            "/api/v2/torrents/setLocation",
            {"hashes": torrent_hash, "location": str(location)},
        )

    def pause(self, torrent_hash: str) -> None:
        """Pause exactly this torrent (``--post-ingest pause``).

        qBittorrent 5.x renamed the endpoint: ``/torrents/stop`` exists and
        ``/torrents/pause`` answers 404. 4.x is the reverse. Try ``stop`` first
        and fall back to ``pause`` on 404 so both are supported.
        """
        for endpoint in ("/api/v2/torrents/stop", "/api/v2/torrents/pause"):
            response = self._request("POST", endpoint, data={"hashes": torrent_hash})
            if response.status_code == httpx.codes.OK:
                return
            if response.status_code != httpx.codes.NOT_FOUND:
                raise AdapterError(
                    f"client returned HTTP {response.status_code} for {endpoint}"
                )
        raise AdapterError(
            "client does not support pausing torrents (tried /torrents/stop "
            "and /torrents/pause)"
        )

    def delete(self, torrent_hash: str) -> None:
        """Delete exactly this torrent; files are left in place."""
        self._post(
            "/api/v2/torrents/delete",
            {"hashes": torrent_hash, "deleteFiles": "false"},
        )

    def recheck(self, torrent_hash: str) -> None:
        """Ask the client to re-verify this torrent's files."""
        self._post("/api/v2/torrents/recheck", {"hashes": torrent_hash})

    def wait_until_complete(
        self, torrent_hash: str, *, timeout: float = 30.0, interval: float = 0.5
    ) -> None:
        """Poll until the torrent reports complete, or fail with a named cause.

        A paused torrent whose files were just relocated can report progress 0
        until it rechecks; waiting keeps the paused state coherent instead of
        returning a record that says ingested while the client shows 0%.
        """
        deadline = time.monotonic() + timeout
        while True:
            match = next(
                (entry for entry in self.entries() if entry.hash == torrent_hash),
                None,
            )
            if match is None:
                raise AdapterError(
                    f"client no longer reports torrent {torrent_hash} after recheck"
                )
            if match.completion is CompletionState.COMPLETE:
                return
            if time.monotonic() >= deadline:
                raise AdapterError(
                    f"torrent {torrent_hash} did not return to 100% within "
                    f"{timeout:.0f}s after recheck"
                )
            time.sleep(interval)

    def _post(self, url: str, data: dict[str, str]) -> None:
        response = self._request("POST", url, data=data)
        if response.status_code != httpx.codes.OK:
            raise AdapterError(f"client returned HTTP {response.status_code} for {url}")
