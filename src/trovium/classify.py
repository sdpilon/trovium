"""Classification of candidates from their own names only.

Vocabulary and precedence are pinned in
``specs/001-ingest-vertical-slice/data-model.md`` (Canonical grammar markers);
anything outside the grammar resolves to ``unresolvable`` -- this module never
guesses (FR-002).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

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
    """Resolved candidate kind."""

    MOVIE = "movie"
    TV = "tv"
    UNRESOLVABLE = "unresolvable"


@dataclass(frozen=True)
class Classification:
    """The resolved meaning of one candidate's names."""

    kind: Kind
    title: str | None = None
    season: int | None = None
    episodes: tuple[tuple[int, int], ...] = field(default=())
    year: int | None = None


UNRESOLVABLE = Classification(kind=Kind.UNRESOLVABLE)


def _tokens(name: str) -> list[str]:
    """Split a candidate name into tokens, dropping a known video extension.

    The extension set comes from ``VIDEO_EXTENSIONS`` so there is one source of
    truth for what counts as a media suffix.
    """
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


def classify(name: str, file_names: tuple[str, ...] = ()) -> Classification:
    """Classify a candidate by name; never guess (FR-002).

    Precedence: TV episode marker, then TV pack marker, then movie-with-year;
    no title tokens at all resolves to ``unresolvable``.
    """
    tokens = _tokens(name)
    if not tokens:
        return UNRESOLVABLE

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
            return UNRESOLVABLE
        return Classification(
            kind=Kind.TV, title=title, season=season, episodes=tuple(episodes)
        )

    pack_season = _SEASON_ONLY.search(name) or _SEASON_PHRASE.search(name)
    if pack_season is not None:
        season_value = next((group for group in pack_season.groups() if group), None)
        title = _title_from(tokens)
        if title and season_value and _holds_multiple_media(file_names):
            return Classification(kind=Kind.TV, title=title, season=int(season_value))

    year_match = _YEAR.search(name)
    if year_match is not None:
        tokens_before = [token for token in tokens if token != year_match.group(0)]
        title = _title_from(tokens_before)
        if title:
            return Classification(
                kind=Kind.MOVIE, title=title, year=int(year_match.group(0))
            )

    return UNRESOLVABLE


def _holds_multiple_media(file_names: tuple[str, ...]) -> bool:
    media = [name for name in file_names if is_media_file(name)]
    return len(media) >= 2


def is_media_file(name: str) -> bool:
    """True when the file name carries a video container extension."""
    return Path(name).suffix.lower() in VIDEO_EXTENSIONS


def is_incidental(name: str) -> bool:
    """True for release clutter that must never be ingested on its own."""
    stem = Path(name).stem.lower()
    return "sample" in stem or stem.startswith("rarbg")
