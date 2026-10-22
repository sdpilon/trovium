"""The video profile: movies, TV episodes, and season packs.

The grammar and precedence are pinned in
``specs/001-ingest-vertical-slice/data-model.md`` (Canonical grammar markers);
anything outside the grammar resolves to ``None`` -- this profile never guesses
(FR-002).
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from trovium.profiles.base import (
    CandidateGroup,
    Classification,
    NamePlan,
    Profile,
    safe_component,
)

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".avi",
        ".flv",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".m2ts",
        ".ts",
        ".vob",
        ".webm",
        ".wmv",
    }
)

_QUALITY_TOKENS: frozenset[str] = frozenset(
    {
        "2160p",
        "1080p",
        "720p",
        "576p",
        "480p",
        "4k",
        "uhd",
        "hdr",
        "hdr10",
        "dolby",
        "dv",
        "remux",
        "bluray",
        "blu",
        "brrip",
        "bdrip",
        "webrip",
        "web",
        "webdl",
        "hdtv",
        "dvdrip",
        "x264",
        "x265",
        "h264",
        "h265",
        "hevc",
        "avc",
        "xvid",
        "divx",
        "aac",
        "ac3",
        "dts",
        "atmos",
        "dd5",
        "ddp5",
        "proper",
        "repack",
        "extended",
        "unrated",
        "internal",
    }
)

_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
_EPISODE = re.compile(r"[sS](\d{1,2})[\s._-]?[eE](\d{1,3})")
_EXTRA_EPISODE = re.compile(r"[eE](\d{1,3})(?!\d)")
_SEASON_ONLY = re.compile(r"(?:^|[\s._-])[sS](\d{1,2})(?![\d\w])")
_SEASON_PHRASE = re.compile(r"season[\s._-]?(\d{1,2})", re.IGNORECASE)


class Kind(StrEnum):
    """Resolved video kind."""

    MOVIE = "movie"
    TV = "tv"


def _tokens(name: str) -> list[str]:
    """Split a candidate name into tokens, dropping a known video extension."""
    path = Path(name)
    stem = path.stem if path.suffix.lower() in VIDEO_EXTENSIONS else path.name
    return [token for token in re.split(r"[\s._\-\[\]()]+", stem) if token]


_MARKER = re.compile(r"^(?:[sS]\d{1,2}(?:[eE]\d{1,3})?|season)$")


def _is_padding(token: str) -> bool:
    lowered = token.lower()
    return (
        lowered in _QUALITY_TOKENS
        or bool(re.fullmatch(r"(19|20)\d{2}", token))
        or bool(_MARKER.fullmatch(token))
    )


def _title_from(tokens: list[str]) -> str:
    kept: list[str] = []
    for token in tokens:
        if _is_padding(token):
            break
        kept.append(token)
    return " ".join(kept).strip()


def classify(name: str, file_names: tuple[str, ...] = ()) -> Classification | None:
    """Classify a video candidate by name; never guess (FR-002).

    Precedence: TV episode marker, then TV pack marker, then movie-with-year;
    no title tokens at all resolves to ``None``.
    """
    tokens = _tokens(name)
    if not tokens:
        return None

    episode_match = _EPISODE.search(name)
    if episode_match is not None:
        season = int(episode_match.group(1))
        first_episode = int(episode_match.group(2))
        episodes = [(season, first_episode)]
        tail = name[episode_match.end() :]
        for extra in _EXTRA_EPISODE.finditer(tail):
            episodes.append((season, int(extra.group(1))))
        title = _title_from(tokens)
        if not title:
            return None
        return Classification(
            profile=VideoProfile.name,
            kind=Kind.TV.value,
            title=title,
            details={"season": season, "episodes": tuple(episodes)},
        )

    pack_season = _SEASON_ONLY.search(name) or _SEASON_PHRASE.search(name)
    if pack_season is not None:
        season_value = next((group for group in pack_season.groups() if group), None)
        title = _title_from(tokens)
        if title and season_value and _holds_multiple_media(file_names):
            return Classification(
                profile=VideoProfile.name,
                kind=Kind.TV.value,
                title=title,
                details={"season": int(season_value)},
            )

    year_match = _YEAR.search(name)
    if year_match is not None:
        tokens_before = [token for token in tokens if token != year_match.group(0)]
        title = _title_from(tokens_before)
        if title:
            return Classification(
                profile=VideoProfile.name,
                kind=Kind.MOVIE.value,
                title=title,
                details={"year": int(year_match.group(0))},
            )

    return None


def _holds_multiple_media(file_names: tuple[str, ...]) -> bool:
    media = [name for name in file_names if is_media_file(name)]
    return len(media) >= 2


def is_media_file(name: str) -> bool:
    """True when the file name carries a video container extension."""
    return Path(name).suffix.lower() in VIDEO_EXTENSIONS


def is_incidental_name(name: str) -> bool:
    """True for release clutter that must never be ingested on its own."""
    stem = Path(name).stem.lower()
    return "sample" in stem or stem.startswith("rarbg")


def _episode_marker(name: str) -> tuple[int, tuple[int, ...]] | None:
    match = _EPISODE.search(name)
    if match is None:
        return None
    season = int(match.group(1))
    episodes = [int(match.group(2))]
    tail = name[match.end() :]
    for extra in _EXTRA_EPISODE.finditer(tail):
        episodes.append(int(extra.group(1)))
    return season, tuple(episodes)


def _episode_tag(season: int, episodes: tuple[int, ...]) -> str:
    tag = f"S{season:02d}E{episodes[0]:02d}"
    for episode in episodes[1:]:
        tag += f"-E{episode:02d}"
    return tag


class VideoProfile(Profile):
    """Movies and TV, with the existing `Movies/` and `TV/` layout."""

    name = "video"
    categories = ("movie", "tv", "all")
    extensions = VIDEO_EXTENSIONS

    def is_incidental(self, path: Path) -> bool:
        return is_incidental_name(path.name)

    def groups(self, entry: Path) -> tuple[CandidateGroup, ...]:
        files = self.collect_files(entry)
        if not files:
            return ()
        return (CandidateGroup(name=entry.name, files=files, root=entry),)

    def classify(self, group: CandidateGroup) -> Classification | None:
        return classify(group.name, tuple(path.name for path in group.files))

    def destination(self, classification: Classification, library_root: Path) -> Path:
        title = safe_component(classification.title or "Unknown")
        year = classification.details.get("year")
        season = classification.details.get("season")
        if classification.kind == Kind.MOVIE.value:
            leaf = f"{title} ({year})" if isinstance(year, int) else title
            return library_root / "Movies" / leaf
        if classification.kind == Kind.TV.value:
            series = library_root / "TV" / title
            if isinstance(season, int):
                return series / f"Season {season:02d}"
            return series
        return library_root / "Unresolved" / title

    def plan_names(
        self, classification: Classification, files: tuple[Path, ...]
    ) -> tuple[NamePlan, ...]:
        title = safe_component(classification.title or "Unknown")
        members = [path for path in files if self.is_member(path)]
        plans: dict[Path, NamePlan] = {
            path: NamePlan(path, path.name)
            for path in files
            if not self.is_member(path)
        }

        if not classification.title:
            for path in members:
                plans[path] = NamePlan(path, None, "no title in the classification")
            return tuple(plans[path] for path in files)

        if classification.kind == Kind.MOVIE.value:
            if len(members) != 1:
                for path in members:
                    plans[path] = NamePlan(
                        path, None, "multi-file movie cannot be renamed safely"
                    )
                return tuple(plans[path] for path in files)
            year = classification.details.get("year")
            suffix = f" ({year})" if isinstance(year, int) else ""
            plans[members[0]] = NamePlan(
                members[0], f"{title}{suffix}{members[0].suffix}"
            )
            return tuple(plans[path] for path in files)

        if classification.kind == Kind.TV.value:
            for path in members:
                marker = _episode_marker(path.name)
                if marker is None:
                    plans[path] = NamePlan(
                        path, None, "no episode marker in the file name"
                    )
                    continue
                season, episodes = marker
                plans[path] = NamePlan(
                    path,
                    f"{title} - {_episode_tag(season, episodes)}{path.suffix}",
                )
            return tuple(plans[path] for path in files)

        for path in members:
            plans[path] = NamePlan(path, None, "unsupported video kind")
        return tuple(plans[path] for path in files)
