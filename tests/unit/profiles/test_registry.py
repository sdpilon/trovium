"""Unit tests: the profile registry and engine-level extensibility."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.fixtures.profiles.distros import DistrosProfile
from trovium import cli
from trovium.profiles import (
    PROFILES,
    available_profiles,
    get_profile,
    register_profile,
)
from trovium.record import Declared, Mode, OnFail


@pytest.fixture
def distros() -> Iterator[DistrosProfile]:
    profile = DistrosProfile()
    register_profile(profile)
    try:
        yield profile
    finally:
        PROFILES.pop(profile.name, None)


def test_built_in_profiles_are_registered() -> None:
    assert available_profiles() == ("video", "books")
    assert get_profile("video").name == "video"
    assert get_profile("books").name == "books"


def test_unknown_profile_names_the_available_ones() -> None:
    with pytest.raises(KeyError) as error:
        get_profile("nope")
    message = str(error.value)
    assert "nope" in message
    assert "video" in message
    assert "books" in message


def test_duplicate_registration_is_refused() -> None:
    with pytest.raises(ValueError, match="already registered"):
        register_profile(get_profile("video"))


def test_distros_profile_runs_through_the_engine(
    distros: DistrosProfile, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    image = source / "ubuntu-24.04.1-live-server-amd64.iso"
    image.write_bytes(b"iso")
    library = tmp_path / "library"
    library.mkdir()
    declared = Declared(
        profile=distros.name,
        library_root=str(library),
        category="all",
        mode=Mode.MOVE,
        on_fail=OnFail.CONTINUE,
        post_ingest=None,
    )

    summary = cli.run_disk(source, library, declared, False, distros)

    assert len(summary.items) == 1
    item = summary.items[0]
    assert item.disposition.value == "ingested"
    assert item.kind == "iso"
    assert item.destination == str(library / "Distros" / "Ubuntu" / "24.04.1" / "amd64")
    assert (Path(item.destination) / image.name).read_bytes() == b"iso"


def test_distros_profile_is_visible_to_the_cli(
    distros: DistrosProfile,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "debian-12.7.0-amd64-netinst.iso").write_bytes(b"iso")
    library = tmp_path / "library"
    library.mkdir()

    code = cli.main(
        [
            "--profile",
            "distros",
            "--source",
            str(source),
            "--library-root",
            str(library),
        ]
    )
    record = json.loads(capsys.readouterr().out)

    assert code == 0
    assert record["declared"]["profile"] == "distros"
    item = record["items"][0]
    assert item["kind"] == "iso"
    assert item["destination"] == str(
        library / "Distros" / "Debian" / "12.7.0" / "amd64"
    )


def test_unknown_profile_is_a_cli_misuse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    library = tmp_path / "library"
    library.mkdir()

    code = cli.main(
        [
            "--profile",
            "nope",
            "--source",
            str(source),
            "--library-root",
            str(library),
        ]
    )

    assert code == 2
    assert "video" in capsys.readouterr().err
