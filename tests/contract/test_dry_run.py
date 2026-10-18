"""Contract tests: inspect-only mode emits the plan and changes nothing (P4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trovium import cli


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.CLIENT_URL_ENV, raising=False)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    release = source / "Movie.Production.2024.1080p-iGor"
    release.mkdir()
    (release / "Movie.Production.2024.1080p-iGor.mkv").write_bytes(b"payload")
    library = tmp_path / "library"
    library.mkdir()
    return source, library


def test_dry_run_reports_plan_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, library = _fixture(tmp_path)
    before_source, before_library = _snapshot(source), _snapshot(library)

    code = cli.main(
        [
            "--source",
            str(source),
            "--library-root",
            str(library),
            "--dry-run",
        ]
    )
    record = json.loads(capsys.readouterr().out)

    assert code == 0
    assert record["dry_run"] is True
    item = record["items"][0]
    assert item["disposition"] == "ingested"
    assert item["actions"], "dry-run must carry the full action plan"
    assert _snapshot(source) == before_source
    assert _snapshot(library) == before_library


def test_executed_run_matches_the_emitted_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, library = _fixture(tmp_path)

    assert (
        cli.main(["--source", str(source), "--library-root", str(library), "--dry-run"])
        == 0
    )
    plan = json.loads(capsys.readouterr().out)["items"]

    assert cli.main(["--source", str(source), "--library-root", str(library)]) == 0
    executed = json.loads(capsys.readouterr().out)["items"]

    assert len(plan) == len(executed)
    for planned, actual in zip(plan, executed, strict=True):
        assert planned["name"] == actual["name"]
        assert planned["actions"] == actual["actions"]


def test_dry_run_over_already_handled_item_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, library = _fixture(tmp_path)
    # copy mode keeps the source, so the item is observed again on the rerun
    assert (
        cli.main(
            ["--source", str(source), "--library-root", str(library), "--mode", "copy"]
        )
        == 0
    )
    capsys.readouterr()

    before_library = _snapshot(library)
    assert (
        cli.main(["--source", str(source), "--library-root", str(library), "--dry-run"])
        == 0
    )
    record = json.loads(capsys.readouterr().out)
    assert record["items"][0]["disposition"] == "already_handled"
    assert _snapshot(library) == before_library
