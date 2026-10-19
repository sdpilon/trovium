"""Unit tests: destination resolution and convention-based already-handled."""

from __future__ import annotations

from pathlib import Path

import pytest

from trovium.classify import classify
from trovium.library import (
    Sameness,
    collect_media_files,
    compare_existing,
    resolve_destination,
)


def test_movie_destination_uses_movies_root_and_year(tmp_path: Path) -> None:
    classification = classify("Movie.Production.2024.1080p-iGor")
    destination = resolve_destination(classification, tmp_path)
    assert destination == tmp_path / "Movies" / "Movie Production (2024)"


def test_tv_destination_uses_tv_root_show_and_season(tmp_path: Path) -> None:
    classification = classify("Shameless.US.S05E10.720p-HDTV", ("a.mkv",))
    destination = resolve_destination(classification, tmp_path)
    assert destination == tmp_path / "TV" / "Shameless US" / "Season 05"


def test_collect_media_files_skips_samples_and_non_media(tmp_path: Path) -> None:
    release = tmp_path / "Release"
    release.mkdir()
    (release / "movie.mkv").write_bytes(b"data")
    (release / "sample-movie.mkv").write_bytes(b"data")
    (release / "notes.txt").write_text("x")
    nested = release / "Subs"
    nested.mkdir()
    (nested / "more.mp4").write_bytes(b"data")
    names = sorted(path.name for path in collect_media_files(release))
    assert names == ["more.mp4", "movie.mkv"]


def test_compare_existing_none_when_absent(tmp_path: Path) -> None:
    source = tmp_path / "src.mkv"
    source.write_bytes(b"abc")
    result = compare_existing(tmp_path / "dest", (source,))
    assert result.sameness is Sameness.NONE


def test_compare_existing_identical_content(tmp_path: Path) -> None:
    source = tmp_path / "src.mkv"
    source.write_bytes(b"abc")
    destination = tmp_path / "dest"
    destination.mkdir()
    (destination / "src.mkv").write_bytes(b"abc")
    assert compare_existing(destination, (source,)).sameness is Sameness.IDENTICAL


def test_compare_existing_collision_on_same_name_different_content(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src.mkv"
    source.write_bytes(b"abc")
    destination = tmp_path / "dest"
    destination.mkdir()
    (destination / "src.mkv").write_bytes(b"xyz")
    result = compare_existing(destination, (source,))
    assert result.sameness is Sameness.COLLISION
    assert result.detail is not None


def test_compare_existing_collision_on_equal_size_different_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src.mkv"
    source.write_bytes(b"aaa")
    destination = tmp_path / "dest"
    destination.mkdir()
    (destination / "src.mkv").write_bytes(b"bbb")
    assert compare_existing(destination, (source,)).sameness is Sameness.COLLISION


@pytest.mark.parametrize("order", ["first-missing", "second-missing"])
def test_compare_existing_detects_collision_in_partial_overlap(
    tmp_path: Path, order: str
) -> None:
    # one file present with different content, one absent: a collision on any
    # present file wins, independent of the candidate's file order
    destination = tmp_path / "dest"
    destination.mkdir()
    (destination / "shared.mkv").write_bytes(b"OLD-CONTENT")
    present = tmp_path / "shared.mkv"
    present.write_bytes(b"NEW-CONTENT")
    absent = tmp_path / "absent.mkv"
    absent.write_bytes(b"x")
    files = (absent, present) if order == "first-missing" else (present, absent)

    result = compare_existing(destination, files)
    assert result.sameness is Sameness.COLLISION
    assert result.detail is not None
