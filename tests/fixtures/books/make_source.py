"""Create the books acceptance fixture under a caller-supplied root."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.books_support import make_epub, make_opf  # noqa: E402


def main(root: Path) -> None:
    source = root / "source"
    source.mkdir(parents=True, exist_ok=True)

    make_epub(
        source / "Jane Doe - The Great Book (2020).epub",
        title="Embedded Title",
        author="Jane Doe",
        year=2020,
    )
    (source / "Alice Author - The PDF Book (2021).pdf").write_bytes(b"%PDF-1.4")
    (source / "Jane Doe - Broken Book (2019).epub").write_bytes(b"not a zip")
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


if __name__ == "__main__":
    main(Path(sys.argv[1]))
