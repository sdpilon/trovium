"""Integration: one-command install from a local bundle (US1, SC-001/SC-002)."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from tests.deploy_support import (
    Layout,
    deploy,
    install,
    report,
    run,
)


def _standard(layout: Layout) -> list[str]:
    return [
        "--library-root",
        str(layout.library),
        "--source",
        str(layout.source),
    ]


def test_install_creates_a_private_working_installation(
    layout: Layout, bundle: Path
) -> None:
    completed = install(layout, bundle, _standard(layout))

    payload = report(completed)
    assert completed.returncode == 0
    assert payload["status"] == "ok"
    assert payload["version"] == "0.1.0"
    assert payload["config_path"] == str(layout.config)
    assert payload["commands"] == [
        "trovium-deploy",
        "trovium-ingest",
        "trovium-rename",
    ]

    mode = stat.S_IMODE(layout.config.stat().st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(layout.config.parent.stat().st_mode) == 0o700
    text = layout.config.read_text(encoding="utf-8")
    assert f"root = {layout.library}" in text
    assert f"path = {layout.source}" in text
    assert "mode = disk" in text

    for command in ("trovium-ingest", "trovium-rename", "trovium-deploy"):
        executable = layout.bin / command
        assert executable.is_file()
        assert os.access(executable, os.X_OK)
        help_result = run(layout, [str(executable), "--help"])
        assert help_result.returncode == 0, help_result.stderr

    record = json.loads((layout.state / "trovium" / "deployment.json").read_text())
    assert record["version"] == "0.1.0"
    assert record["previous_version"] is None
    assert record["config_path"] == str(layout.config)
    assert record["tool_dir"].startswith(str(layout.data))
    assert record["bin_dir"] == str(layout.bin)
    assert record["last_self_check"]["status"] == "pass"
    assert record["last_operation"]["status"] == "ok"
    for key in ("tool_dir", "bin_dir", "config_path", "uv_path", "python_path"):
        assert Path(record[key]).is_absolute()
    assert record["commands"] == [
        "trovium-deploy",
        "trovium-ingest",
        "trovium-rename",
    ]

    for path in layout.root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert path.stat().st_uid == os.getuid()


def test_second_identical_install_is_a_noop(layout: Layout, bundle: Path) -> None:
    first = report(install(layout, bundle, _standard(layout)))
    assert first["status"] == "ok"
    config_before = layout.config.read_bytes()

    second = report(install(layout, bundle, _standard(layout)))

    assert second["status"] == "noop"
    assert second["operation"] == "install"
    assert second["actions"] == []
    assert second["previous_version"] == second["version"]
    assert layout.config.read_bytes() == config_before


def test_noop_surfaces_config_warnings(layout: Layout, bundle: Path) -> None:
    report(install(layout, bundle, _standard(layout)))
    shutil.rmtree(layout.source)

    repeated = report(install(layout, bundle, _standard(layout)))

    assert repeated["status"] == "degraded"
    assert repeated["actions"] == []
    source_check = next(
        check for check in repeated["checks"] if check["name"] == "source_path"
    )
    assert source_check["status"] == "warn"


def test_reinstall_warns_when_supplied_paths_are_ignored(
    layout: Layout, bundle: Path
) -> None:
    first = report(install(layout, bundle, _standard(layout)))
    assert first["status"] == "ok"
    other_library = layout.root / "other-library"
    other_library.mkdir()

    repeated = report(
        install(
            layout,
            bundle,
            ["--library-root", str(other_library), "--source", str(layout.source)],
        )
    )

    assert repeated["status"] == "degraded"
    config_check = next(
        check for check in repeated["checks"] if check["name"] == "config"
    )
    assert config_check["status"] == "warn"
    assert str(other_library) in config_check["detail"]
    assert "not applied" in config_check["detail"]
    assert f"root = {layout.library}" in layout.config.read_text(encoding="utf-8")


def test_missing_command_triggers_repair_not_noop(layout: Layout, bundle: Path) -> None:
    report(install(layout, bundle, _standard(layout)))
    (layout.bin / "trovium-ingest").unlink()

    repaired = report(install(layout, bundle, _standard(layout)))

    assert repaired["status"] == "ok"
    assert repaired["actions"], "a repair must report the actions it took"
    assert (layout.bin / "trovium-ingest").is_file()


def test_install_refuses_a_pre_313_interpreter(
    layout: Layout, bundle: Path, tmp_path: Path
) -> None:
    older = tmp_path / "python-old"
    older.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then\n'
        "    printf '3.12\\n'\n"
        "    exit 0\n"
        "fi\n"
        'exec python3 "$@"\n',
        encoding="utf-8",
    )
    older.chmod(0o755)

    completed = install(
        layout,
        bundle,
        _standard(layout),
        env={"TROVIUM_TEST_PYTHON": str(older)},
    )

    payload = report(completed)
    assert completed.returncode == 3
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "missing_prerequisite"
    assert "3.13 or newer" in payload["error"]["message"]
    assert not layout.config.exists()
    assert not (layout.bin / "trovium-ingest").exists()


def _shim_path(
    tmp_path: Path,
    *,
    missing: set[str] | None = None,
    uname: str | None = None,
) -> str:
    """Build a PATH that contains the bootstrap's tools minus ``missing``."""

    skipped = missing or set()
    shim = tmp_path / "shim"
    shim.mkdir()
    tools = (
        "bash",
        "date",
        "sed",
        "tr",
        "mktemp",
        "find",
        "awk",
        "tar",
        "shasum",
        "sha256sum",
        "curl",
        "uname",
        "dirname",
        "head",
        "cp",
        "rm",
        "mkdir",
    )
    for name in tools:
        if name in skipped:
            continue
        found = shutil.which(name)
        if found is not None:
            (shim / name).symlink_to(found)
    if uname is not None:
        system, machine = uname.split()
        (shim / "uname").unlink(missing_ok=True)
        (shim / "uname").write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            f"  -s) echo {system} ;;\n"
            f"  *) echo {machine} ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        (shim / "uname").chmod(0o755)
    return str(shim)


