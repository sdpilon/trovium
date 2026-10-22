"""The books profile: ebooks, EPUB metadata, and the author/title layout.

Classification prefers metadata embedded in an EPUB, then a Calibre
``metadata.opf`` sidecar, then a deliberately conservative filename grammar.
An ambiguous name resolves to ``None``; this profile never guesses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from trovium.profiles.base import (
    CandidateGroup,
    Classification,
    Profile,
    safe_component,
)
from trovium.profiles.epub import EpubMetadata, read_epub_metadata, read_opf_file

BOOK_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".azw",
        ".azw3",
        ".djvu",
        ".epub",
        ".fb2",
        ".mobi",
        ".pdf",
    }
)

_BRACKETED = re.compile(r"\[[^\]]*\]")
_SERIES = re.compile(
    r"^(?P<author>.+?)\s+-\s+(?P<series>.+?)\s+#\s*"
    r"(?P<index>\d+(?:\.\d+)?)\s+-\s+(?P<title>.+)$"
)
_YEAR_FIRST = re.compile(
    r"^(?P<title>.+?)\s+\((?P<year>(?:19|20)\d{2})\)\s+-\s+(?P<author>.+)$"
)
_PARENTHETICAL = re.compile(
    r"^(?P<title>.+?)\s+\((?P<parenthetical>[^()]+)\)"
    r"(?:\s+\((?P<year>(?:19|20)\d{2})\))?$"
)
_AUTHOR_TITLE = re.compile(r"^(?P<author>.+?)\s+-\s+(?P<title>.+)$")
_TRAILING_YEAR = re.compile(r"^(?P<base>.+?)\s+\((?P<year>(?:19|20)\d{2})\)$")


@dataclass(frozen=True)
class BookName:
    """The fields a conservative filename parse can recover."""

    title: str
    author: str | None = None
    year: int | None = None
    series: str | None = None
    series_index: int | float | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" ._-")
    return cleaned or None


def _split_year(value: str) -> tuple[str, int | None]:
    match = _TRAILING_YEAR.match(value)
    if match is None:
        return value, None
    return _clean(match.group("base")) or "", int(match.group("year"))


def _number(value: str) -> int | float:
    number = float(value)
    return int(number) if number.is_integer() else number


def parse_book_name(name: str) -> BookName | None:
    """Parse a conservative ebook filename; return ``None`` when unsure."""
    cleaned = _BRACKETED.sub(" ", name)
    cleaned = cleaned.replace("\u2013", "-").replace("\u2014", "-")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None

    series_match = _SERIES.match(cleaned)
    if series_match is not None:
        title_text, year = _split_year(series_match.group("title"))
        title = _clean(title_text)
        author = _clean(series_match.group("author"))
        series = _clean(series_match.group("series"))
        if title:
            return BookName(
                title=title,
                author=author,
                year=year,
                series=series,
                series_index=_number(series_match.group("index")),
            )

    year_first = _YEAR_FIRST.match(cleaned)
    if year_first is not None:
        title = _clean(year_first.group("title"))
        author = _clean(year_first.group("author"))
        if title:
            return BookName(
                title=title,
                author=author,
                year=int(year_first.group("year")),
            )

    author_title = _AUTHOR_TITLE.match(cleaned)
    if author_title is not None:
        title_text, year = _split_year(author_title.group("title"))
        title = _clean(title_text)
        author = _clean(author_title.group("author"))
        if title:
            return BookName(title=title, author=author, year=year)

    parenthetical = _PARENTHETICAL.match(cleaned)
    if parenthetical is not None:
        title_text, title_year = _split_year(parenthetical.group("title"))
        title = _clean(title_text)
        inside = _clean(parenthetical.group("parenthetical"))
        year_value = parenthetical.group("year")
        year = int(year_value) if year_value else title_year
        if inside is not None and re.fullmatch(r"(?:19|20)\d{2}", inside):
            year = int(inside)
            author = None
        else:
            author = inside
        if title:
            return BookName(title=title, author=author, year=year)

    return None


def _is_sidecar(path: Path) -> bool:
    lower = path.name.lower()
    return (
        lower.startswith("cover.")
        or lower == "metadata.opf"
        or path.suffix.lower() == ".nfo"
    )


class BooksProfile(Profile):
    """Ebooks under ``Books/<Author>/<Title> (Year)/``."""

    name = "books"
    categories = ("book", "all")
    extensions = BOOK_EXTENSIONS

    def groups(self, entry: Path) -> tuple[CandidateGroup, ...]:
        if entry.is_file():
            if self.is_member(entry) and not self.is_incidental(entry):
                return (CandidateGroup(name=entry.stem, files=(entry,), root=entry),)
            return ()
        return tuple(
            CandidateGroup(
                name=book.stem,
                files=(book, *self._sidecars(book)),
                root=book.parent,
            )
            for book in self.collect_files(entry)
        )

    def _sidecars(self, book: Path) -> tuple[Path, ...]:
        """Sidecars travel only when their folder holds exactly one book."""
        try:
            siblings = [
                path
                for path in book.parent.iterdir()
                if path.is_file()
                and self.is_member(path)
                and not self.is_incidental(path)
            ]
            if len(siblings) != 1:
                return ()
            return tuple(
                sorted(
                    path
                    for path in book.parent.iterdir()
                    if path.is_file() and path != book and _is_sidecar(path)
                )
            )
        except OSError:
            return ()

    def classify(self, group: CandidateGroup) -> Classification | None:
        if not group.files:
            return None
        primary = group.files[0]
        filename = parse_book_name(group.name)

        embedded = (
            read_epub_metadata(primary) if primary.suffix.lower() == ".epub" else None
        )
        sidecar: EpubMetadata | None = None
        if embedded is None:
            sidecar_path = primary.parent / "metadata.opf"
            if sidecar_path.is_file():
                sidecar = read_opf_file(sidecar_path)

        metadata = embedded or sidecar
        metadata_label = "epub" if embedded is not None else ("opf" if sidecar else "")
        used_metadata = False
        used_filename = False

        def pick(meta_value: object, file_value: object) -> object:
            nonlocal used_metadata, used_filename
            if meta_value is not None:
                used_metadata = True
                return meta_value
            if file_value is not None:
                used_filename = True
                return file_value
            return None

        title = pick(
            metadata.title if metadata is not None else None,
            filename.title if filename is not None else None,
        )
        if title is None:
            return None
        author = pick(
            metadata.author if metadata is not None else None,
            filename.author if filename is not None else None,
        )
        year = pick(
            metadata.year if metadata is not None else None,
            filename.year if filename is not None else None,
        )
        series = pick(
            metadata.series if metadata is not None else None,
            filename.series if filename is not None else None,
        )
        series_index = pick(
            metadata.series_index if metadata is not None else None,
            filename.series_index if filename is not None else None,
        )

        if used_metadata and used_filename:
            source = f"{metadata_label}+filename"
        elif used_metadata:
            source = metadata_label
        else:
            source = "filename"

        return Classification(
            profile=self.name,
            kind="book",
            title=str(title),
            details={
                "author": None if author is None else str(author),
                "year": year,
                "series": None if series is None else str(series),
                "series_index": series_index,
                "format": primary.suffix.lower().lstrip("."),
                "metadata_source": source,
            },
        )

    def destination(self, classification: Classification, library_root: Path) -> Path:
        author = safe_component(str(classification.details.get("author") or "Unknown"))
        title = safe_component(classification.title or "Unknown")
        year = classification.details.get("year")
        leaf = f"{title} ({year})" if isinstance(year, int) else title
        return library_root / "Books" / author / leaf
