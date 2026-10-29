"""Unit tests: convention-based already-handled comparison."""

from __future__ import annotations

from pathlib import Path

import pytest

from trovium.library import Sameness, compare_existing


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


def test_compare_existing_uses_a_planned_identical_target(tmp_path: Path) -> None:
    destination = tmp_path / "dest"
    planned_source = tmp_path / "planned.mkv"
    planned_source.write_bytes(b"abc")
    source = tmp_path / "source.mkv"
    source.write_bytes(b"abc")

    result = compare_existing(
        destination, (source,), planned={destination / source.name: planned_source}
    )

    assert result.sameness is Sameness.IDENTICAL


def test_compare_existing_detects_collision_with_a_planned_target(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "dest"
    planned_source = tmp_path / "planned.mkv"
    planned_source.write_bytes(b"xyz")
    source = tmp_path / "source.mkv"
    source.write_bytes(b"abc")

    result = compare_existing(
        destination, (source,), planned={destination / source.name: planned_source}
    )

    assert result.sameness is Sameness.COLLISION
    assert result.detail is not None


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


def test_renamed_library_file_counts_as_already_handled(tmp_path: Path) -> None:
    source = tmp_path / "Some.Release.Name.epub"
    source.write_bytes(b"book-bytes")
    destination = tmp_path / "dest"
    destination.mkdir()
    (destination / "Jane Doe - Some Book (2020).epub").write_bytes(b"book-bytes")

    result = compare_existing(destination, (source,))

    assert result.sameness is Sameness.IDENTICAL


def test_renamed_library_file_with_different_content_is_new(tmp_path: Path) -> None:
    source = tmp_path / "Some.Release.Name.epub"
    source.write_bytes(b"book-bytes")
    destination = tmp_path / "dest"
    destination.mkdir()
    (destination / "Jane Doe - Some Book (2020).epub").write_bytes(b"other-bytes")

    result = compare_existing(destination, (source,))

    assert result.sameness is Sameness.NONE
