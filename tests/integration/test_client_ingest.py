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
    root_path: Path | None = None,
    progress: float = 1.0,
    state: str = "uploading",
    category: str = "movies",
    torrent_hash: str = "h-" + "0" * 39,
) -> dict[str, Any]:
    return {
        "hash": torrent_hash,
        "name": name,
        "progress": progress,
        "state": state,
        "save_path": str(content_path.parent),
        "content_path": str(content_path),
        "root_path": "" if root_path is None else str(root_path),
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
    bodies: dict[str, str] = {}

    content = tmp_path / "downloads" / "Movie.Production.2024.1080p-iGor"
    content.mkdir(parents=True)
    (content / "Movie.Production.2024.1080p-iGor.mkv").write_bytes(b"movie-bytes")
    library = tmp_path / "library"
    library.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        bodies[request.url.path] = request.content.decode()
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200,
                json=[
                    _torrent(
                        "Movie.Production.2024.1080p-iGor",
                        content / "Movie.Production.2024.1080p-iGor.mkv",
                    )
                ],
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
    bodies: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        bodies[request.url.path] = request.content.decode()
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200,
                json=[
                    _torrent(
                        "Movie.Production.2024.1080p-iGor",
                        content / "Movie.Production.2024.1080p-iGor.mkv",
                    )
                ],
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
    assert record["items"][0]["client_actions"][-1]["op"] == "delete"
    assert "hashes=h-" in bodies["/api/v2/torrents/delete"]


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
                200,
                json=[
                    _torrent(
                        "Movie.Production.2024.1080p-iGor",
                        content / "Movie.Production.2024.1080p-iGor.mkv",
                    )
                ],
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
                200,
                json=[
                    _torrent(
                        "Movie.Production.2024.1080p-iGor",
                        content / "Movie.Production.2024.1080p-iGor.mkv",
                    )
                ],
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
    item = record["items"][0]
    assert item["actions"]
    # FR-006: the plan also says what a real run would do to the client
    assert [action["op"] for action in item["client_actions"]] == ["setLocation"]
    assert item["client_actions"][0]["detail"].startswith("planned:")
    assert "/api/v2/torrents/setLocation" not in calls
    assert "/api/v2/torrents/delete" not in calls
    assert content.exists()


def test_client_candidate_with_invisible_content_is_a_named_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "downloads" / "not-on-this-host"
    library = tmp_path / "library"
    library.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200, json=[_torrent("Missing.Content.2024.1080p", missing)]
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

    assert code == 0
    item = record["items"][0]
    assert item["disposition"] == "error"
    assert "source path not visible on this host" in item["reason"]
    assert str(missing) in item["reason"]


def test_multi_file_torrent_with_move_is_refused_with_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = tmp_path / "downloads" / "Show.Name.S01"
    content.mkdir(parents=True)
    (content / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (content / "Show.Name.S01E02.mkv").write_bytes(b"b")
    library = tmp_path / "library"
    library.mkdir()

    calls: list[str] = []
    transport = _transport([_torrent("Show.Name.S01", content, root_path=content)])
    import trovium.cli as cli_module

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return transport.handle_request(request)

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=httpx.MockTransport(handler)
        ),
    )

    code, record, _ = _run(library)

    assert code == 0
    item = record["items"][0]
    assert item["disposition"] == "error"
    assert "--mode copy or --mode hardlink" in item["reason"]
    # nothing placed, no client mutation
    assert not list(library.rglob("*.mkv"))
    assert content.exists()
    assert "/api/v2/torrents/setLocation" not in calls


def test_multi_file_torrent_ingests_with_copy_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = tmp_path / "downloads" / "Show.Name.S01"
    content.mkdir(parents=True)
    (content / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (content / "Show.Name.S01E02.mkv").write_bytes(b"b")
    library = tmp_path / "library"
    library.mkdir()

    transport = _transport([_torrent("Show.Name.S01", content, root_path=content)])
    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=transport
        ),
    )

    code, record, _ = _run(library, "--mode", "copy")

    assert code == 0
    assert record["items"][0]["disposition"] == "ingested"
    assert content.exists()
    assert len(list(library.rglob("*.mkv"))) == 2


