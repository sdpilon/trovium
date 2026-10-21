"""Contract tests for ingest config fallbacks and precedence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trovium import cli


def _tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    library = tmp_path / "library"
    source = tmp_path / "source"
    library.mkdir()
    release = source / "Movie.Production.2024.1080p-GRP"
    release.mkdir(parents=True)
    (release / "Movie.Production.2024.1080p-GRP.mkv").write_bytes(b"payload")
    config = tmp_path / "config.ini"
    config.write_text(
        "[meta]\nschema_version = 1\n"
        f"[library]\nroot = {library}\n"
        f"[source]\nmode = disk\npath = {source}\n"
        "[ingest]\nmode = copy\ncategory = movie\njson = compact\n",
        encoding="utf-8",
    )
    return config, library, source


def test_ingest_uses_config_defaults(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _library, _source = _tree(tmp_path)
    code = cli.main(["--config", str(config), "--dry-run"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["declared"]["mode"] == "copy"
    assert payload["declared"]["category"] == "movie"
    assert payload["source"] == "disk"


def test_cli_overrides_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _library, _source = _tree(tmp_path)
    code = cli.main(["--config", str(config), "--mode", "move", "--dry-run"])
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["declared"]["mode"] == "move"


def test_missing_explicit_config_is_misuse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _config, library, source = _tree(tmp_path)
    code = cli.main(
        [
            "--config",
            str(tmp_path / "missing.ini"),
            "--library-root",
            str(library),
            "--source",
            str(source),
        ]
    )
    captured = capsys.readouterr()
    assert code == cli.EXIT_MISUSE
    assert captured.out == ""
    assert "does not exist" in captured.err
