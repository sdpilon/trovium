"""Unit tests: declared category scope filtering (Story P3)."""

from __future__ import annotations

from trovium.cli import in_scope


def test_all_scope_keeps_everything() -> None:
    assert in_scope("movie", "all")
    assert in_scope("tv", "all")
    assert in_scope("book", "all")


def test_movie_scope_excludes_tv() -> None:
    assert in_scope("movie", "movie")
    assert not in_scope("tv", "movie")


def test_tv_scope_excludes_movies() -> None:
    assert in_scope("tv", "tv")
    assert not in_scope("movie", "tv")


def test_book_scope_excludes_video_kinds() -> None:
    assert in_scope("book", "book")
    assert not in_scope("movie", "book")
    assert not in_scope("tv", "book")