def test_folder_torrent_with_one_media_file_is_refused_in_move_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a folder torrent can hold one video plus .nfo/.srt; media-file count alone
    # does not make it single-file from the client's point of view
    content = tmp_path / "downloads" / "Folder.Film.2024.1080p"
    content.mkdir(parents=True)
    (content / "Folder.Film.2024.1080p.mkv").write_bytes(b"movie")
    (content / "Folder.Film.2024.1080p.nfo").write_text("metadata")
    library = tmp_path / "library"
    library.mkdir()

    # qBittorrent reports content_path as the file for a one-file folder torrent;
    # root_path is the directory and is what distinguishes torrent shape
    media = content / "Folder.Film.2024.1080p.mkv"
    transport = _transport(
        [_torrent("Folder.Film.2024.1080p", media, root_path=content)]
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
    item = record["items"][0]
    assert item["disposition"] == "error"
    assert "--mode copy or --mode hardlink" in item["reason"]
    assert list(library.rglob("*.mkv")) == []
    assert content.exists()


def test_scoped_out_folder_torrent_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the move refusal must come after scope: a TV pack in a movie-scoped run is
    # out of scope, not an error
    content = tmp_path / "downloads" / "Show.Name.S02"
    content.mkdir(parents=True)
    (content / "Show.Name.S02E01.mkv").write_bytes(b"a")
    (content / "Show.Name.S02E02.mkv").write_bytes(b"b")
    library = tmp_path / "library"
    library.mkdir()

    transport = _transport([_torrent("Show.Name.S02", content, root_path=content)])
    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=transport
        ),
    )

    code, record, _ = _run(library, "--category", "movie")

    assert code == 0
    item = record["items"][0]
    assert item["disposition"] == "rejected_out_of_scope"
    assert "outside the declared category scope (movie)" in item["reason"]


def test_dry_run_plans_setlocation_for_already_handled_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = tmp_path / "downloads" / "Movie.Production.2024.1080p-iGor"
    content.mkdir(parents=True)
    media = content / "Movie.Production.2024.1080p-iGor.mkv"
    media.write_bytes(b"movie-bytes")
    library = tmp_path / "library"
    library.mkdir()

    transport = _transport([_torrent("Movie.Production.2024.1080p-iGor", media)])
    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=transport
        ),
    )

    code, first, _ = _run(library, "--mode", "copy")
    assert code == 0
    assert first["items"][0]["disposition"] == "ingested"

    code, planned, _ = _run(library, "--dry-run")
    code, executed, _ = _run(library)

    planned_item = planned["items"][0]
    executed_item = executed["items"][0]
    assert planned_item["disposition"] == "already_handled"
    assert [action["op"] for action in planned_item["actions"]] == ["delete"]
    planned_ops = [action["op"] for action in planned_item["client_actions"]]
    executed_ops = [action["op"] for action in executed_item["client_actions"]]
    assert planned_ops == executed_ops == ["setLocation"]
    planned_detail = planned_item["client_actions"][0]["detail"]
    executed_detail = executed_item["client_actions"][0]["detail"]
    assert planned_detail == f"planned: {executed_detail}"
    assert not media.exists()


def test_already_handled_folder_torrent_is_not_an_error_in_move_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = tmp_path / "downloads" / "Show.Name.S02"
    content.mkdir(parents=True)
    (content / "Show.Name.S02E01.mkv").write_bytes(b"a")
    (content / "Show.Name.S02E02.mkv").write_bytes(b"b")
    library = tmp_path / "library"
    library.mkdir()

    transport = _transport([_torrent("Show.Name.S02", content, root_path=content)])
    import trovium.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "QbittorrentClient",
        lambda url, username, password: QbittorrentClient(
            url, username, password, transport=transport
        ),
    )

    code, first, _ = _run(library, "--mode", "copy")
    assert code == 0
    assert first["items"][0]["disposition"] == "ingested"

    # move mode now refuses only when a placement would occur; here it is a no-op
    code, second, _ = _run(library)
    item = second["items"][0]
    assert code == 0
    assert item["disposition"] == "already_handled"
    assert item["actions"] == []
    assert content.exists()  # download copies are what the client seeds from


