"""Unit tests: the video profile's destination and grouping behavior."""

from __future__ import annotations

from pathlib import Path

from trovium.profiles.base import Classification
from trovium.profiles.video import VideoProfile, classify


def test_movie_destination_uses_movies_root_and_year(tmp_path: Path) -> None:
    classification = classify("Movie.Production.2024.1080p-iGor")
    assert classification is not None
    destination = VideoProfile().destination(classification, tmp_path)
    assert destination == tmp_path / "Movies" / "Movie Production (2024)"


def test_tv_destination_uses_tv_root_show_and_season(tmp_path: Path) -> None:
    classification = classify("Shameless.US.S05E10.720p-HDTV", ("a.mkv",))
    assert classification is not None
    destination = VideoProfile().destination(classification, tmp_path)
    assert destination == tmp_path / "TV" / "Shameless US" / "Season 05"


def test_collect_files_skips_samples_and_non_media(tmp_path: Path) -> None:
    release = tmp_path / "Release"
    release.mkdir()
    (release / "movie.mkv").write_bytes(b"data")
    (release / "sample-movie.mkv").write_bytes(b"data")
    (release / "notes.txt").write_text("x")
    nested = release / "Subs"
    nested.mkdir()
    (nested / "more.mp4").write_bytes(b"data")
    names = sorted(path.name for path in VideoProfile().collect_files(release))
    assert names == ["more.mp4", "movie.mkv"]


def test_groups_returns_one_candidate_for_a_release_directory(
    tmp_path: Path,
) -> None:
    release = tmp_path / "Movie.Production.2024.1080p"
    release.mkdir()
    (release / "Movie.Production.2024.1080p.mkv").write_bytes(b"x")
    groups = VideoProfile().groups(release)
    assert len(groups) == 1
    assert groups[0].name == release.name
    assert groups[0].root == release


def test_groups_returns_nothing_for_a_non_media_directory(tmp_path: Path) -> None:
    empty = tmp_path / "notes"
    empty.mkdir()
    (empty / "readme.txt").write_text("x")
    assert VideoProfile().groups(empty) == ()


def test_plan_names_movie_uses_title_and_year(tmp_path: Path) -> None:
    classification = Classification(
        profile="video",
        kind="movie",
        title="Movie Production",
        details={"year": 2024},
    )
    plans = VideoProfile().plan_names(
        classification, (tmp_path / "Movie.Production.2024.1080p.mkv",)
    )
    assert plans[0].name == "Movie Production (2024).mkv"


def test_plan_names_tv_uses_the_file_episode_marker(tmp_path: Path) -> None:
    classification = Classification(
        profile="video",
        kind="tv",
        title="Show Name",
        details={"season": 1},
    )
    plans = VideoProfile().plan_names(
        classification,
        (
            tmp_path / "Show.Name.S01E01E02.1080p.mkv",
            tmp_path / "Show.Name.S01E03.mkv",
        ),
    )
    assert [plan.name for plan in plans] == [
        "Show Name - S01E01-E02.mkv",
        "Show Name - S01E03.mkv",
    ]


def test_plan_names_multi_file_movie_is_skipped(tmp_path: Path) -> None:
    classification = Classification(
        profile="video",
        kind="movie",
        title="Movie",
        details={"year": 2024},
    )
    plans = VideoProfile().plan_names(
        classification, (tmp_path / "part1.mkv", tmp_path / "part2.mkv")
    )
    assert all(plan.name is None for plan in plans)
    assert all(plan.reason for plan in plans)


def test_plan_names_tv_without_a_marker_is_skipped(tmp_path: Path) -> None:
    classification = Classification(
        profile="video",
        kind="tv",
        title="Show Name",
        details={"season": 1},
    )
    plans = VideoProfile().plan_names(classification, (tmp_path / "featurette.mkv",))
    assert plans[0].name is None
    assert plans[0].reason
