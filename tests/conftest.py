"""Test isolation for trovium's XDG and deployment state."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_trovium_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TROVIUM_CONFIG_FILE", str(tmp_path / "config.ini"))
    monkeypatch.setenv("TROVIUM_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("TROVIUM_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("TROVIUM_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("TROVIUM_BIN_DIR", str(tmp_path / "bin"))
