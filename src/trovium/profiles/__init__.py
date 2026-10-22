"""Built-in media profiles and the registry the engine resolves names through.

A new profile is a module that implements ``Profile`` plus one registration
call. The engine never imports a built-in profile directly.
"""

from __future__ import annotations

from trovium.profiles.base import (
    CandidateGroup,
    Classification,
    NamePlan,
    Profile,
)
from trovium.profiles.books import BooksProfile
from trovium.profiles.video import VideoProfile

PROFILES: dict[str, Profile] = {
    profile.name: profile for profile in (VideoProfile(), BooksProfile())
}


def available_profiles() -> tuple[str, ...]:
    """Registered profile names, in registration order."""
    return tuple(PROFILES)


def get_profile(name: str) -> Profile:
    """Resolve a registered profile by name."""
    try:
        return PROFILES[name]
    except KeyError as error:
        allowed = ", ".join(available_profiles())
        raise KeyError(
            f"unknown profile {name!r}; available profiles: {allowed}"
        ) from error


def register_profile(profile: Profile) -> None:
    """Register a profile; used by built-ins, tests, and future distributions."""
    if not profile.name:
        raise ValueError("a profile must declare a non-empty name")
    if not profile.categories:
        raise ValueError(f"profile {profile.name!r} must declare categories")
    if profile.name in PROFILES:
        raise ValueError(f"profile {profile.name!r} is already registered")
    PROFILES[profile.name] = profile


__all__ = [
    "PROFILES",
    "CandidateGroup",
    "Classification",
    "NamePlan",
    "Profile",
    "available_profiles",
    "get_profile",
    "register_profile",
]
