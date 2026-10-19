"""Unit tests: the classifier's pinned grammar markers (data-model.md)."""

from __future__ import annotations

import pytest

from trovium.classify import VIDEO_EXTENSIONS, Kind, _tokens, classify


def test_movie_with_year_and_quality() -> None:
    result = classify("Movie.Production.2024.1080p.BluRay.x264-iGor")
    assert result.kind is Kind.MOVIE
    assert result.title == "Movie Production"
    assert result.year == 2024


def test_tv_episode_marker_beats_other_markers() -> None:
    result = classify("Shameless.US.S05E10.720p.HDTV.x264-KILLERS", ("a.mkv",))
    assert result.kind is Kind.TV
    assert result.title == "Shameless US"
    assert result.season == 5
    assert result.episodes == ((5, 10),)


def test_tv_multi_episode_range() -> None:
    result = classify("Series.Name.S01E01E02.1080p", ("a.mkv",))
    assert result.kind is Kind.TV
    assert result.episodes == ((1, 1), (1, 2))


def test_tv_pack_requires_file_count_signal() -> None:
    assert classify("Great.Show.S02", ("one.mkv",)).kind is Kind.UNRESOLVABLE
    pack = classify("Great.Show.S02", ("one.mkv", "two.mkv"))
    assert pack.kind is Kind.TV
    assert pack.season == 2


def test_season_phrase_pack() -> None:
    pack = classify("Another Show Season 3", ("a.mkv", "b.mkv"))
    assert pack.kind is Kind.TV
    assert pack.season == 3


def test_unresolvable_when_no_markers() -> None:
    assert classify("some random folder name").kind is Kind.UNRESOLVABLE
    assert classify("").kind is Kind.UNRESOLVABLE


def test_unresolvable_when_year_only_no_title() -> None:
    assert classify("2024").kind is Kind.UNRESOLVABLE


def test_movie_without_quality_marker() -> None:
    result = classify("Some Film (1999)")
    assert result.kind is Kind.MOVIE
    assert result.title == "Some Film"
    assert result.year == 1999


@pytest.mark.parametrize("extension", sorted(VIDEO_EXTENSIONS))
def test_tokens_strip_every_known_video_extension(extension: str) -> None:
    # one source of truth: VIDEO_EXTENSIONS, not a partial hardcoded list
    assert _tokens(f"Release.Name{extension}") == ["Release", "Name"]