@pytest.mark.parametrize(
    "case",
    ["disk_source", "client_source", "config_file", "offline_bundle", "second_home"],
)
def test_sc002_matrix_positive_cases(
    layout: Layout, bundle: Path, tmp_path: Path, case: str
) -> None:
    """Five clean positive cases must install and pass their self-check."""

    supplied = tmp_path / "supplied.ini"
    supplied.write_text(
        f"[meta]\nschema_version = 1\n[library]\nroot = {layout.library}\n",
        encoding="utf-8",
    )
    supplied.chmod(0o600)
    args: list[str]
    environment: dict[str, str] = {}
    if case == "disk_source":
        args = _standard(layout)
    elif case == "client_source":
        args = [
            "--library-root",
            str(layout.library),
            "--client-url",
            "http://127.0.0.1:8080",
        ]
    elif case == "config_file":
        args = ["--config", str(supplied)]
    elif case == "offline_bundle":
        args = _standard(layout)
        environment = {
            "UV_OFFLINE": "1",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
        }
    else:
        args = _standard(layout)

    completed = install(layout, bundle, args, env=environment)

    payload = report(completed)
    assert completed.returncode == 0, payload
    assert payload["status"] in {"ok", "degraded"}
    status = deploy(layout, "status", "--json", "compact")
    assert status.returncode == 0
    status_payload = json.loads(status.stdout)
    assert status_payload["version"] == "0.1.0"
    assert any(
        check["name"] == "self_check" and check["status"] == "pass"
        for check in status_payload["checks"]
    )


@pytest.mark.parametrize(
    ("case", "uname"),
    [
        pytest.param("unsupported_platform", "plan9 mips", id="unsupported_platform"),
        pytest.param("missing_prerequisite", None, id="missing_prerequisite"),
    ],
)
def test_sc002_matrix_negative_cases(
    layout: Layout,
    bundle: Path,
    tmp_path: Path,
    case: str,
    uname: str | None,
) -> None:
    """Negative preflight cases refuse before changing anything."""

    if case == "unsupported_platform":
        shim = _shim_path(tmp_path, uname=uname)
    else:
        shim = _shim_path(tmp_path, missing={"tar"})
    completed = install(layout, bundle, _standard(layout), env={"PATH": shim})

    payload = report(completed)
    assert completed.returncode == 3, payload
    assert payload["status"] == "error"
    assert payload["error"]["code"] in {
        "unsupported_platform",
        "missing_prerequisite",
    }
    assert payload["error"]["remedy"]
    assert not layout.config.exists()
    assert not (layout.bin / "trovium-ingest").exists()


def test_installation_is_user_scoped_and_reports_the_path_remedy(
    layout: Layout, bundle: Path
) -> None:
    report(install(layout, bundle, _standard(layout)))
    record = json.loads((layout.state / "trovium" / "deployment.json").read_text())

    for key in ("config_path", "tool_dir", "bin_dir"):
        assert Path(record[key]).is_relative_to(layout.root)
    assert not list(layout.data.rglob("*.service")), "no service unit may be created"
    assert not list(layout.data.rglob("*.timer"))

    status = deploy(
        layout, "status", "--json", "compact", env={"PATH": "/usr/bin:/bin"}
    )
    payload = json.loads(status.stdout)
    path_check = next(
        check for check in payload["checks"] if check["name"] == "command_path"
    )
    assert path_check["status"] == "warn"
    assert str(layout.bin) in path_check["remedy"]
    assert "shell profile" in path_check["remedy"]
