"""Unit tests: the pipeline runner's record and skip reasons."""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.books.make_source import main as make_books
from trovium import run


def _run(
    main: Callable[[list[str]], int], argv: list[str]
) -> tuple[int, dict[str, Any], str]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    payload = json.loads(out.getvalue()) if out.getvalue() else {}
    return code, payload, err.getvalue()


def _movie_source(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    release = source / "Movie.Production.2024.1080p"
    release.mkdir(parents=True)
    (release / "Movie.Production.2024.1080p.mkv").write_bytes(b"movie")
    library = tmp_path / "library"
    library.mkdir()
    return source, library


def test_books_pipeline_runs_both_steps(tmp_path: Path) -> None:
    make_books(tmp_path)
    library = tmp_path / "library"
    library.mkdir()

    code, payload, _ = _run(
        run.main,
        [
            "--profile",
            "books",
            "--source",
            str(tmp_path / "source"),
            "--library-root",
            str(library),
            "--json",
            "compact",
        ],
    )

    assert code == 0
    assert payload["source"] == "run"
    assert payload["profile"] == "books"
    assert payload["ingest"]["counts"]["ingested"] == 4
    assert payload["rename"]["counts"]["error"] == 0
    assert (
        library
        / "Books"
        / "Jane Doe"
        / "Embedded Title (2020)"
        / "Jane Doe - Embedded Title (2020).epub"
    ).exists()


def test_dry_run_changes_nothing_and_skips_rename(tmp_path: Path) -> None:
    source, library = _movie_source(tmp_path)

    code, payload, _ = _run(
        run.main,
        [
            "--source",
            str(source),
            "--library-root",
            str(library),
            "--dry-run",
            "--json",
            "compact",
        ],
    )

    assert code == 0
    assert payload["dry_run"] is True
    assert payload["rename"] is None
    assert "dry-run" in payload["rename_skipped"]
    assert (
        source / "Movie.Production.2024.1080p" / "Movie.Production.2024.1080p.mkv"
    ).exists()
    assert list(library.iterdir()) == []


def test_copy_mode_skips_rename_by_default(tmp_path: Path) -> None:
    source, library = _movie_source(tmp_path)

    code, payload, _ = _run(
        run.main,
        [
            "--source",
            str(source),
            "--library-root",
            str(library),
            "--mode",
            "copy",
            "--json",
            "compact",
        ],
    )

    assert code == 0
    assert payload["ingest"]["counts"]["ingested"] == 1
    assert payload["rename"] is None
    assert "allow-unsafe" in payload["rename_skipped"]
    assert (
        library
        / "Movies"
        / "Movie Production (2024)"
        / "Movie.Production.2024.1080p.mkv"
    ).exists()


def test_allow_unsafe_permits_rename_in_copy_mode(tmp_path: Path) -> None:
    source, library = _movie_source(tmp_path)

    code, payload, _ = _run(
        run.main,
        [
            "--source",
            str(source),
            "--library-root",
            str(library),
            "--mode",
            "copy",
            "--allow-unsafe",
            "--json",
            "compact",
        ],
    )

    assert code == 0
    assert payload["rename"] is not None
    assert payload["rename"]["counts"]["renamed"] == 1
    assert (
        library / "Movies" / "Movie Production (2024)" / "Movie Production (2024).mkv"
    ).exists()


def test_skip_rename_leaves_the_placed_names(tmp_path: Path) -> None:
    source, library = _movie_source(tmp_path)

    code, payload, _ = _run(
        run.main,
        [
            "--source",
            str(source),
            "--library-root",
            str(library),
            "--skip-rename",
            "--json",
            "compact",
        ],
    )

    assert code == 0
    assert payload["rename"] is None
    assert payload["rename_skipped"] == "skipped by --skip-rename"
    assert (
        library
        / "Movies"
        / "Movie Production (2024)"
        / "Movie.Production.2024.1080p.mkv"
    ).exists()


def test_unreachable_client_exits_three_and_does_not_rename(
    tmp_path: Path,
) -> None:
    library = tmp_path / "library"
    library.mkdir()

    code, payload, err = _run(
        run.main,
        [
            "--client-url",
            "http://127.0.0.1:9",
            "--library-root",
            str(library),
        ],
    )

    assert code == 3
    assert payload == {}
    assert "error" in err
    assert list(library.iterdir()) == []


def test_config_drives_the_pipeline(tmp_path: Path) -> None:
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

    code, payload, _ = _run(run.main, ["--config", str(config), "--json", "compact"])

    assert code == 0
    assert payload["profile"] == "books"
    assert payload["ingest"]["counts"]["ingested"] == 4
    assert payload["rename"] is not None


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("copy", "allow-unsafe"), ("hardlink", "allow-unsafe")],
)
def test_unsafe_modes_name_the_override(
    tmp_path: Path, mode: str, expected: str
) -> None:
    source, library = _movie_source(tmp_path)

    code, payload, _ = _run(
        run.main,
        [
            "--source",
            str(source),
            "--library-root",
            str(library),
            "--mode",
            mode,
            "--json",
            "compact",
        ],
    )

    assert code == 0
    assert payload["rename"] is None
    assert expected in payload["rename_skipped"]
