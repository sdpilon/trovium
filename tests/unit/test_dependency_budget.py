"""Guard test: the runtime dependency budget is exactly one package (D8)."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_runtime_dependencies_are_exactly_httpx() -> None:
    with PYPROJECT.open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["dependencies"] == ["httpx>=0.27"]


def test_console_script_is_registered() -> None:
    with PYPROJECT.open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["scripts"]["trovium-ingest"] == "trovium.cli:main"
