"""Unit tests: placement operations and the pinned conflict policy."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from trovium.library import ExistingItem, Sameness
from trovium.placement import apply_placement, plan_placement
from trovium.record import Disposition, Mode


def _no_conflict() -> ExistingItem:
    return ExistingItem(sameness=Sameness.NONE)


def test_move_places_and_removes_source(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    source = source_dir / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "Movies" / "Movie"

    plan = plan_placement(Mode.MOVE, (source,), destination, _no_conflict())
    assert plan.disposition is Disposition.INGESTED
    assert plan.actions
    assert plan.actions[0].bytes == len(b"payload")

    outcome = apply_placement(Mode.MOVE, (source,), plan)
    assert outcome.disposition is Disposition.INGESTED
    assert (destination / "movie.mkv").read_bytes() == b"payload"
    assert not source.exists()


def test_copy_leaves_original_in_place(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "lib" / "Movie"

    plan = plan_placement(Mode.COPY, (source,), destination, _no_conflict())
    outcome = apply_placement(Mode.COPY, (source,), plan)

    assert outcome.disposition is Disposition.INGESTED
    assert source.exists()
    assert (destination / "movie.mkv").read_bytes() == b"payload"


def test_hardlink_shares_storage_when_same_filesystem(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "lib" / "Movie"

    plan = plan_placement(Mode.HARDLINK, (source,), destination, _no_conflict())
    apply_placement(Mode.HARDLINK, (source,), plan)

    placed = destination / "movie.mkv"
    assert placed.exists()
    assert source.exists()
    assert placed.stat().st_ino == source.stat().st_ino


def test_cross_filesystem_hardlink_behaves_as_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "lib" / "Movie"

    monkeypatch.setattr("trovium.placement._same_filesystem", lambda *_: False)
    plan = plan_placement(Mode.HARDLINK, (source,), destination, _no_conflict())
    apply_placement(Mode.HARDLINK, (source,), plan)

    placed = destination / "movie.mkv"
    assert placed.exists()
    assert source.exists()
    assert placed.stat().st_ino != source.stat().st_ino
    assert placed.read_bytes() == b"payload"


def test_hardlink_os_link_failure_falls_back_to_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    source = tmp_path / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "lib" / "Movie"

    def refuse_link(src: Path, dst: Path) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr("trovium.placement.os.link", refuse_link)
    plan = plan_placement(Mode.HARDLINK, (source,), destination, _no_conflict())
    outcome = apply_placement(Mode.HARDLINK, (source,), plan)

    placed = destination / "movie.mkv"
    assert outcome.disposition is Disposition.INGESTED
    assert placed.exists()
    assert source.exists()
    assert placed.read_bytes() == b"payload"


def test_identical_content_copy_mode_leaves_source_untouched(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "lib" / "Movie"
    plan = plan_placement(
        Mode.COPY, (source,), destination, ExistingItem(sameness=Sameness.IDENTICAL)
    )
    outcome = apply_placement(Mode.COPY, (source,), plan)
    assert outcome.disposition is Disposition.ALREADY_HANDLED
    assert source.exists()


def test_identical_content_move_mode_removes_redundant_source(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "lib" / "Movie"
    plan = plan_placement(
        Mode.MOVE, (source,), destination, ExistingItem(sameness=Sameness.IDENTICAL)
    )
    outcome = apply_placement(Mode.MOVE, (source,), plan)
    assert outcome.disposition is Disposition.ALREADY_HANDLED
    assert outcome.reason is not None
    assert "redundant source removed" in outcome.reason
    assert not source.exists()


def test_same_name_different_content_is_error_never_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "lib" / "Movie"
    destination.mkdir(parents=True)
    (destination / "movie.mkv").write_bytes(b"other!!")

    plan = plan_placement(
        Mode.MOVE,
        (source,),
        destination,
        ExistingItem(
            sameness=Sameness.COLLISION, detail="same name, different content"
        ),
    )
    outcome = apply_placement(Mode.MOVE, (source,), plan)

    assert outcome.disposition is Disposition.ERROR
    assert (destination / "movie.mkv").read_bytes() == b"other!!"
    assert source.exists()


def test_no_media_files_is_rejected_out_of_scope(tmp_path: Path) -> None:
    destination = tmp_path / "lib"
    plan = plan_placement(Mode.MOVE, (), destination, _no_conflict())
    assert plan.disposition is Disposition.REJECTED_OUT_OF_SCOPE


def test_unreadable_source_file_is_named_error(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "lib" / "Movie"
    source.chmod(0o000)
    try:
        if os.geteuid() == 0:  # root ignores mode bits
            pytest.skip("running as root: permission bits are not enforced")
        # copy must read the source, so an unreadable file is a per-item error
        plan = plan_placement(Mode.COPY, (source,), destination, _no_conflict())
        outcome = apply_placement(Mode.COPY, (source,), plan)
        assert outcome.disposition is Disposition.ERROR
        assert outcome.reason is not None
    finally:
        source.chmod(0o644)


def test_unwritable_destination_is_named_error(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"payload")
    destination = tmp_path / "lib" / "Movie"
    destination.mkdir(parents=True)
    destination.chmod(0o500)
    try:
        plan = plan_placement(Mode.MOVE, (source,), destination, _no_conflict())
        outcome = apply_placement(Mode.MOVE, (source,), plan)
        if os.geteuid() == 0:
            pytest.skip("running as root: permission bits are not enforced")
        assert outcome.disposition is Disposition.ERROR
        assert outcome.reason is not None
        assert source.exists()
    finally:
        destination.chmod(0o755)
