"""Unit tests: the books profile's names, metadata, grouping, and layout."""

from __future__ import annotations

import zipfile
from pathlib import Path

from tests.books_support import make_epub, make_opf
from trovium.profiles.base import CandidateGroup, Classification
from trovium.profiles.books import BooksProfile, parse_book_name
from trovium.profiles.epub import read_epub_metadata, read_opf_file


def test_filename_author_title_year() -> None:
    parsed = parse_book_name("Jane Doe - The Great Book (2020)")
    assert parsed is not None
    assert parsed.author == "Jane Doe"
    assert parsed.title == "The Great Book"
    assert parsed.year == 2020


def test_filename_year_first() -> None:
    parsed = parse_book_name("The Great Book (2020) - Jane Doe")
    assert parsed is not None
    assert parsed.title == "The Great Book"
    assert parsed.author == "Jane Doe"
    assert parsed.year == 2020


def test_filename_parenthetical_author() -> None:
    parsed = parse_book_name("The Great Book (Jane Doe)")
    assert parsed is not None
    assert parsed.title == "The Great Book"
    assert parsed.author == "Jane Doe"
    assert parsed.year is None


def test_filename_series_and_index() -> None:
    parsed = parse_book_name("Jane Doe - The Series #2 - The Book (2021)")
    assert parsed is not None
    assert parsed.author == "Jane Doe"
    assert parsed.series == "The Series"
    assert parsed.series_index == 2
    assert parsed.title == "The Book"
    assert parsed.year == 2021


def test_filename_author_title_year_with_release_tag() -> None:
    parsed = parse_book_name("Jane Doe - The Great Book (2020) [retail]")
    assert parsed is not None
    assert parsed.author == "Jane Doe"
    assert parsed.title == "The Great Book"
    assert parsed.year == 2020


def test_filename_bare_dash_is_unresolvable() -> None:
    assert parse_book_name("Sample Title - Sample Author") is None


def test_filename_numeric_prefix_is_unresolvable() -> None:
    assert parse_book_name("01 - Sample Title") is None


def test_filename_year_only_leaves_author_unknown() -> None:
    parsed = parse_book_name("The Great Book (2020)")
    assert parsed is not None
    assert parsed.title == "The Great Book"
    assert parsed.author is None
    assert parsed.year == 2020


def test_filename_without_a_title_is_unresolvable() -> None:
    assert parse_book_name("untitled") is None


def test_epub_metadata_wins_over_filename(tmp_path: Path) -> None:
    book = make_epub(
        tmp_path / "Wrong - Name (1999).epub",
        title="Embedded Title",
        author="Embedded Author",
        year=2020,
    )
    profile = BooksProfile()
    classification = profile.classify(
        CandidateGroup(name=book.stem, files=(book,), root=book)
    )
    assert classification is not None
    assert classification.title == "Embedded Title"
    assert classification.details["author"] == "Embedded Author"
    assert classification.details["year"] == 2020
    assert classification.details["metadata_source"] == "epub"


def test_epub_metadata_fills_missing_fields_from_filename(tmp_path: Path) -> None:
    book = make_epub(
        tmp_path / "Jane Doe - Filename Title (2021).epub",
        title="Embedded Title",
    )
    profile = BooksProfile()
    classification = profile.classify(
        CandidateGroup(name=book.stem, files=(book,), root=book)
    )
    assert classification is not None
    assert classification.title == "Embedded Title"
    assert classification.details["author"] == "Jane Doe"
    assert classification.details["year"] == 2021
    assert classification.details["metadata_source"] == "epub+filename"


def test_malformed_epub_falls_back_to_filename(tmp_path: Path) -> None:
    book = tmp_path / "Jane Doe - Broken Book (2019).epub"
    book.write_bytes(b"not a zip")
    profile = BooksProfile()
    classification = profile.classify(
        CandidateGroup(name=book.stem, files=(book,), root=book)
    )
    assert classification is not None
    assert classification.title == "Broken Book"
    assert classification.details["author"] == "Jane Doe"
    assert classification.details["metadata_source"] == "filename"


