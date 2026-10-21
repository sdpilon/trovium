"""Contract: concurrent deployment operations are serialized or refused."""

from __future__ import annotations

import fcntl
from pathlib import Path

from tests.deploy_support import Layout, install, make_layout, report, run


def _standard(layout: Layout) -> list[str]:
    return ["--library-root", str(layout.library), "--source", str(layout.source)]


def test_held_lock_refuses_with_exit_6(layout: Layout, bundle: Path) -> None:
    lock = layout.state / "trovium" / "deploy.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = install(layout, bundle, _standard(layout))
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    payload = report(completed)
    assert completed.returncode == 6
    assert payload["error"]["code"] == "lock_held"
    assert not layout.config.exists()
    assert not (layout.bin / "trovium-ingest").exists()


def test_distinct_user_roots_use_separate_locks(
    layout: Layout, bundle: Path, tmp_path: Path
) -> None:
    lock = layout.state / "trovium" / "deploy.lock"
    lock.parent.mkdir(parents=True)
    second = make_layout(tmp_path / "second")
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = install(second, bundle, _standard(second))
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    payload = report(completed)
    assert completed.returncode == 0, payload
    assert payload["status"] in {"ok", "degraded"}
    assert (second.bin / "trovium-ingest").is_file()


def test_status_does_not_take_the_deployment_lock(layout: Layout, bundle: Path) -> None:
    report(install(layout, bundle, _standard(layout)))
    lock = layout.state / "trovium" / "deploy.lock"
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = run(
            layout, [str(layout.bin / "trovium-deploy"), "status", "--json", "compact"]
        )
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    assert completed.returncode == 0
