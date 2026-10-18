"""Integration tests: the disk-source journey (Story P1, SC-002, SC-003)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trovium import cli


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.CLIENT_URL_ENV, raising=False)


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "Movie.Production.2024.1080p-iGor").mkdir(parents=True)
    (
        source
        / "Movie.Production.2024.1080p-iGor"
        / "Movie.Production.2024.1080p-iGor.mkv"
    ).write_bytes(b"movie-bytes")
    (source / "Show.Name.S02").mkdir()
    (source / "Show.Name.S02" / "Show.Name.S02E01.mkv").write_bytes(b"ep1")
    (source / "Show.Name.S02" / "Show.Name.S02E02.mkv").write_bytes(b"ep2")
    (source / "hand-gathered").mkdir()
    (source / "hand-gathered" / "notes.txt").write_text("no media here")
    (source / "loose-unlabeled-thing.mkv").write_bytes(b"mystery")
    return source


def _run(source: Path, library: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cli.main(
            ["--source", str(source), "--library-root", str(library), *extra]
        )
    payload = json.loads(buffer.getvalue()) if buffer.getvalue() else {}
    return code, payload


def test_disk_ingest_places_media_and_reports(tmp_path: Path) -> None:
    source, library = _make_source(tmp_path), tmp_path / "library"
    library.mkdir()

    code, record = _run(source, library)

    assert code == 0
    assert record["source"] == "disk"
    by_name = {item["name"]: item for item in record["items"]}

    movie = by_name["Movie.Production.2024.1080p-iGor"]
    assert movie["disposition"] == "ingested"
    assert movie["kind"] == "movie"
    placed = Path(movie["destination"]) / "Movie.Production.2024.1080p-iGor.mkv"
    assert placed.read_bytes() == b"movie-bytes"
    assert movie["actions"][0]["op"] == "move"

    pack = by_name["Show.Name.S02"]
    assert pack["disposition"] == "ingested"
    assert pack["kind"] == "tv"
    assert sorted(path.name for path in Path(pack["destination"]).iterdir()) == [
        "Show.Name.S02E01.mkv",
        "Show.Name.S02E02.mkv",
    ]

    assert by_name["hand-gathered"]["disposition"] == "rejected_out_of_scope"
    assert by_name["hand-gathered"]["reason"]

    assert by_name["loose-unlabeled-thing.mkv"]["disposition"] == "unresolvable"
    assert by_name["loose-unlabeled-thing.mkv"]["reason"]

    assert record["counts"]["total"] == len(record["items"])


def test_original_file_names_are_preserved(tmp_path: Path) -> None:
    source, library = _make_source(tmp_path), tmp_path / "library"
    library.mkdir()
    _run(source, library)
    assert (
        library
        / "Movies"
        / "Movie Production (2024)"
        / "Movie.Production.2024.1080p-iGor.mkv"
    ).exists()


def test_second_run_is_a_no_op_reporting_already_handled(tmp_path: Path) -> None:
    source, library = _make_source(tmp_path), tmp_path / "library"
    library.mkdir()
    _run(source, library)
    before = sorted(str(p) for p in library.rglob("*"))

    code, record = _run(source, library)

    assert code == 0
    # move mode emptied the source; nothing new is ingested and the library is
    # unchanged (any remaining items are the non-media/unresolvable stragglers)
    assert record["counts"]["ingested"] == 0
    assert sorted(str(p) for p in library.rglob("*")) == before
    by_name = {item["name"]: item for item in record["items"]}
    assert by_name["hand-gathered"]["disposition"] == "rejected_out_of_scope"
    assert by_name["loose-unlabeled-thing.mkv"]["disposition"] == "unresolvable"


def test_copy_mode_keeps_source_and_reports_already_handled_on_rerun(
    tmp_path: Path,
) -> None:
    source, library = _make_source(tmp_path), tmp_path / "library"
    library.mkdir()
    _run(source, library, "--mode", "copy")

    assert (
        source
        / "Movie.Production.2024.1080p-iGor"
        / "Movie.Production.2024.1080p-iGor.mkv"
    ).exists()

    code, record = _run(source, library, "--mode", "copy")
    by_name = {item["name"]: item for item in record["items"]}
    assert code == 0
    assert by_name["Movie.Production.2024.1080p-iGor"]["disposition"] == (
        "already_handled"
    )


def test_run_continues_past_item_errors_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    bad = source / "Broken.Movie.2024.1080p"
    bad.mkdir()
    (bad / "Broken.Movie.2024.1080p.mkv").write_bytes(b"x")
    good = source / "Good.Movie.2023.1080p"
    good.mkdir()
    (good / "Good.Movie.2023.1080p.mkv").write_bytes(b"y")

    library = tmp_path / "library"
    library.mkdir()
    # pre-place conflicting content so the first item errors
    destination = library / "Movies" / "Broken Movie (2024)"
    destination.mkdir(parents=True)
    (destination / "Broken.Movie.2024.1080p.mkv").write_bytes(b"different")

    code, record = _run(source, library)
    by_name = {item["name"]: item for item in record["items"]}

    assert code == 0
    assert by_name["Broken.Movie.2024.1080p"]["disposition"] == "error"
    assert by_name["Good.Movie.2023.1080p"]["disposition"] == "ingested"


def test_on_fail_stop_halts_after_first_error(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    bad = source / "A.Broken.2024.1080p"
    bad.mkdir()
    (bad / "A.Broken.2024.1080p.mkv").write_bytes(b"x")
    later = source / "B.Later.2025.1080p"
    later.mkdir()
    (later / "B.Later.2025.1080p.mkv").write_bytes(b"y")

    library = tmp_path / "library"
    library.mkdir()
    destination = library / "Movies" / "A Broken (2024)"
    destination.mkdir(parents=True)
    (destination / "A.Broken.2024.1080p.mkv").write_bytes(b"different")

    code, record = _run(source, library, "--on-fail", "stop")
    names = [item["name"] for item in record["items"]]

    assert code == 0
    assert names == ["A.Broken.2024.1080p"]
    assert (later / "B.Later.2025.1080p.mkv").exists()


def test_category_scope_touches_only_the_selected_kind(tmp_path: Path) -> None:
    source, library = _make_source(tmp_path), tmp_path / "library"
    library.mkdir()
    _, record = _run(source, library, "--category", "movie")
    by_name = {item["name"]: item for item in record["items"]}

    assert by_name["Movie.Production.2024.1080p-iGor"]["disposition"] == "ingested"
    assert "Show.Name.S02" not in by_name
    assert (source / "Show.Name.S02").exists()
    # unresolvable stays visible under any scope
    assert by_name["loose-unlabeled-thing.mkv"]["disposition"] == "unresolvable"


def test_empty_result_is_clean_success(tmp_path: Path) -> None:
    source, library = tmp_path / "source", tmp_path / "library"
    source.mkdir()
    library.mkdir()
    (source / "Show.Name.S01").mkdir()
    (source / "Show.Name.S01" / "Show.Name.S01E01.mkv").write_bytes(b"x")
    (source / "Show.Name.S01" / "Show.Name.S01E02.mkv").write_bytes(b"x")

    code, record = _run(source, library, "--category", "movie")
    assert code == 0
    assert record["items"] == []
    assert (source / "Show.Name.S01").exists()


def test_quickstart_style_timing_probe_on_fifty_candidates(tmp_path: Path) -> None:
    import time

    source = tmp_path / "source"
    source.mkdir()
    for index in range(50):
        release = source / f"Movie.Number{index}.2024.1080p"
        release.mkdir()
        for part in range(20):
            (release / f"part{part}.mkv").write_bytes(b"x" * 1024)
    library = tmp_path / "library"
    library.mkdir()

    started = time.monotonic()
    code, record = _run(source, library, "--category", "movie")
    elapsed = time.monotonic() - started

    assert code == 0
    assert record["counts"]["total"] == 50
    assert elapsed < 60.0, f"SC-001 probe exceeded a minute: {elapsed:.2f}s"
