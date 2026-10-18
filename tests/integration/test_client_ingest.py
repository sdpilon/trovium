"""Integration/contract tests: client mode and fail-closed adapter behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from trovium import cli
from trovium.adapters.qbittorrent import AdapterError, QbittorrentClient

BASE_URL = "http://client.invalid"


def _torrent(
    name: str,
    content_path: Path,
    *,
    progress: float = 1.0,
    state: str = "uploading",
    category: str = "movies",
) -> dict[str, Any]:
    return {
        "name": name,
        "progress": progress,
        "state": state,
        "save_path": str(content_path.parent),
        "content_path": str(content_path),
        "category": category,
    }


def _transport(
    torrents: list[dict[str, Any]], *, login_ok: bool = True, malformed: bool = False
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok." if login_ok else "Fails.")
        if request.url.path == "/api/v2/torrents/info":
            if malformed:
                return httpx.Response(200, text="not json at all")
            return httpx.Response(200, json=torrents)
        return httpx.Response(200, text="Ok.")

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.CLIENT_URL_ENV, BASE_URL)
    monkeypatch.setenv(cli.CLIENT_USERNAME_ENV, "admin")
    monkeypatch.setenv(cli.CLIENT_PASSWORD_ENV, "secret")


def _run(library: Path, *extra: str) -> tuple[int, dict[str, Any], str]:
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--library-root", str(library), *extra])
    payload = json.loads(out.getvalue()) if out.getvalue() else {}
    return code, payload, err.getvalue()


def test_completed_torrent_is_ingested_and_client_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    content = tmp_path / "downloads" / "Movie.Production.2024.1080p-iGor"
    content.mkdir(parents=True)
    (content / "Movie.Production.2024.1080p-iGor.mkv").write_bytes(b"movie-bytes")
    library = tmp_path / "library"
    library.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200, json=[_torrent("Movie.Production.2024.1080p-iGor", content)]
            )
        return httpx.Response(200, text="Ok.")

    import trovium.cli as cli_module

    original = cli_module.QbittorrentClient

    def factory(
        url: str, username: str | None, password: str | None
    ) -> QbittorrentClient:
        return original(url, username, password, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(cli_module, "QbittorrentClient", factory)

    code, record, _ = _run(library)

    assert code == 0
    assert record["source"] == "client"
    item = record["items"][0]
    assert item["disposition"] == "ingested"
    assert (Path(item["destination"]) / "Movie.Production.2024.1080p-iGor.mkv").exists()
    # FR-010: the client is updated only after placement succeeded
    assert calls.index("/api/v2/torrents/setLocation") > calls.index(
        "/api/v2/torrents/info"
    )


def test_incomplete_torrent_is_skipped_without_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = tmp_path / "downloads" / "Show.Name.S01E01.1080p"
    content.mkdir(parents=True)
    (content / "Show.Name.S01E01.1080p.mkv").write_bytes(b"partial")
    library = tmp_path / "library"
    library.mkdir()

    transport = _transport(
        [
            _torrent(
                "Show.Name.S01E01.1080p", content, progress=0.42, state="downloading"
            )
        ]
    )
    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=transport
        ),
    )

    code, record, _ = _run(library)

    assert code == 0
    assert record["items"][0]["disposition"] == "not_yet_complete"
    assert content.exists()


def test_unreachable_client_fails_with_exit_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "library"
    library.mkdir()

    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=httpx.MockTransport(explode)
        ),
    )

    code, record, err = _run(library)

    assert code == cli.EXIT_CLIENT_FAILURE
    assert record == {}
    assert "unreachable" in err


def test_invalid_credentials_fail_with_exit_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=_transport([], login_ok=False)
        ),
    )

    code, record, err = _run(library)

    assert code == cli.EXIT_CLIENT_FAILURE
    assert record == {}
    assert "authentication failed" in err
    assert "secret" not in err


@pytest.mark.parametrize(
    "payload",
    [
        b"not json at all",
        b'({"unclosed": ',
        b'"a string"',
        b'[{"name": "x"}]',
        b"[null]",
        b'[{"name": "", "progress": 1, "state": "uploading", "save_path": "/tmp"}]',
        b'[{"name": "x", "progress": "fast", "state": "up", "save_path": "/tmp"}]',
    ],
)
def test_malformed_client_responses_fail_closed(
    payload: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        return httpx.Response(200, content=payload)

    client = QbittorrentClient(
        BASE_URL, "admin", "secret", transport=httpx.MockTransport(handler)
    )
    client.login()
    with pytest.raises(AdapterError) as caught:
        client.entries()
    assert "malformed client response" in str(caught.value)


def test_malformed_response_aborts_the_run_with_exit_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=_transport([], malformed=True)
        ),
    )

    code, record, err = _run(library)

    assert code == cli.EXIT_CLIENT_FAILURE
    assert record == {}
    assert "malformed client response" in err


def test_post_ingest_pause_and_delete_are_applied_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    content = tmp_path / "downloads" / "Movie.Production.2024.1080p-iGor"
    content.mkdir(parents=True)
    (content / "Movie.Production.2024.1080p-iGor.mkv").write_bytes(b"bytes")
    library = tmp_path / "library"
    library.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200, json=[_torrent("Movie.Production.2024.1080p-iGor", content)]
            )
        return httpx.Response(200, text="Ok.")

    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=httpx.MockTransport(handler)
        ),
    )

    code, record, _ = _run(library, "--post-ingest", "delete")

    assert code == 0
    assert record["items"][0]["disposition"] == "ingested"
    assert "/api/v2/torrents/delete" in calls


def test_client_failure_after_placement_is_reported_as_item_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = tmp_path / "downloads" / "Movie.Production.2024.1080p-iGor"
    content.mkdir(parents=True)
    (content / "Movie.Production.2024.1080p-iGor.mkv").write_bytes(b"bytes")
    library = tmp_path / "library"
    library.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/torrents/setLocation":
            return httpx.Response(500, text="boom")
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200, json=[_torrent("Movie.Production.2024.1080p-iGor", content)]
            )
        return httpx.Response(200, text="Ok.")

    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=httpx.MockTransport(handler)
        ),
    )

    code, record, _ = _run(library)

    item = record["items"][0]
    assert code == 0
    assert item["disposition"] == "error"
    assert "client update failed" in item["reason"]
    # placement itself completed and is reported
    assert (Path(item["destination"]) / "Movie.Production.2024.1080p-iGor.mkv").exists()


def test_dry_run_in_client_mode_does_not_call_the_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    content = tmp_path / "downloads" / "Movie.Production.2024.1080p-iGor"
    content.mkdir(parents=True)
    (content / "Movie.Production.2024.1080p-iGor.mkv").write_bytes(b"bytes")
    library = tmp_path / "library"
    library.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200, json=[_torrent("Movie.Production.2024.1080p-iGor", content)]
            )
        return httpx.Response(200, text="Ok.")

    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=httpx.MockTransport(handler)
        ),
    )

    code, record, _ = _run(library, "--dry-run")

    assert code == 0
    assert record["dry_run"] is True
    assert record["items"][0]["actions"]
    assert "/api/v2/torrents/setLocation" not in calls
    assert "/api/v2/torrents/delete" not in calls
    assert content.exists()
