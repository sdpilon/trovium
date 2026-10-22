"""Unit tests: rename planning, safety refusals, and idempotency."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trovium import rename
from trovium.profiles import get_profile
from trovium.record import OnFail


def _item(
    destination: Path,
    *,
    name: str = "item",
    kind: str = "book",
    title: str = "Book",
    details: dict[str, object] | None = None,
    client_actions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": name,
        "source": "disk",
        "disposition": "ingested",
        "kind": kind,
        "title": title,
        "details": details or {},
        "destination": str(destination),
    }
    if client_actions is not None:
        item["client_actions"] = client_actions
    return item


def _record(
    items: list[dict[str, Any]],
    *,
    mode: str = "move",
    profile: str = "books",
) -> dict[str, Any]:
    return {
        "declared": {
            "profile": profile,
            "library_root": "/tmp/library",
            "mode": mode,
        },
        "items": items,
    }


def _book(destination: Path, *, old: str = "old.epub") -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    source = destination / old
    source.write_bytes(b"book")
    return source


def test_book_rename_keeps_sidecars(tmp_path: Path) -> None:
    destination = tmp_path / "book"
    source = _book(destination)
    (destination / "cover.jpg").write_bytes(b"image")
    payload = _record(
        [
            _item(
                destination,
                details={"author": "Jane Doe", "year": 2020},
            )
        ]
    )

    summary = rename.rename_items(
        payload,
        get_profile("books"),
        dry_run=False,
        allow_unsafe=False,
        on_fail=OnFail.CONTINUE,
    )

    item = summary.items[0]
    assert item.disposition is rename.RenameDisposition.RENAMED
    assert (destination / "Jane Doe - Book (2020).epub").exists()
    assert not source.exists()
    assert (destination / "cover.jpg").exists()
    assert [action.op.value for action in item.actions] == ["rename"]


def test_second_run_is_already_handled(tmp_path: Path) -> None:
    destination = tmp_path / "book"
    _book(destination)
    payload = _record(
        [_item(destination, details={"author": "Jane Doe", "year": 2020})]
    )
    profile = get_profile("books")

    first = rename.rename_items(
        payload, profile, dry_run=False, allow_unsafe=False, on_fail=OnFail.CONTINUE
    )
    second = rename.rename_items(
        payload, profile, dry_run=False, allow_unsafe=False, on_fail=OnFail.CONTINUE
    )

    assert first.items[0].disposition is rename.RenameDisposition.RENAMED
    assert second.items[0].disposition is rename.RenameDisposition.ALREADY_HANDLED
    assert second.items[0].actions == []


def test_collision_is_an_error_and_leaves_both_files(tmp_path: Path) -> None:
    destination = tmp_path / "book"
    source = _book(destination)
    (destination / "Jane Doe - Book (2020).epub").write_bytes(b"other")
    payload = _record(
        [_item(destination, details={"author": "Jane Doe", "year": 2020})]
    )

    summary = rename.rename_items(
        payload,
        get_profile("books"),
        dry_run=False,
        allow_unsafe=False,
        on_fail=OnFail.CONTINUE,
    )

    assert summary.items[0].disposition is rename.RenameDisposition.ERROR
    assert "Jane Doe - Book (2020).epub" in (summary.items[0].reason or "")
    assert source.exists()
    assert (destination / "Jane Doe - Book (2020).epub").read_bytes() == b"other"


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    destination = tmp_path / "book"
    source = _book(destination)
    payload = _record(
        [_item(destination, details={"author": "Jane Doe", "year": 2020})]
    )

    summary = rename.rename_items(
        payload,
        get_profile("books"),
        dry_run=True,
        allow_unsafe=False,
        on_fail=OnFail.CONTINUE,
    )

    item = summary.items[0]
    assert item.disposition is rename.RenameDisposition.RENAMED
    assert item.actions
    assert source.exists()
    assert not (destination / "Jane Doe - Book (2020).epub").exists()
    assert summary.to_json()["dry_run"] is True


def test_client_relocated_item_is_skipped(tmp_path: Path) -> None:
    destination = tmp_path / "book"
    source = _book(destination)
    payload = _record(
        [
            _item(
                destination,
                details={"author": "Jane Doe", "year": 2020},
                client_actions=[{"op": "setLocation", "detail": "library"}],
            )
        ]
    )

    summary = rename.rename_items(
        payload,
        get_profile("books"),
        dry_run=False,
        allow_unsafe=False,
        on_fail=OnFail.CONTINUE,
    )

    assert summary.items[0].disposition is rename.RenameDisposition.SKIPPED
    assert "seeding" in (summary.items[0].reason or "")
    assert source.exists()


def test_copy_record_is_refused_by_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "book"
    source = _book(destination)
    record = tmp_path / "record.json"
    record.write_text(
        json.dumps(
            _record(
                [_item(destination, details={"author": "Jane Doe", "year": 2020})],
                mode="copy",
            )
        ),
        encoding="utf-8",
    )

    code = rename.main(["--record", str(record)])

    captured = capsys.readouterr()
    assert code == 2
    assert "--allow-unsafe" in captured.err
    assert source.exists()


def test_allow_unsafe_permits_copy_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "book"
    _book(destination)
    record = tmp_path / "record.json"
    record.write_text(
        json.dumps(
            _record(
                [_item(destination, details={"author": "Jane Doe", "year": 2020})],
                mode="copy",
            )
        ),
        encoding="utf-8",
    )

    code = rename.main(["--record", str(record), "--allow-unsafe"])

    assert code == 0
    assert (destination / "Jane Doe - Book (2020).epub").exists()
    assert "warning" in capsys.readouterr().err


def test_unknown_profile_is_misuse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = tmp_path / "record.json"
    record.write_text(json.dumps(_record([], profile="nope")), encoding="utf-8")

    code = rename.main(["--record", str(record)])

    assert code == 2
    assert "video" in capsys.readouterr().err


def test_record_without_a_profile_is_misuse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = tmp_path / "record.json"
    record.write_text(
        json.dumps({"declared": {"mode": "move"}, "items": []}),
        encoding="utf-8",
    )

    code = rename.main(["--record", str(record)])

    assert code == 2
    assert "profile" in capsys.readouterr().err


def test_malformed_json_is_misuse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = tmp_path / "record.json"
    record.write_text("{", encoding="utf-8")

    code = rename.main(["--record", str(record)])

    assert code == 2
    assert "JSON" in capsys.readouterr().err


def test_on_fail_stop_stops_after_the_first_error(tmp_path: Path) -> None:
    first = tmp_path / "first"
    _book(first)
    (first / "Jane Doe - Book (2020).epub").write_bytes(b"other")
    second = tmp_path / "second"
    _book(second)
    details = {"author": "Jane Doe", "year": 2020}
    payload = _record([_item(first, details=details), _item(second, details=details)])
    profile = get_profile("books")

    stopped = rename.rename_items(
        payload, profile, dry_run=False, allow_unsafe=False, on_fail=OnFail.STOP
    )
    continued = rename.rename_items(
        payload, profile, dry_run=False, allow_unsafe=False, on_fail=OnFail.CONTINUE
    )

    assert len(stopped.items) == 1
    assert len(continued.items) == 2
    assert continued.items[1].disposition is rename.RenameDisposition.RENAMED


def test_a_rename_record_can_be_renamed_again(tmp_path: Path) -> None:
    destination = tmp_path / "book"
    _book(destination)
    payload = _record(
        [_item(destination, details={"author": "Jane Doe", "year": 2020})]
    )
    profile = get_profile("books")

    first = rename.rename_items(
        payload, profile, dry_run=False, allow_unsafe=False, on_fail=OnFail.CONTINUE
    )
    second = rename.rename_items(
        first.to_json(),
        profile,
        dry_run=False,
        allow_unsafe=False,
        on_fail=OnFail.CONTINUE,
    )

    assert second.items[0].disposition is rename.RenameDisposition.ALREADY_HANDLED