def test_sidecar_opf_classifies_a_pdf(tmp_path: Path) -> None:
    book = tmp_path / "Jane Doe - PDF Book (2018).pdf"
    book.write_bytes(b"%PDF-1.4")
    make_opf(
        tmp_path / "metadata.opf",
        title="Sidecar Title",
        author="Sidecar Author",
        year=2018,
    )
    profile = BooksProfile()
    classification = profile.classify(
        CandidateGroup(name=book.stem, files=(book,), root=book)
    )
    assert classification is not None
    assert classification.title == "Sidecar Title"
    assert classification.details["author"] == "Sidecar Author"
    assert classification.details["metadata_source"] == "opf"


def test_single_book_folder_carries_sidecars(tmp_path: Path) -> None:
    folder = tmp_path / "book"
    book = make_epub(folder / "Jane Doe - The Book (2020).epub", title="The Book")
    (folder / "cover.jpg").write_bytes(b"image")
    make_opf(folder / "metadata.opf", title="The Book")
    (folder / "notes.nfo").write_text("x")

    groups = BooksProfile().groups(folder)
    assert len(groups) == 1
    assert {path.name for path in groups[0].files} == {
        book.name,
        "cover.jpg",
        "metadata.opf",
        "notes.nfo",
    }


def test_multi_book_folder_splits_and_ignores_sidecars(tmp_path: Path) -> None:
    folder = tmp_path / "books"
    first = make_epub(folder / "Jane Doe - First (2020).epub", title="First")
    second = make_epub(folder / "John Smith - Second (2021).epub", title="Second")
    (folder / "cover.jpg").write_bytes(b"image")

    groups = BooksProfile().groups(folder)
    assert len(groups) == 2
    assert {group.name for group in groups} == {first.stem, second.stem}
    assert all(len(group.files) == 1 for group in groups)


def test_destination_uses_author_title_and_year(tmp_path: Path) -> None:
    profile = BooksProfile()
    classification = profile.classify(
        CandidateGroup(
            name="Jane Doe - The Book (2020)",
            files=(tmp_path / "Jane Doe - The Book (2020).pdf",),
        )
    )
    assert classification is not None
    assert profile.destination(classification, tmp_path) == (
        tmp_path / "Books" / "Jane Doe" / "The Book (2020)"
    )


def test_destination_uses_unknown_author_and_omits_missing_year(
    tmp_path: Path,
) -> None:
    profile = BooksProfile()
    classification = Classification(
        profile="books",
        kind="book",
        title="The Book",
        details={"author": None, "year": None},
    )
    assert profile.destination(classification, tmp_path) == (
        tmp_path / "Books" / "Unknown" / "The Book"
    )


def test_plan_names_author_title_year(tmp_path: Path) -> None:
    classification = Classification(
        profile="books",
        kind="book",
        title="The Book",
        details={"author": "Jane Doe", "year": 2020},
    )
    plans = BooksProfile().plan_names(
        classification, (tmp_path / "old.epub", tmp_path / "cover.jpg")
    )
    assert plans[0].name == "Jane Doe - The Book (2020).epub"
    assert plans[1].name == "cover.jpg"


def test_plan_names_series_and_unknown_author(tmp_path: Path) -> None:
    series = Classification(
        profile="books",
        kind="book",
        title="The Book",
        details={
            "author": "Jane Doe",
            "year": 2020,
            "series": "The Series",
            "series_index": 2,
        },
    )
    assert BooksProfile().plan_names(series, (tmp_path / "old.epub",))[0].name == (
        "Jane Doe - The Series #2 - The Book (2020).epub"
    )

    unknown = Classification(
        profile="books",
        kind="book",
        title="The Book",
        details={"author": None, "year": None},
    )
    assert BooksProfile().plan_names(unknown, (tmp_path / "old.epub",))[0].name == (
        "The Book.epub"
    )


def test_epub_reader_returns_none_without_container(tmp_path: Path) -> None:
    book = tmp_path / "empty.epub"
    with zipfile.ZipFile(book, "w") as archive:
        archive.writestr("OEBPS/content.opf", "<package/>")
    assert read_epub_metadata(book) is None


def test_opf_reader_rejects_entity_declarations(tmp_path: Path) -> None:
    opf = tmp_path / "metadata.opf"
    opf.write_text(
        '<?xml version="1.0"?><!DOCTYPE package [<!ENTITY x "y">]>'
        '<package><metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "&x;</dc:title></metadata></package>",
        encoding="utf-8",
    )
    assert read_opf_file(opf) is None
