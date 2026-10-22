"""Defensive EPUB/OPF metadata reading for the books profile.

Only the archive's metadata is read: the container points at the OPF package
document, which carries the Dublin Core title/creator/date and (for Calibre
libraries) the series fields. Reads are capped and any parse failure returns
``None`` so the caller can fall back to the filename. No external entities are
resolved and the book is never modified.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

MAX_CONTAINER_BYTES = 64 * 1024
MAX_OPF_BYTES = 1024 * 1024
_CONTAINER_PATH = "META-INF/container.xml"
_YEAR = re.compile(r"(?:19|20)\d{2}")


@dataclass(frozen=True)
class EpubMetadata:
    """The metadata fields the books profile can use."""

    title: str | None = None
    author: str | None = None
    year: int | None = None
    series: str | None = None
    series_index: int | float | None = None

    def has_any(self) -> bool:
        """True when at least one usable field was found."""
        return any(
            value is not None
            for value in (
                self.title,
                self.author,
                self.year,
                self.series,
                self.series_index,
            )
        )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = _YEAR.search(value)
    return int(match.group(0)) if match else None


def _parse_number(value: str | None) -> int | float | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    if match is None:
        return None
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _parse_opf(data: bytes) -> EpubMetadata | None:
    """Parse an OPF package document; local names keep EPUB 2/3 variants working."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None

    metadata = next(
        (element for element in root.iter() if _local(element.tag) == "metadata"),
        root,
    )

    title: str | None = None
    creators: list[str] = []
    date: str | None = None
    series: str | None = None
    series_index: int | float | None = None

    for element in metadata.iter():
        name = _local(element.tag)
        text = _clean(element.text)
        if name == "title" and title is None:
            title = text
        elif name == "creator" and text is not None:
            creators.append(text)
        elif name == "date" and date is None:
            date = text
        elif name == "meta":
            key = (element.get("name") or element.get("property") or "").lower()
            content = _clean(element.get("content"))
            value = content or text
            if "series_index" in key or key == "group-position":
                series_index = _parse_number(value)
            elif (
                "series" in key and "index" not in key
            ) or "belongs-to-collection" in key:
                series = value

    parsed = EpubMetadata(
        title=title,
        author=" & ".join(creators) if creators else None,
        year=_parse_int(date),
        series=series,
        series_index=series_index,
    )
    return parsed if parsed.has_any() else None


def _safe_xml(data: bytes) -> bool:
    """Reject documents that could expand entities; OPF needs no DTD."""
    lowered = data.lower()
    return b"<!doctype" not in lowered and b"<!entity" not in lowered


def _read_zip_entry(archive: zipfile.ZipFile, name: str, cap: int) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.is_dir() or info.file_size > cap:
        return None
    try:
        data = archive.read(info)
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile):
        return None
    if len(data) > cap or not _safe_xml(data):
        return None
    return data


def read_epub_metadata(path: Path) -> EpubMetadata | None:
    """Read an EPUB's OPF metadata, or return ``None`` on any failure."""
    try:
        with zipfile.ZipFile(path) as archive:
            container = _read_zip_entry(archive, _CONTAINER_PATH, MAX_CONTAINER_BYTES)
            if container is None:
                return None
            try:
                root = ET.fromstring(container)
            except ET.ParseError:
                return None
            rootfiles = [
                element
                for element in root.iter()
                if _local(element.tag) == "rootfile" and element.get("full-path")
            ]
            if not rootfiles:
                return None
            preferred = next(
                (
                    element
                    for element in rootfiles
                    if element.get("media-type") == "application/oebps-package+xml"
                ),
                rootfiles[0],
            )
            opf_path = preferred.get("full-path")
            if not opf_path:
                return None
            package = _read_zip_entry(archive, opf_path, MAX_OPF_BYTES)
            if package is None:
                return None
            return _parse_opf(package)
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, RuntimeError):
        return None


def read_opf_file(path: Path) -> EpubMetadata | None:
    """Read a standalone ``metadata.opf`` sidecar, or return ``None``."""
    try:
        if path.stat().st_size > MAX_OPF_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if not _safe_xml(data):
        return None
    return _parse_opf(data)
