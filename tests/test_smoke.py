"""Smoke test: the package imports and reports a version."""

import trovium


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(trovium.__version__, str)
    assert trovium.__version__
