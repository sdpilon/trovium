"""Integration tests: ingest record piped into the rename step."""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.fixtures.books.make_source import main as make_books
from trovium import cli, rename


def _run(
    main: Callable[[list[str]], int], argv: list[str]
) -> tuple[int, dict[str, Any], str]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    payload = json.loads(out.getvalue()) if out.getvalue() else {}
    return code, payload, err.getvalue()


def _ingest(source: Path, library: Path, *extra: str) -> dict[str, Any]:
    code, record, _ = _run(
        cli.main,
        ["--source", str(source), "--library-root", str(library), *extra],
    )
    assert code == 0
    return record


def _write_record(tmp_path: Path, record: dict[str, Any]) -> Path:
    path = tmp_path / "ingest.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_books_ingest_then_rename(tmp_path: Path) -> None:
    make_books(tmp_path)
    library = tmp_path / "library"
    library.mkdir()
    ingest = _ingest(tmp_path / "source", library, "--profile", "books")
    record_path = _write_record(tmp_path, ingest)

    code, renamed, _ = _run(
        rename.main, ["--record", str(record_path), "--json", "compact"]
    )

    assert code == 0
    assert renamed["counts"]["error"] == 0
    assert (
        library
        / "Books"
        / "Jane Doe"
        / "Embedded Title (2020)"
        / "Jane Doe - Embedded Title (2020).epub"
    ).exists()
    assert (
        library
        / "Books"
        / "Folder Author"
        / "Solo Book (2018)"
        / "Folder Author - Solo Book (2018).epub"
    ).exists()
    assert (
        library / "Books" / "Folder Author" / "Solo Book (2018)" / "cover.jpg"
    ).exists()

    code, second, _ = _run(
        rename.main, ["--record", str(record_path), "--json", "compact"]
    )
    assert code == 0
    assert second["counts"]["renamed"] == 0
    assert second["counts"]["already_handled"] == 4


def test_video_ingest_then_rename(tmp_path: Path) -> None:
    source = tmp_path / "source"
    movie = source / "Movie.Production.2024.1080p"
    movie.mkdir(parents=True)
    (movie / "Movie.Production.2024.1080p.mkv").write_bytes(b"movie")
    (source / "Show.Name.S01").mkdir()
    (source / "Show.Name.S01" / "Show.Name.S01E01.mkv").write_bytes(b"one")
    (source / "Show.Name.S01" / "Show.Name.S01E02.mkv").write_bytes(b"two")
    library = tmp_path / "library"
    library.mkdir()
    ingest = _ingest(source, library)
    record_path = _write_record(tmp_path, ingest)

    code, renamed, _ = _run(rename.main, ["--record", str(record_path)])

    assert code == 0
    assert renamed["counts"]["error"] == 0
    assert (
        library / "Movies" / "Movie Production (2024)" / "Movie Production (2024).mkv"
    ).exists()
    assert (
        library / "TV" / "Show Name" / "Season 01" / "Show Name - S01E01.mkv"
    ).exists()
    assert (
        library / "TV" / "Show Name" / "Season 01" / "Show Name - S01E02.mkv"
    ).exists()


def test_rename_dry_run_matches_the_real_run(tmp_path: Path) -> None:
    source = tmp_path / "source"
    release = source / "Movie.Production.2024.1080p"
    release.mkdir(parents=True)
    (release / "Movie.Production.2024.1080p.mkv").write_bytes(b"movie")
    library = tmp_path / "library"
    library.mkdir()
    ingest = _ingest(source, library)
    record_path = _write_record(tmp_path, ingest)

    code, plan, _ = _run(
        rename.main,
        ["--record", str(record_path), "--dry-run", "--json", "compact"],
    )
    assert code == 0
    assert plan["dry_run"] is True
    assert (
        library
        / "Movies"
        / "Movie Production (2024)"
        / "Movie.Production.2024.1080p.mkv"
    ).exists()

    code, real, _ = _run(rename.main, ["--record", str(record_path)])
    assert code == 0
    assert plan["items"][0]["actions"] == real["items"][0]["actions"]


def test_copy_mode_record_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    release = source / "Movie.Production.2024.1080p"
    release.mkdir(parents=True)
    (release / "Movie.Production.2024.1080p.mkv").write_bytes(b"movie")
    library = tmp_path / "library"
    library.mkdir()
    ingest = _ingest(source, library, "--mode", "copy")
    record_path = _write_record(tmp_path, ingest)

    code, payload, err = _run(rename.main, ["--record", str(record_path)])

    assert code == 2
    assert payload == {}
    assert "--allow-unsafe" in err
    assert (
        library
        / "Movies"
        / "Movie Production (2024)"
        / "Movie.Production.2024.1080p.mkv"
    ).exists()
