"""Build minimal EPUB and OPF files for books-profile tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

_CONTAINER = """<?xml version="1.0"?>
<container version="1.0"
  xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _metadata_xml(
    *,
    title: str | None,
    author: str | None,
    year: int | None,
    series: str | None,
    series_index: int | float | None,
) -> str:
    metadata: list[str] = []
    if title is not None:
        metadata.append(f"<dc:title>{title}</dc:title>")
    if author is not None:
        metadata.append(f"<dc:creator>{author}</dc:creator>")
    if year is not None:
        metadata.append(f"<dc:date>{year}-01-01</dc:date>")
    if series is not None:
        metadata.append(f'<meta name="calibre:series" content="{series}"/>')
    if series_index is not None:
        metadata.append(f'<meta name="calibre:series_index" content="{series_index}"/>')
    return "".join(metadata)


def _opf(
    *,
    title: str | None,
    author: str | None,
    year: int | None,
    series: str | None,
    series_index: int | float | None,
) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        + _metadata_xml(
            title=title,
            author=author,
            year=year,
            series=series,
            series_index=series_index,
        )
        + "</metadata></package>\n"
    )


def make_epub(
    path: Path,
    *,
    title: str | None = None,
    author: str | None = None,
    year: int | None = None,
    series: str | None = None,
    series_index: int | float | None = None,
) -> Path:
    """Write a small valid EPUB carrying the requested OPF metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/container.xml", _CONTAINER)
        archive.writestr(
            "OEBPS/content.opf",
            _opf(
                title=title,
                author=author,
                year=year,
                series=series,
                series_index=series_index,
            ),
        )
    return path


def make_opf(
    path: Path,
    *,
    title: str | None = None,
    author: str | None = None,
    year: int | None = None,
    series: str | None = None,
    series_index: int | float | None = None,
) -> Path:
    """Write a standalone Calibre-style ``metadata.opf`` sidecar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _opf(
            title=title,
            author=author,
            year=year,
            series=series,
            series_index=series_index,
        ),
        encoding="utf-8",
    )
    return path
