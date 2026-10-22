"""Unit tests for the shared INI configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from trovium.config import (
    ConfigError,
    IngestSettings,
    config_path,
    copy_config,
    load_config,
    migrate_config,
    parse_config,
    write_default_config,
)
from trovium.record import Mode


def test_write_load_and_permissions(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    library = tmp_path / "library"
    library.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    write_default_config(
        path,
        library_root=library,
        source_mode="disk",
        source_path=source,
        ingest=IngestSettings(category="tv", mode=Mode.COPY),
    )
    loaded = load_config(path, required=True)
    assert loaded is not None
    assert loaded.config.library_root == library
    assert loaded.config.source.mode == "disk"
    assert loaded.config.source.path == source
    assert loaded.config.ingest.profile == "video"
    assert loaded.config.ingest.category == "tv"
    assert loaded.config.ingest.mode is Mode.COPY
    assert path.stat().st_mode & 0o777 == 0o600


def test_existing_config_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    library = tmp_path / "library"
    library.mkdir()
    write_default_config(path, library_root=library)
    with pytest.raises(ConfigError):
        write_default_config(path, library_root=library)


def test_userinfo_in_client_url_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[meta]\nschema_version = 1\n[library]\nroot = /tmp\n"
        "[source]\nmode = client\nclient_url = http://user:pass@example.test\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        parse_config(path)


def test_missing_client_url_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[meta]\nschema_version = 1\n[library]\nroot = /tmp\n[source]\nmode = client\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        parse_config(path)


def test_explicit_missing_config_is_required(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.ini", required=True)


def test_migration_creates_private_backup(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text("[library]\nroot = /tmp\n", encoding="utf-8")
    path.chmod(0o600)
    backup = migrate_config(path)
    assert backup is not None
    assert backup.exists()
    assert backup.stat().st_mode & 0o777 == 0o600
    loaded = load_config(path, required=True)
    assert loaded is not None
    assert loaded.config.schema_version == 1


def test_copy_config_preserves_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.ini"
    destination = tmp_path / "destination.ini"
    source.write_text("[meta]\nschema_version = 1\n[library]\nroot = /tmp\n")
    assert copy_config(source, destination) is True
    assert destination.stat().st_mode & 0o777 == 0o600
    destination.write_text("[meta]\nschema_version = 1\n[library]\nroot = /other\n")
    assert copy_config(source, destination) is False
    assert "other" in destination.read_text()


def test_config_path_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    explicit = tmp_path / "explicit.ini"
    monkeypatch.setenv("TROVIUM_CONFIG_FILE", str(explicit))
    assert config_path() == explicit
    assert config_path(tmp_path / "other.ini") == tmp_path / "other.ini"
    assert os.access(tmp_path, os.W_OK)
