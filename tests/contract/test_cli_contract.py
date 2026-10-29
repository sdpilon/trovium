"""Contract tests: CLI misuse refusals, exit codes, and record shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trovium import cli


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        cli.CLIENT_URL_ENV,
        cli.CLIENT_USERNAME_ENV,
        cli.CLIENT_PASSWORD_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def _library(tmp_path: Path) -> Path:
    library = tmp_path / "library"
    library.mkdir()
    return library


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    release = source / "Movie.Production.2024.1080p-iGor"
    release.mkdir()
    (release / "Movie.Production.2024.1080p-iGor.mkv").write_bytes(b"payload")
    return source


def test_source_with_client_url_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "--source",
            str(_source(tmp_path)),
            "--client-url",
            "http://127.0.0.1:8080",
            "--library-root",
            str(_library(tmp_path)),
        ]
    )
    captured = capsys.readouterr()
    assert code == cli.EXIT_MISUSE
    assert captured.out == ""
    assert "--client-url" in captured.err


def test_source_with_post_ingest_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "--source",
            str(_source(tmp_path)),
            "--post-ingest",
            "delete",
            "--library-root",
            str(_library(tmp_path)),
        ]
    )
    captured = capsys.readouterr()
    assert code == cli.EXIT_MISUSE
    assert captured.out == ""
    assert "--post-ingest" in captured.err


def test_source_with_explicit_post_ingest_keep_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "--source",
            str(_source(tmp_path)),
            "--post-ingest",
            "keep",
            "--library-root",
            str(_library(tmp_path)),
        ]
    )
    captured = capsys.readouterr()
    assert code == cli.EXIT_MISUSE
    assert captured.out == ""
    assert "--post-ingest" in captured.err


def test_no_source_declared_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["--library-root", str(_library(tmp_path))])
    captured = capsys.readouterr()
    assert code == cli.EXIT_MISUSE
    assert cli.CLIENT_URL_ENV in captured.err


def test_missing_source_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "--source",
            str(tmp_path / "nope"),
            "--library-root",
            str(_library(tmp_path)),
        ]
    )
    assert code == cli.EXIT_MISUSE
    assert "does not exist" in capsys.readouterr().err


def test_source_that_is_not_a_directory_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    code = cli.main(
        ["--source", str(a_file), "--library-root", str(_library(tmp_path))]
    )
    assert code == cli.EXIT_MISUSE
    assert "not a directory" in capsys.readouterr().err


@pytest.mark.skipif(
    __import__("os").geteuid() == 0, reason="root ignores permission bits"
)
def test_unreadable_source_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path)
    source.chmod(0o000)
    try:
        code = cli.main(
            ["--source", str(source), "--library-root", str(_library(tmp_path))]
        )
    finally:
        source.chmod(0o755)
    assert code == cli.EXIT_MISUSE
    assert "not readable" in capsys.readouterr().err


def test_missing_library_root_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        ["--source", str(_source(tmp_path)), "--library-root", str(tmp_path / "none")]
    )
    assert code == cli.EXIT_MISUSE
    assert "--library-root" in capsys.readouterr().err


def test_compact_and_pretty_emit_the_same_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path)
    library = _library(tmp_path)

    # inspect-only runs make no changes, so both formats see identical state
    assert (
        cli.main(["--source", str(source), "--library-root", str(library), "--dry-run"])
        == 0
    )
    pretty = capsys.readouterr().out
    assert (
        cli.main(
            [
                "--source",
                str(source),
                "--library-root",
                str(library),
                "--dry-run",
                "--json",
                "compact",
            ]
        )
        == 0
    )
    compact = capsys.readouterr().out

    assert json.loads(pretty) == json.loads(compact)
    assert pretty.count("\n") > 1


def test_record_shape_and_counts_reconcile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        cli.main(
            [
                "--source",
                str(_source(tmp_path)),
                "--library-root",
                str(_library(tmp_path)),
            ]
        )
        == 0
    )
    record = json.loads(capsys.readouterr().out)

    assert record["source"] == "disk"
    assert record["dry_run"] is False
    assert record["declared"]["library_root"].endswith("library")
    assert record["declared"]["post_ingest"] is None
    assert record["declared"]["mode"] == "auto"
    assert record["declared"]["category"] == "all"
    assert record["counts"]["total"] == len(record["items"])
    assert (
        sum(record["counts"][key] for key in record["counts"] if key != "total")
        == record["counts"]["total"]
    )


def test_no_credentials_or_env_values_in_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.CLIENT_PASSWORD_ENV, "sup3r-s3cret")
    assert (
        cli.main(
            [
                "--source",
                str(_source(tmp_path)),
                "--library-root",
                str(_library(tmp_path)),
            ]
        )
        == 0
    )
    assert "sup3r-s3cret" not in capsys.readouterr().out


def test_relative_library_root_is_recorded_as_absolute(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "source" / "Movie.Production.2024.1080p-iGor").mkdir(parents=True)
    (
        tmp_path
        / "source"
        / "Movie.Production.2024.1080p-iGor"
        / "Movie.Production.2024.1080p-iGor.mkv"
    ).write_bytes(b"payload")
    (tmp_path / "library").mkdir()

    code = cli.main(["--source", "source", "--library-root", "library", "--dry-run"])
    record = json.loads(capsys.readouterr().out)

    assert code == 0
    assert Path(record["declared"]["library_root"]).is_absolute()
    item = record["items"][0]
    assert Path(item["destination"]).is_absolute()
    assert Path(item["actions"][0]["to"]).is_absolute()
