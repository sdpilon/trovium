"""Integration tests: one command runs ingest and rename end to end."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from trovium import run


def _run(argv: list[str]) -> dict[str, Any]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert run.main(argv) == 0
    payload: dict[str, Any] = json.loads(out.getvalue())
    return payload


def test_video_pipeline_ingests_and_renames(tmp_path: Path) -> None:
    source = tmp_path / "source"
    movie = source / "Movie.Production.2024.1080p"
    movie.mkdir(parents=True)
    (movie / "Movie.Production.2024.1080p.mkv").write_bytes(b"movie")
    show = source / "Show.Name.S01"
    show.mkdir()
    (show / "Show.Name.S01E01.mkv").write_bytes(b"one")
    (show / "Show.Name.S01E02.mkv").write_bytes(b"two")
    library = tmp_path / "library"
    library.mkdir()

    payload = _run(
        [
            "--source",
            str(source),
            "--library-root",
            str(library),
            "--json",
            "compact",
        ]
    )

    assert payload["ingest"]["counts"]["ingested"] == 2
    assert payload["rename"]["counts"]["error"] == 0
    assert (
        library / "Movies" / "Movie Production (2024)" / "Movie Production (2024).mkv"
    ).exists()
    assert (
        library / "TV" / "Show Name" / "Season 01" / "Show Name - S01E01.mkv"
    ).exists()


def test_books_pipeline_from_a_config_file(tmp_path: Path) -> None:
    from tests.fixtures.books.make_source import main as make_books

    make_books(tmp_path)
    library = tmp_path / "library"
    library.mkdir()
    config = tmp_path / "config.ini"
    config.write_text(
        "[meta]\nschema_version = 1\n"
        f"[library]\nroot = {library}\n"
        f"[source]\nmode = disk\npath = {tmp_path / 'source'}\n"
        "[ingest]\nprofile = books\ncategory = all\nmode = move\n",
        encoding="utf-8",
    )

    payload = _run(["--config", str(config), "--json", "compact"])

    assert payload["profile"] == "books"
    assert payload["rename"]["counts"]["error"] == 0
    assert (
        library
        / "Books"
        / "Jane Doe"
        / "Embedded Title (2020)"
        / "Jane Doe - Embedded Title (2020).epub"
    ).exists()


def test_auto_mode_moves_and_renames_a_disk_book(tmp_path: Path) -> None:
    source = tmp_path / "source"
    folder = source / "Some Book"
    folder.mkdir(parents=True)
    (folder / "Some.Book.epub").write_bytes(b"epub-bytes")
    (folder / "metadata.opf").write_text(
        "<package><metadata><title>Some Book</title>"
        "<creator>Jane Doe</creator><date>2020</date></metadata></package>",
        encoding="utf-8",
    )
    library = tmp_path / "library"
    library.mkdir()

    payload = _run(
        [
            "--source",
            str(source),
            "--library-root",
            str(library),
            "--profile",
            "books",
            "--json",
            "compact",
        ]
    )

    item = payload["ingest"]["items"][0]
    assert item["actions"][0]["op"] == "move"
    assert payload["rename"]["counts"]["renamed"] == 1
    assert (
        library
        / "Books"
        / "Jane Doe"
        / "Some Book (2020)"
        / "Jane Doe - Some Book (2020).epub"
    ).exists()
    assert not (folder / "Some.Book.epub").exists()


def test_copy_then_rename_then_rerun_is_already_handled(tmp_path: Path) -> None:
    source = tmp_path / "source"
    folder = source / "Some Book"
    folder.mkdir(parents=True)
    (folder / "Some.Book.epub").write_bytes(b"epub-bytes")
    (folder / "metadata.opf").write_text(
        "<package><metadata><title>Some Book</title>"
        "<creator>Jane Doe</creator><date>2020</date></metadata></package>",
        encoding="utf-8",
    )
    library = tmp_path / "library"
    library.mkdir()
    argv = [
        "--source",
        str(source),
        "--library-root",
        str(library),
        "--profile",
        "books",
        "--mode",
        "copy",
        "--json",
        "compact",
    ]

    first = _run(argv)

    assert first["rename"]["counts"]["renamed"] == 1
    second = _run(argv)

    assert second["ingest"]["items"][0]["disposition"] == "already_handled"
    assert len(list(library.rglob("*.epub"))) == 1
