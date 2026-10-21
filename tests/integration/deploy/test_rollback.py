"""Integration: rollback and interrupted-install recovery (US3, SC-006)."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest

from tests.deploy_support import (
    Layout,
    deploy,
    install,
    report,
    run,
)
from trovium.deploy import installer
from trovium.deploy import uv as uv_module
from trovium.deploy.installer import InstallOptions
from trovium.deploy.report import ActionOutcome, DeployError, now
from trovium.deploy.state import CommandCheck, SelfCheckResult


def _standard(layout: Layout) -> list[str]:
    return [
        "--library-root",
        str(layout.library),
        "--source",
        str(layout.source),
    ]


def _extract(bundle: Path, destination: Path) -> Path:
    destination.mkdir(parents=True)
    with tarfile.open(bundle) as archive:
        archive.extractall(destination, filter="data")
    roots = [path for path in destination.iterdir() if path.is_dir()]
    assert len(roots) == 1
    return roots[0]


def _python() -> Path:
    found = shutil.which("python3.13") or shutil.which("python3")
    assert found is not None
    return Path(found)


def _passing() -> SelfCheckResult:
    return SelfCheckResult(
        status="pass",
        checked_at=now(),
        commands=(CommandCheck(name="trovium-ingest", status="pass", exit_code=0),),
        duration_ms=1,
    )


def _failing() -> SelfCheckResult:
    return SelfCheckResult(
        status="fail",
        checked_at=now(),
        commands=(
            CommandCheck(
                name="trovium-ingest",
                status="fail",
                exit_code=3,
                detail="--help exited 3",
            ),
        ),
        duration_ms=1,
    )


def _direct_install(layout: Layout, bundle: Path) -> None:
    installer.install(
        InstallOptions(
            bundle=bundle,
            non_interactive=True,
            library_root=layout.library,
            source=layout.source,
            uv_override=Path(shutil.which("uv") or "uv"),
            python_override=_python(),
        )
    )


def _installed_version(layout: Layout) -> str:
    matches = list(layout.data.rglob("trovium-*.dist-info"))
    assert len(matches) == 1, matches
    return matches[0].name.removesuffix(".dist-info").split("-", 1)[1]


def test_cache_failure_happens_before_promotion(
    layout: Layout, bundle: Path, tmp_path: Path
) -> None:
    extracted = _extract(bundle, tmp_path / "bundle")
    (layout.state / "trovium").mkdir(parents=True)
    (layout.state / "trovium" / "cache").write_text("blocked", encoding="utf-8")

    with pytest.raises(DeployError) as failure:
        _direct_install(layout, extracted)

    assert failure.value.code == "unwritable_path"
    assert not (layout.bin / "trovium-ingest").exists()
    assert not (layout.state / "trovium" / "deployment.json").exists()

    (layout.state / "trovium" / "cache").unlink()
    _direct_install(layout, extracted)
    assert _installed_version(layout) == "0.1.0"


def test_first_install_record_failure_removes_the_environment(
    layout: Layout, bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extracted = _extract(bundle, tmp_path / "bundle")

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise DeployError(
            "unwritable_path", "injected record failure", "Retry when fixed."
        )

    with monkeypatch.context() as patch:
        patch.setattr(installer, "write_record", _fail)
        with pytest.raises(DeployError) as failure:
            _direct_install(layout, extracted)

    assert failure.value.code == "unwritable_path"
    assert not (layout.bin / "trovium-ingest").exists()
    assert not (layout.state / "trovium" / "deployment.json").exists()
    assert not (layout.data / "trovium" / "tools" / "trovium").exists()
    partial = failure.value.report
    assert partial is not None
    actions = {action.action: action for action in partial.actions}
    assert actions["write_record"].outcome is ActionOutcome.FAILED
    assert actions["uv_uninstall"].outcome is ActionOutcome.OK

    _direct_install(layout, extracted)
    assert _installed_version(layout) == "0.1.0"


def test_first_install_self_check_failure_removes_the_environment(
    layout: Layout, bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extracted = _extract(bundle, tmp_path / "bundle")
    calls = {"count": 0}

    def _staged_pass_active_fail(
        bin_dir: Path, commands: tuple[str, ...]
    ) -> SelfCheckResult:
        calls["count"] += 1
        return _passing() if calls["count"] == 1 else _failing()

    with monkeypatch.context() as patch:
        patch.setattr(installer, "run_selfcheck", _staged_pass_active_fail)
        with pytest.raises(DeployError) as failure:
            _direct_install(layout, extracted)

    assert failure.value.code == "self_check_failed"
    assert not (layout.bin / "trovium-ingest").exists()
    assert not (layout.state / "trovium" / "deployment.json").exists()
    assert not (layout.data / "trovium" / "tools" / "trovium").exists()
    partial = failure.value.report
    assert partial is not None
    actions = {action.action: action for action in partial.actions}
    assert actions["uv_uninstall"].outcome is ActionOutcome.OK

    _direct_install(layout, extracted)
    assert _installed_version(layout) == "0.1.0"


def test_failed_upgrade_keeps_the_previous_version(
    layout: Layout, bundle: Path, newer_bundle: Path, broken_bundle: Path
) -> None:
    report(install(layout, newer_bundle, _standard(layout)))

    completed = install(layout, broken_bundle, _standard(layout))

    payload = report(completed)
    assert completed.returncode == 5
    assert payload["error"]["code"] == "self_check_failed"
    status = json.loads(deploy(layout, "status", "--json", "compact").stdout)
    assert status["version"] == "0.2.0"
    help_result = run(layout, [str(layout.bin / "trovium-ingest"), "--help"])
    assert help_result.returncode == 0


def test_active_self_check_failure_restores_the_cached_previous_version(
    layout: Layout,
    bundle: Path,
    newer_bundle: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report(install(layout, bundle, _standard(layout)))
    extracted = _extract(newer_bundle, tmp_path / "newer")
    calls = {"count": 0}

    def _staged_pass_active_fail(
        bin_dir: Path, commands: tuple[str, ...]
    ) -> SelfCheckResult:
        calls["count"] += 1
        return _passing() if calls["count"] == 1 else _failing()

    monkeypatch.setattr(installer, "run_selfcheck", _staged_pass_active_fail)

    with pytest.raises(DeployError) as failure:
        _direct_install(layout, extracted)

    assert failure.value.code == "self_check_failed", failure.value.message
    partial = failure.value.report
    assert partial is not None
    actions = {action.action: action for action in partial.actions}
    assert actions["rollback"].outcome is ActionOutcome.OK
    assert calls["count"] == 2
    record = json.loads((layout.state / "trovium" / "deployment.json").read_text())
    assert record["version"] == "0.1.0"
    status = json.loads(deploy(layout, "status", "--json", "compact").stdout)
    assert status["version"] == "0.1.0"
    help_result = run(layout, [str(layout.bin / "trovium-ingest"), "--help"])
    assert help_result.returncode == 0


INTERRUPTIONS = [
    "before_toolchain_copy",
    "before_staging_install",
    "before_staged_self_check",
    "before_promotion",
    "before_record_write",
]


def _interrupt(monkeypatch: pytest.MonkeyPatch, point: str) -> None:
    if point == "before_toolchain_copy":
        monkeypatch.setattr(
            installer,
            "_prepare_toolchain",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                DeployError("install_failed", "injected interruption", "Retry.")
            ),
        )
    elif point == "before_staging_install":
        monkeypatch.setattr(
            uv_module,
            "tool_install",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                DeployError("install_failed", "injected interruption", "Retry.")
            ),
        )
    elif point == "before_staged_self_check":
        monkeypatch.setattr(
            installer,
            "run_selfcheck",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                DeployError("install_failed", "injected interruption", "Retry.")
            ),
        )
    elif point == "before_promotion":
        calls = {"count": 0}
        original = uv_module.tool_install

        def _fail_on_promotion(
            uv_path: Path,
            *,
            python_path: Path,
            wheelhouse: Path,
            tool_dir: Path,
            bin_dir: Path,
            wheel: Path,
            force: bool = True,
        ) -> None:
            calls["count"] += 1
            if calls["count"] == 2:
                raise DeployError("install_failed", "injected interruption", "Retry.")
            original(
                uv_path,
                python_path=python_path,
                wheelhouse=wheelhouse,
                tool_dir=tool_dir,
                bin_dir=bin_dir,
                wheel=wheel,
                force=force,
            )

        monkeypatch.setattr(uv_module, "tool_install", _fail_on_promotion)
    else:
        monkeypatch.setattr(
            installer,
            "write_record",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                DeployError("install_failed", "injected interruption", "Retry.")
            ),
        )


@pytest.mark.parametrize("point", INTERRUPTIONS)
def test_recovery_after_interruption_converges_on_rerun(
    layout: Layout,
    bundle: Path,
    newer_bundle: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    report(install(layout, bundle, _standard(layout)))
    extracted = _extract(newer_bundle, tmp_path / "newer")
    _interrupt(monkeypatch, point)

    with pytest.raises(DeployError) as failure:
        _direct_install(layout, extracted)

    record_after_failure = json.loads(
        (layout.state / "trovium" / "deployment.json").read_text()
    )
    assert record_after_failure["version"] == "0.1.0"
    if point == "before_record_write":
        partial = failure.value.report
        assert partial is not None
        actions = {action.action: action for action in partial.actions}
        assert actions["write_record"].outcome is ActionOutcome.FAILED
        assert actions["rollback"].outcome is ActionOutcome.OK
        assert _installed_version(layout) == "0.1.0"

    recovered = report(install(layout, newer_bundle, _standard(layout)))
    assert recovered["version"] == "0.2.0"
    record = json.loads((layout.state / "trovium" / "deployment.json").read_text())
    assert record["version"] == "0.2.0"
    assert record["last_operation"]["status"] == "ok"
    help_result = run(layout, [str(layout.bin / "trovium-ingest"), "--help"])
    assert help_result.returncode == 0
    assert os.access(layout.bin / "trovium-deploy", os.X_OK)
