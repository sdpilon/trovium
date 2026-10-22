"""Tests for generated install configuration."""

from __future__ import annotations

from pathlib import Path

from trovium.config import IngestSettings, load_config, write_default_config
from trovium.record import JsonStyle, Mode, OnFail, PostIngest


def test_generated_config_has_documented_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    library = tmp_path / "library"
    library.mkdir()
    write_default_config(
        path,
        library_root=library,
        source_mode="disk",
        source_path=tmp_path,
        ingest=IngestSettings(),
    )
    loaded = load_config(path, required=True)
    assert loaded is not None
    assert loaded.config.library_root == library
    assert loaded.config.source.mode == "disk"
    assert loaded.config.ingest.profile == "video"
    assert loaded.config.ingest.category == "all"
    assert loaded.config.ingest.mode is Mode.MOVE
    assert loaded.config.ingest.post_ingest is PostIngest.KEEP
    assert loaded.config.ingest.on_fail is OnFail.CONTINUE
    assert loaded.config.ingest.json is JsonStyle.PRETTY
    assert "schema_version = 1" in path.read_text()