def test_move_with_pause_pauses_before_relocating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = tmp_path / "downloads" / "Movie.Production.2024.1080p-iGor"
    content.mkdir(parents=True)
    media = content / "Movie.Production.2024.1080p-iGor.mkv"
    media.write_bytes(b"movie-bytes")
    library = tmp_path / "library"
    library.mkdir()

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200,
                json=[_torrent("Movie.Production.2024.1080p-iGor", media)],
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

    code, planned, _ = _run(library, "--post-ingest", "pause", "--dry-run")
    assert code == 0
    planned_ops = [action["op"] for action in planned["items"][0]["client_actions"]]
    assert planned_ops == ["pause", "setLocation", "recheck"]

    code, record, _ = _run(library, "--post-ingest", "pause")

    assert code == 0
    assert record["items"][0]["disposition"] == "ingested"
    ops = [action["op"] for action in record["items"][0]["client_actions"]]
    assert ops == ["pause", "setLocation", "recheck"]
    # pause must land before the async move, and the recheck follows it
    assert calls.index("/api/v2/torrents/stop") < calls.index(
        "/api/v2/torrents/setLocation"
    )
    assert calls.index("/api/v2/torrents/setLocation") < calls.index(
        "/api/v2/torrents/recheck"
    )


def test_wait_until_complete_polls_until_progress_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/torrents/info":
            state["calls"] += 1
            progress = 0.0 if state["calls"] == 1 else 1.0
            return httpx.Response(
                200,
                json=[
                    {
                        "hash": "abc123",
                        "name": "x",
                        "progress": progress,
                        "state": "stoppedDL",
                        "save_path": "/tmp",
                        "root_path": "",
                    }
                ],
            )
        return httpx.Response(200, text="Ok.")

    client = QbittorrentClient(
        BASE_URL, "admin", "secret", transport=httpx.MockTransport(handler)
    )
    client.wait_until_complete("abc123", timeout=5.0, interval=0.0)
    assert state["calls"] == 2


def test_client_mode_dry_run_plan_matches_the_real_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = tmp_path / "downloads" / "Movie.Production.2024.1080p-iGor"
    content.mkdir(parents=True)
    (content / "Movie.Production.2024.1080p-iGor.mkv").write_bytes(b"bytes")
    library = tmp_path / "library"
    library.mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200,
                json=[
                    _torrent(
                        "Movie.Production.2024.1080p-iGor",
                        content / "Movie.Production.2024.1080p-iGor.mkv",
                    )
                ],
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

    code, planned, _ = _run(library, "--dry-run")
    assert code == 0
    code, executed, _ = _run(library)

    assert code == 0
    assert planned["items"][0]["actions"] == executed["items"][0]["actions"]
    assert planned["items"][0]["destination"] == executed["items"][0]["destination"]


def test_pause_uses_stop_endpoint_on_qbittorrent_5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, text="Ok.")

    client = QbittorrentClient(
        BASE_URL, "admin", "secret", transport=httpx.MockTransport(handler)
    )
    client.pause("abc123")
    assert calls == ["/api/v2/torrents/stop"]


def test_pause_falls_back_to_legacy_endpoint_on_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/torrents/stop":
            return httpx.Response(404)
        return httpx.Response(200, text="Ok.")

    client = QbittorrentClient(
        BASE_URL, "admin", "secret", transport=httpx.MockTransport(handler)
    )
    client.pause("abc123")
    assert calls == ["/api/v2/torrents/stop", "/api/v2/torrents/pause"]


def test_second_client_run_after_setlocation_keeps_the_library_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # After run 1 the client's content_path is the placed library file
    # (qBittorrent's documented single-file behavior). Run 2 must be a no-op
    # and must never delete that file.
    content = tmp_path / "downloads" / "Movie.Production.2024.1080p-iGor"
    content.mkdir(parents=True)
    source_file = content / "Movie.Production.2024.1080p-iGor.mkv"
    source_file.write_bytes(b"movie-bytes")
    library = tmp_path / "library"
    library.mkdir()
    placed = (
        library
        / "Movies"
        / "Movie Production (2024)"
        / "Movie.Production.2024.1080p-iGor.mkv"
    )

    state = {"path": source_file}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200, json=[_torrent("Movie.Production.2024.1080p-iGor", state["path"])]
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

    code, first, _ = _run(library)
    assert code == 0
    assert first["items"][0]["disposition"] == "ingested"
    assert placed.exists()

    state["path"] = placed  # the client now points at the library file
    code, second, _ = _run(library)

    assert code == 0
    item = second["items"][0]
    assert item["disposition"] == "already_handled"
    assert item["actions"] == []
    assert placed.exists()
