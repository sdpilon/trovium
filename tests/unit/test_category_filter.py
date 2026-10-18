"""Unit tests: declared category scope filtering (Story P3)."""

from __future__ import annotations

from trovium.classify import Classification, Kind
from trovium.cli import in_scope
from trovium.record import Category

MOVIE = Classification(kind=Kind.MOVIE, title="Movie", year=2024)
TV = Classification(kind=Kind.TV, title="Show", season=1)
UNRESOLVED = Classification(kind=Kind.UNRESOLVABLE)


def test_all_scope_keeps_everything() -> None:
    assert in_scope(MOVIE, Category.ALL)
    assert in_scope(TV, Category.ALL)


def test_movie_scope_excludes_tv() -> None:
    assert in_scope(MOVIE, Category.MOVIE)
    assert not in_scope(TV, Category.MOVIE)


def test_tv_scope_excludes_movies() -> None:
    assert in_scope(TV, Category.TV)
    assert not in_scope(MOVIE, Category.TV)


def test_unresolvable_stays_visible_under_any_scope() -> None:
    assert in_scope(UNRESOLVED, Category.MOVIE)
    assert in_scope(UNRESOLVED, Category.TV)
    assert in_scope(UNRESOLVED, Category.ALL)
