"""Fixtures for the deployment integration tests.

Bundles are built once per version and platform and cached outside the
repository, so a full run does not rebuild them for every test. Installations
always go through the shipped ``install.sh`` in an isolated XDG tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.deploy_support import (
    Layout,
    build_broken_bundle,
    build_bundle,
    make_layout,
)


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Layout:
    tree = make_layout(tmp_path)
    for name, value in tree.environment.items():
        monkeypatch.setenv(name, value)
    return tree


@pytest.fixture(scope="session")
def bundle() -> Path:
    return build_bundle("0.1.0")


@pytest.fixture(scope="session")
def newer_bundle() -> Path:
    return build_bundle("0.2.0")


@pytest.fixture(scope="session")
def broken_bundle() -> Path:
    return build_broken_bundle()
