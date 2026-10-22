"""Unit tests for trovium-ingest configuration fallbacks."""

from __future__ import annotations

from pathlib import Path

import pytest

from trovium.cli import MisuseError, build_parser, resolve_options


def _config(tmp_path: Path, *, source: str = "client") -> Path:
    path = tmp_path / "config.ini"
    body = (
        "[meta]\nschema_version = 1\n"
        f"[library]\nroot = {tmp_path / 'library'}\n"
        "[ingest]\ncategory = tv\nmode = copy\non_fail = stop\njson = compact\n"
    )
    if source == "client":
        body += (
            "[source]\nmode = client\nclient_url = http://127.0.0.1:8080\n"
            "client_username_env = CUSTOM_USER\n"
            "client_password_env = CUSTOM_PASSWORD\n"
        )
    elif source == "disk":
        body += f"[source]\nmode = disk\npath = {tmp_path / 'source'}\n"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture(autouse=True)
def _library_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "library").mkdir()
    (tmp_path / "source").mkdir()
    monkeypatch.delenv("TROVIUM_LIBRARY_ROOT", raising=False)
    monkeypatch.delenv("TROVIUM_SOURCE", raising=False)
    monkeypatch.delenv("TROVIUM_CLIENT_URL", raising=False)


def test_config_supplies_client_mode_and_enums(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--config", str(_config(tmp_path))])

    resolved = resolve_options(args)

    assert resolved.library_root == (tmp_path / "library").resolve()
    assert resolved.client_url == "http://127.0.0.1:8080"
    assert resolved.profile.name == "video"
    assert resolved.category == "tv"
    assert resolved.mode.value == "copy"
    assert resolved.on_fail.value == "stop"
    assert resolved.json_style.value == "compact"
    assert resolved.client_username_env == "CUSTOM_USER"
    assert resolved.client_password_env == "CUSTOM_PASSWORD"


def test_config_supplies_disk_source(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        ["--config", str(_config(tmp_path, source="disk"))]
    )

    resolved = resolve_options(args)

    assert resolved.source == (tmp_path / "source").resolve()
    assert resolved.client_url is None


def test_cli_overrides_config_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other-source"
    other.mkdir()
    monkeypatch.setenv("TROVIUM_SOURCE", str(tmp_path / "source"))
    args = build_parser().parse_args(
        [
            "--config",
            str(_config(tmp_path, source="disk")),
            "--source",
            str(other),
            "--mode",
            "move",
        ]
    )

    resolved = resolve_options(args)

    assert resolved.source == other.resolve()
    assert resolved.client_url is None
    assert resolved.mode.value == "move"


def test_environment_supplies_missing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROVIUM_SOURCE", str(tmp_path / "source"))
    args = build_parser().parse_args(["--config", str(_config(tmp_path))])

    resolved = resolve_options(args)

    assert resolved.source == (tmp_path / "source").resolve()


def test_missing_explicit_config_is_misuse(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--config", str(tmp_path / "absent.ini")])

    with pytest.raises(MisuseError):
        resolve_options(args)


def test_missing_library_root_is_misuse(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[meta]\nschema_version = 1\n"
        "[source]\nmode = client\nclient_url = http://127.0.0.1:8080\n",
        encoding="utf-8",
    )
    args = build_parser().parse_args(["--config", str(path)])

    with pytest.raises(MisuseError) as error:
        resolve_options(args)
    assert "TROVIUM_LIBRARY_ROOT" in str(error.value)
