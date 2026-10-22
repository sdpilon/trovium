"""Integration tests: the books-profile disk journey."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.books_support import make_epub, make_opf
from trovium import cli


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.CLIENT_URL_ENV, raising=False)


def _run(source: Path, library: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cli.main(
            [
                "--profile",
                "books",
                "--source",
                str(source),
                "--library-root",
                str(library),
                *extra,
            ]
        )
    payload = json.loads(buffer.getvalue()) if buffer.getvalue() else {}
    return code, payload


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()

    make_epub(
        source / "Jane Doe - The Great Book (2020).epub",
        title="Embedded Title",
        author="Jane Doe",
        year=2020,
    )
    (source / "Alice Author - The PDF Book (2021).pdf").write_bytes(b"%PDF-1.4")
    (source / "mystery file.epub").write_bytes(b"not a zip")

    solo = source / "Solo Book"
    make_epub(solo / "Solo Book (2018).epub")
    make_opf(
        solo / "metadata.opf",
        title="Solo Book",
        author="Folder Author",
        year=2018,
    )
    (solo / "cover.jpg").write_bytes(b"image")

    pair = source / "Two Books"
    make_epub(pair / "First Author - First Book (2017).epub")
    make_epub(pair / "Second Author - Second Book (2016).epub")
    (pair / "cover.jpg").write_bytes(b"image")
    return source


def test_books_ingest_places_ebooks_and_preserves_names(tmp_path: Path) -> None:
    source, library = _make_source(tmp_path), tmp_path / "library"
    library.mkdir()

    code, record = _run(source, library, "--mode", "copy")

    assert code == 0
    assert record["declared"]["profile"] == "books"
    assert record["declared"]["category"] == "all"
    by_name = {item["name"]: item for item in record["items"]}

    embedded = by_name["Jane Doe - The Great Book (2020)"]
    assert embedded["disposition"] == "ingested"
    assert embedded["kind"] == "book"
    assert embedded["details"]["metadata_source"] == "epub"
    assert embedded["destination"] == str(
        library / "Books" / "Jane Doe" / "Embedded Title (2020)"
    )
    assert (
        Path(embedded["destination"]) / "Jane Doe - The Great Book (2020).epub"
    ).read_bytes()

    pdf = by_name["Alice Author - The PDF Book (2021)"]
    assert pdf["disposition"] == "ingested"
    assert pdf["details"]["metadata_source"] == "filename"
    assert pdf["destination"] == str(
        library / "Books" / "Alice Author" / "The PDF Book (2021)"
    )

    solo = by_name["Solo Book (2018)"]
    assert solo["disposition"] == "ingested"
    assert solo["details"]["metadata_source"] == "opf"
    solo_dir = Path(solo["destination"])
    assert solo_dir.name == "Solo Book (2018)"
    assert (solo_dir / "cover.jpg").read_bytes() == b"image"
    assert (solo_dir / "metadata.opf").exists()

    first = by_name["First Author - First Book (2017)"]
    second = by_name["Second Author - Second Book (2016)"]
    assert first["destination"] == str(
        library / "Books" / "First Author" / "First Book (2017)"
    )
    assert second["destination"] == str(
        library / "Books" / "Second Author" / "Second Book (2016)"
    )
    assert not (Path(first["destination"]) / "cover.jpg").exists()

    ambiguous = by_name["mystery file"]
    assert ambiguous["disposition"] == "unresolvable"
    assert ambiguous["reason"]
    assert record["counts"]["total"] == len(record["items"])


def test_books_second_run_is_a_no_op(tmp_path: Path) -> None:
    source, library = _make_source(tmp_path), tmp_path / "library"
    library.mkdir()
    _run(source, library, "--mode", "copy")
    before = sorted(str(path) for path in library.rglob("*"))

    code, record = _run(source, library, "--mode", "copy")
    by_name = {item["name"]: item for item in record["items"]}

    assert code == 0
    assert record["counts"]["ingested"] == 0
    assert sorted(str(path) for path in library.rglob("*")) == before
    assert by_name["Jane Doe - The Great Book (2020)"]["disposition"] == (
        "already_handled"
    )
    assert by_name["Alice Author - The PDF Book (2021)"]["disposition"] == (
        "already_handled"
    )
    assert by_name["mystery file"]["disposition"] == "unresolvable"


def test_books_category_filter_rejects_video_scope(tmp_path: Path) -> None:
    source, library = _make_source(tmp_path), tmp_path / "library"
    library.mkdir()

    code, record = _run(source, library, "--category", "movie")

    assert code == 2
    assert record == {}
