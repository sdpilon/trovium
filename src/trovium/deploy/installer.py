"""Install, check, status, and uninstall orchestration."""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from trovium.config import (
    ConfigError,
    IngestSettings,
    TroviumConfig,
    config_path,
    copy_config,
    load_config,
    migrate_config,
    tighten_permissions,
    write_default_config,
)
from trovium.deploy import bundle as bundle_module
from trovium.deploy import paths
from trovium.deploy import uv as uv_module
from trovium.deploy.report import (
    Action,
    ActionOutcome,
    Check,
    CheckStatus,
    DeployError,
    Operation,
    Report,
    ReportStatus,
    now,
    register_secrets,
    status_for,
)
from trovium.deploy.selfcheck import run_selfcheck
from trovium.deploy.state import (
    DeploymentRecord,
    LastOperation,
    acquire_lock,
    read_record,
    write_record,
)
from trovium.record import JsonStyle

LIBRARY_ROOT_ENV = "TROVIUM_LIBRARY_ROOT"
SOURCE_ENV = "TROVIUM_SOURCE"
CLIENT_URL_ENV = "TROVIUM_CLIENT_URL"


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


@dataclass(frozen=True)
class InstallOptions:
    """Inputs to an install or upgrade."""

    bundle: Path
    non_interactive: bool = False
    library_root: Path | None = None
    source: Path | None = None
    client_url: str | None = None
    config: Path | None = None
    force: bool = False
    json_style: JsonStyle = JsonStyle.PRETTY
    uv_override: Path | None = None
    python_override: Path | None = None


def _commands_executable(bin_dir: Path, commands: tuple[str, ...]) -> bool:
    return all(
        (bin_dir / command).is_file() and os.access(bin_dir / command, os.X_OK)
        for command in commands
    )


def _running_from_active_tool_dir() -> bool:
    """True when this process executes from the recorded tool environment."""

    record = read_record()
    if record is None:
        return False
    active = Path(record.tool_dir)
    for candidate in (Path(sys.executable), Path(sys.argv[0])):
        try:
            resolved = candidate.resolve()
            resolved.relative_to(active.resolve())
        except (OSError, ValueError):
            continue
        return True
    return False


def _check_path(
    name: str,
    path: Path | None,
    *,
    kind: str,
    writable: bool = False,
) -> Check:
    if path is None:
        return Check(
            name=name, status=CheckStatus.WARN, detail=f"{kind} is not configured"
        )
    if not path.exists():
        return Check(
            name=name,
            status=CheckStatus.WARN,
            detail=f"{path} does not exist",
            remedy=f"Mount or create {path} before the next pipeline run.",
        )
    if writable and not os.access(path, os.W_OK | os.X_OK):
        return Check(
            name=name,
            status=CheckStatus.FAIL,
            detail=f"{path} is not writable",
            remedy="Fix the directory permissions and retry.",
        )
    return Check(name=name, status=CheckStatus.PASS, detail=f"{path} is present")


def _config_checks(config: TroviumConfig) -> list[Check]:
    checks = [
        _check_path("library_path", config.library_root, kind="library", writable=True)
    ]
    checks.append(_check_path("source_path", config.source.path, kind="source path"))
    checks.append(
        Check(
            name="source_configured",
            status=CheckStatus.PASS if config.source.mode else CheckStatus.WARN,
            detail=f"source mode: {config.source.mode}"
            if config.source.mode
            else "source is not configured",
            remedy=None if config.source.mode else "Set [source] mode in the config.",
        )
    )
    if config.source.mode == "client":
        username = os.environ.get(config.source.client_username_env)
        password = os.environ.get(config.source.client_password_env)
        # Only the password is a secret: registering the username redacts any
        # path that happens to contain it (e.g. an "admin" account).
        register_secrets((password,))
        missing = [
            name
            for name, value in (
                (config.source.client_username_env, username),
                (config.source.client_password_env, password),
            )
            if not value
        ]
        checks.append(
            Check(
                name="credentials",
                status=CheckStatus.WARN if missing else CheckStatus.PASS,
                detail=(
                    f"missing environment variables: {', '.join(missing)}"
                    if missing
                    else "credential variables are set"
                ),
                remedy=(
                    "Export the named credential variables before the first client run."
                    if missing
                    else None
                ),
            )
        )
    return checks


def _report_status(checks: list[Check]) -> ReportStatus:
    return status_for(checks)


def _resolve_install_config(
    opts: InstallOptions,
) -> tuple[TroviumConfig, list[str], list[Action]]:
    try:
        return _resolve_install_config_inner(opts)
    except ConfigError as error:
        raise DeployError(
            "config_invalid",
            str(error),
            "Fix the configuration file and retry.",
            exit_code=7,
        ) from error


def _ignored_supplied_warnings(
    opts: InstallOptions, config: TroviumConfig
) -> list[str]:
    """Name supplied values a reinstall keeps from the existing config (FR-022)."""

    warnings: list[str] = []
    supplied = (
        ("library root", opts.library_root, config.library_root),
        ("source path", opts.source, config.source.path),
        ("client URL", opts.client_url, config.source.client_url),
    )
    for label, requested, current in supplied:
        if requested is not None and requested != current:
            warnings.append(
                f"existing config retained; supplied {label} not applied: {requested}"
            )
    return warnings


def _resolve_install_config_inner(
    opts: InstallOptions,
) -> tuple[TroviumConfig, list[str], list[Action]]:
    target = config_path()
    warnings: list[str] = []
    actions: list[Action] = []
    if opts.config is not None and opts.config.resolve() != target.resolve():
        if not opts.config.exists():
            raise ConfigError(f"supplied config does not exist: {opts.config}")
        if not target.exists():
            copy_config(opts.config, target)
            actions.append(
                Action(
                    action="write_config",
                    target=str(target),
                    outcome=ActionOutcome.OK,
                    detail="copied supplied config",
                )
            )
        else:
            warnings.append(
                f"existing config retained; supplied config not applied: {opts.config}"
            )
    if target.exists():
        backup = migrate_config(target)
        if backup is not None:
            actions.append(
                Action(
                    action="write_config",
                    target=str(target),
                    outcome=ActionOutcome.OK,
                    detail=f"migrated config; backup: {backup.name}",
                )
            )
        if tighten_permissions(target):
            actions.append(
                Action(
                    action="write_config",
                    target=str(target),
                    outcome=ActionOutcome.OK,
                    detail="tightened permissions to 0600",
                )
            )
        loaded = load_config(target, required=True)
        assert loaded is not None
        warnings.extend(loaded.warnings)
        warnings.extend(_ignored_supplied_warnings(opts, loaded.config))
        return loaded.config, warnings, actions
    if opts.source is not None and opts.client_url is not None:
        raise DeployError(
            "misuse",
            "--source cannot be combined with --client-url",
            "Choose one source and retry.",
            exit_code=2,
        )
    source = opts.source if opts.source is not None else _env_path(SOURCE_ENV)
    client_url = (
        opts.client_url if opts.client_url is not None else _env_value(CLIENT_URL_ENV)
    )
    if source is not None and client_url is not None:
        raise DeployError(
            "misuse",
            "--source cannot be combined with --client-url",
            f"Unset {SOURCE_ENV} or {CLIENT_URL_ENV} and retry.",
            exit_code=2,
        )
    root = (
        opts.library_root
        if opts.library_root is not None
        else _env_path(LIBRARY_ROOT_ENV)
    )
    if root is None:
        if opts.non_interactive:
            raise DeployError(
                "misuse",
                "missing required input: library root",
                "Pass --library-root, set TROVIUM_LIBRARY_ROOT, or supply --config.",
                exit_code=2,
            )
        root = Path(paths.prompt("Library root")).expanduser()
    if source is not None:
        mode = "disk"
    elif client_url is not None:
        mode = "client"
    else:
        mode = None
    write_default_config(
        target,
        library_root=root,
        source_mode=mode,
        source_path=source,
        client_url=client_url,
        ingest=IngestSettings(),
    )
    actions.append(
        Action(
            action="write_config",
            target=str(target),
            outcome=ActionOutcome.OK,
            detail="created with mode 0600",
        )
    )
    loaded = load_config(target, required=True)
    assert loaded is not None
    return loaded.config, warnings, actions


def _prepare_toolchain(
    info: bundle_module.BundleInfo,
    *,
    uv_override: Path | None,
    python_override: Path | None,
) -> tuple[Path, Path]:
    if uv_override is not None:
        uv_path = uv_override
    else:
        assert info.uv_path is not None
        paths.ensure_directory(paths.toolchain_root())
        uv_path = paths.toolchain_root() / f"uv-{info.uv_version}"
        if not uv_path.exists():
            shutil.copy2(info.uv_path, uv_path)
        paths.ensure_executable(uv_path)
    if python_override is not None:
        python_path = python_override
    else:
        assert info.python_tarball is not None
        destination = paths.toolchain_root() / f"python-{info.python_version}"
        interpreter = destination / "bin" / "python3"
        if not interpreter.exists():
            interpreter = bundle_module.extract_python(info.python_tarball, destination)
        python_path = interpreter
    return uv_path, python_path


def _cache_wheelhouse(info: bundle_module.BundleInfo) -> Path:
    cache = paths.wheel_cache_dir(info.version)
    wheelhouse = cache / "wheelhouse"
    try:
        paths.ensure_directory(cache)
        shutil.copytree(info.root / "wheelhouse", wheelhouse, dirs_exist_ok=True)
        shutil.copy2(info.wheel.path, cache / info.wheel.path.name)
    except OSError as error:
        raise DeployError(
            "unwritable_path",
            f"cannot cache the wheelhouse for {info.version} at {cache}: {error}",
            "Free space or fix the permissions on the state directory, then retry.",
            exit_code=3,
            path=str(cache),
        ) from error
    return cache


def _rollback_previous(
    report: Report,
    previous: DeploymentRecord,
    *,
    uv_path: Path,
    python_path: Path,
    tool_dir: Path,
    bin_dir: Path,
) -> None:
    """Restore the previous version and record the rollback outcome."""

    try:
        _rollback(
            previous,
            uv_path=uv_path,
            python_path=python_path,
            tool_dir=tool_dir,
            bin_dir=bin_dir,
        )
    except DeployError:
        report.actions.append(
            Action(
                action="rollback",
                target=previous.version,
                outcome=ActionOutcome.FAILED,
                detail="could not restore the previous version",
            )
        )
        raise
    report.actions.append(
        Action(
            action="rollback",
            target=previous.version,
            outcome=ActionOutcome.OK,
            detail="restored the previous version from the cache",
        )
    )
    report.status = ReportStatus.ERROR


def _discard_fresh_install(
    report: Report,
    *,
    uv_path: Path,
    tool_dir: Path,
    bin_dir: Path,
    commands: tuple[str, ...],
    version: str,
) -> bool:
    """Remove a failed first installation and record the outcome.

    Without a previous version there is nothing to restore. Leaving the
    promoted tool environment and command links behind would make the next
    plain install refuse as unmanaged, so remove them before reporting the
    failure. ``uv tool uninstall`` removes the environment on macOS but can
    leave the directory behind on Linux, so remove it explicitly too.
    """

    leftover = False
    # Fall through to the explicit removal below if uv cannot do it.
    with contextlib.suppress(DeployError):
        uv_module.tool_uninstall(uv_path, tool_dir=tool_dir, bin_dir=bin_dir)
    for command in commands:
        link = bin_dir / command
        if not link.is_symlink():
            continue
        try:
            link.resolve().relative_to(tool_dir)
        except (OSError, ValueError):
            continue
        try:
            link.unlink()
        except OSError:
            leftover = True
    try:
        _remove_directory(tool_dir, label="tool environment")
    except DeployError:
        leftover = True
    removed = not leftover
    report.actions.append(
        Action(
            action="uv_uninstall",
            target=version,
            outcome=ActionOutcome.OK if removed else ActionOutcome.FAILED,
            detail=(
                "removed the failed first installation"
                if removed
                else "could not fully remove the failed first installation"
            ),
        )
    )
    return removed


def _rollback(
    previous: DeploymentRecord,
    *,
    uv_path: Path,
    python_path: Path,
    tool_dir: Path,
    bin_dir: Path,
) -> None:
    cache = Path(previous.wheel_cache)
    wheelhouse = cache / "wheelhouse"
    wheels = sorted(cache.glob("trovium-*.whl"))
    if not wheelhouse.is_dir() or not wheels:
        raise DeployError(
            "rollback_failed",
            "no cached previous wheel is available for rollback",
            "Reinstall the previous version explicitly with install.sh --version.",
            path=str(cache),
        )
    uv_module.tool_install(
        uv_path,
        python_path=python_path,
        wheelhouse=wheelhouse,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
        wheel=wheels[-1],
        force=True,
    )


def install(opts: InstallOptions) -> Report:
    """Install or upgrade from a verified bundle."""

    report = Report(operation=Operation.INSTALL)
    try:
        return _install(opts, report)
    except DeployError as failure:
        if failure.report is None:
            failure.report = report
        raise


def _preflight_paths() -> None:
    """Validate the install destinations before writing anything."""

    for label, target in (
        ("config directory", config_path().parent),
        ("state directory", paths.state_dir()),
        ("data directory", paths.data_dir()),
        ("command directory", paths.bin_dir()),
    ):
        try:
            paths.validate_writable_path(target)
        except DeployError as failure:
            raise DeployError(
                "unwritable_path",
                f"{label} is not writable: {target}",
                "Fix the path permissions or set the matching TROVIUM_* override, "
                "then retry. Nothing was changed.",
                exit_code=3,
                path=str(target),
            ) from failure


def _install(opts: InstallOptions, report: Report) -> Report:
    _preflight_paths()
    if _running_from_active_tool_dir():
        raise DeployError(
            "install_failed",
            "refusing to install from the active tool environment",
            "Run install.sh instead; promotion would replace the running installer.",
        )
    platform = paths.detect_platform()
    paths.ensure_supported(platform)
    with acquire_lock():
        record_before = read_record()
        info = bundle_module.load_bundle(
            opts.bundle,
            platform=platform,
            uv_override=opts.uv_override,
            python_override=opts.python_override,
        )
        config, config_warnings, config_actions = _resolve_install_config(opts)
        report.config_path = str(config.path)
        report.checks.append(
            Check(name="platform", status=CheckStatus.PASS, detail=platform.bundle)
        )
        report.checks.extend(_config_checks(config))
        report.checks.append(
            Check(
                name="config",
                status=CheckStatus.PASS if not config_warnings else CheckStatus.WARN,
                detail="; ".join(config_warnings)
                if config_warnings
                else "config is valid",
                remedy=None if not config_warnings else "Review the config warnings.",
            )
        )
        if (
            record_before is not None
            and record_before.version == info.version
            and record_before.config_path == str(config.path)
            and not config_actions
            and _commands_executable(
                Path(record_before.bin_dir), record_before.commands
            )
        ):
            report.operation = Operation.INSTALL
            report.status = ReportStatus.NOOP
            report.version = record_before.version
            report.previous_version = record_before.version
            report.install_root = record_before.tool_dir
            report.bin_dir = record_before.bin_dir
            report.commands = list(record_before.commands)
            report.checks.append(
                Check(
                    name="record",
                    status=CheckStatus.PASS,
                    detail="version and config are current",
                )
            )
            report.actions.extend(config_actions)
            report.next_steps.append(
                "Run trovium-deploy status for the full installation view."
            )
            # A no-op still reports the checks it made: a failing media mount or
            # missing source must not be hidden behind "noop" (report-schema:
            # a fail check is error, warnings are degraded).
            checked = _report_status(report.checks)
            if checked is not ReportStatus.OK:
                report.status = checked
            return report.finish()
        if not opts.force and record_before is None:
            existing = [
                command
                for command in info.wheel.commands
                if (paths.bin_dir() / command).exists()
            ]
            if existing:
                existing_text = ", ".join(existing)
                raise DeployError(
                    "unmanaged_install",
                    "commands already exist without a deployment record: "
                    f"{existing_text}",
                    "Remove the existing commands or rerun with --force.",
                    exit_code=3,
                )
        adopted = (
            opts.force
            and record_before is None
            and any(
                (paths.bin_dir() / command).exists() for command in info.wheel.commands
            )
        )
        if record_before is not None:
            report.operation = Operation.UPGRADE
            report.previous_version = record_before.version
        report.actions.append(
            Action(
                action="verify_bundle",
                target=info.root.name,
                outcome=ActionOutcome.OK,
                detail="manifest and checksums verified",
            )
        )
        # Cache before promotion: this is the last fallible write that needs the
        # bundle, and a failure here must not leave a promoted tool environment
        # without a rollback cache.
        cache = _cache_wheelhouse(info)
        report.actions.append(
            Action(
                action="cache",
                target=str(cache),
                outcome=ActionOutcome.OK,
                detail="cached the wheelhouse for rollback",
            )
        )
        uv_path, python_path = _prepare_toolchain(
            info,
            uv_override=opts.uv_override,
            python_override=opts.python_override,
        )
        report.checks.append(
            Check(
                name="bundle",
                status=CheckStatus.PASS,
                detail=f"{info.version} for {info.platform}",
            )
        )
        paths.ensure_directory(paths.bin_dir())
        active_tool = paths.tool_dir()
        bin_dir = paths.bin_dir()
        staging = paths.staging_root() / uuid.uuid4().hex
        staging_tool = staging / "tools"
        staging_bin = staging / "bin"
        try:
            uv_module.tool_install(
                uv_path,
                python_path=python_path,
                wheelhouse=info.root / "wheelhouse",
                tool_dir=staging_tool,
                bin_dir=staging_bin,
                wheel=info.wheel.path,
                force=True,
            )
            report.actions.append(
                Action(
                    action="stage",
                    target=info.version,
                    outcome=ActionOutcome.OK,
                    detail="staged in an isolated tool directory",
                )
            )
            staged_check = run_selfcheck(staging_bin, info.wheel.commands)
            if staged_check.status != "pass":
                bad = next(
                    (item for item in staged_check.commands if item.status != "pass"),
                    None,
                )
                raise DeployError(
                    "self_check_failed",
                    (
                        f"{bad.name}: {bad.detail}"
                        if bad is not None
                        else "staged self-check failed"
                    ),
                    "Fix the failing command or install a previous version.",
                )
            report.actions.append(
                Action(
                    action="self_check",
                    target=info.version,
                    outcome=ActionOutcome.OK,
                    detail="staged commands passed --help",
                )
            )
            uv_module.tool_install(
                uv_path,
                python_path=python_path,
                wheelhouse=info.root / "wheelhouse",
                tool_dir=active_tool,
                bin_dir=bin_dir,
                wheel=info.wheel.path,
                force=True,
            )
            active_check = run_selfcheck(bin_dir, info.wheel.commands)
            if active_check.status != "pass":
                bad_active = next(
                    (item for item in active_check.commands if item.status != "pass"),
                    None,
                )
                report.actions.append(
                    Action(
                        action="self_check",
                        target=info.version,
                        outcome=ActionOutcome.FAILED,
                        detail=(
                            f"{bad_active.name}: {bad_active.detail}"
                            if bad_active is not None
                            else "active self-check failed"
                        ),
                    )
                )
                if record_before is not None:
                    _rollback_previous(
                        report,
                        record_before,
                        uv_path=uv_path,
                        python_path=python_path,
                        tool_dir=active_tool,
                        bin_dir=bin_dir,
                    )
                else:
                    removed = _discard_fresh_install(
                        report,
                        uv_path=uv_path,
                        tool_dir=active_tool,
                        bin_dir=bin_dir,
                        commands=info.wheel.commands,
                        version=info.version,
                    )
                remedy = (
                    "The previous version was restored; inspect the failing command."
                    if record_before is not None
                    else (
                        "The failed installation was removed; inspect the failing "
                        "command before retrying."
                        if removed
                        else "The failed installation could not be fully removed; "
                        "inspect the failing command and remove its command links "
                        "and tool directory manually before retrying."
                    )
                )
                raise DeployError(
                    "self_check_failed",
                    "active commands failed their self-check",
                    remedy,
                )
            report.actions.append(
                Action(
                    action="promote",
                    target=info.version,
                    outcome=ActionOutcome.OK,
                    detail="active tool environment replaced",
                )
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        record = DeploymentRecord(
            version=info.version,
            previous_version=report.previous_version,
            installed_at=now(),
            config_path=str(config.path),
            tool_dir=str(active_tool),
            bin_dir=str(bin_dir),
            uv_path=str(uv_path),
            python_path=str(python_path),
            commands=info.wheel.commands,
            wheel_cache=str(cache),
            wheel_sha256=info.wheel.sha256,
            bundle_platform=info.platform,
            last_self_check=active_check,
            last_operation=LastOperation(
                operation=report.operation.value,
                status="ok",
                at=now(),
            ),
            extra={"rollback_available": not adopted},
        )
        try:
            write_record(record)
        except DeployError as record_failure:
            report.actions.append(
                Action(
                    action="write_record",
                    target=str(paths.record_path()),
                    outcome=ActionOutcome.FAILED,
                    detail=record_failure.message,
                )
            )
            # The commands are already promoted. Restore the previous version,
            # or remove the first installation, so the record and the tree agree
            # and the next plain install can repair instead of refusing.
            if record_before is not None:
                _rollback_previous(
                    report,
                    record_before,
                    uv_path=uv_path,
                    python_path=python_path,
                    tool_dir=active_tool,
                    bin_dir=bin_dir,
                )
            else:
                _discard_fresh_install(
                    report,
                    uv_path=uv_path,
                    tool_dir=active_tool,
                    bin_dir=bin_dir,
                    commands=info.wheel.commands,
                    version=info.version,
                )
            raise
        report.actions.append(
            Action(
                action="write_record",
                target=str(paths.record_path()),
                outcome=ActionOutcome.OK,
                detail="deployment state recorded",
            )
        )
        report.actions.extend(config_actions)
        report.version = info.version
        report.install_root = str(active_tool)
        report.bin_dir = str(bin_dir)
        report.commands = list(info.wheel.commands)
        if not paths.path_contains(bin_dir):
            remedy = f'Add `export PATH="{bin_dir}:$PATH"` to your shell profile.'
            report.checks.append(
                Check(
                    name="command_path",
                    status=CheckStatus.WARN,
                    detail=f"{bin_dir} is not on PATH",
                    remedy=remedy,
                )
            )
        report.checks.append(
            Check(
                name="record",
                status=CheckStatus.PASS,
                detail="deployment record written",
            )
        )
        if adopted:
            report.checks.append(
                Check(
                    name="rollback",
                    status=CheckStatus.WARN,
                    detail=(
                        "adopted an unmanaged installation; no cached previous "
                        "wheel exists, so automatic rollback is unavailable"
                    ),
                    remedy=(
                        "Keep the bundle or version you installed so it can be "
                        "reinstalled explicitly."
                    ),
                )
            )
        report.status = _report_status(report.checks)
        report.next_steps.extend(
            [
                "Run trovium-deploy status to verify the installation.",
                "Run trovium-ingest --help to inspect the pipeline options.",
            ]
        )
        return report.finish()


def check(version: str) -> Report | None:
    """Return a no-op report when the exact version is healthy, else None."""

    record = read_record()
    if record is None or record.version != version:
        return None
    if not _commands_executable(Path(record.bin_dir), record.commands):
        return None
    report = Report(
        operation=Operation.INSTALL,
        status=ReportStatus.NOOP,
        version=record.version,
        previous_version=record.version,
        config_path=record.config_path,
        install_root=record.tool_dir,
        bin_dir=record.bin_dir,
        commands=list(record.commands),
        checks=[
            Check(
                name="record",
                status=CheckStatus.PASS,
                detail="version, config, and commands are current",
            )
        ],
        next_steps=["Run trovium-deploy status for the full installation view."],
    )
    return report.finish()


def status(config_override: Path | None = None) -> Report:
    """Read-only installation status."""

    record = read_record()
    if record is None:
        report = Report(
            operation=Operation.STATUS,
            status=ReportStatus.NOT_INSTALLED,
            next_steps=["Run install.sh to install trovium."],
            checks=[
                Check(
                    name="record",
                    status=CheckStatus.PASS,
                    detail="no installation found",
                )
            ],
        )
        return report.finish()
    report = Report(
        operation=Operation.STATUS,
        version=record.version,
        config_path=record.config_path,
        install_root=record.tool_dir,
        bin_dir=record.bin_dir,
        commands=list(record.commands),
    )
    report.checks.append(
        Check(
            name="record",
            status=CheckStatus.PASS,
            detail="deployment record is readable",
        )
    )
    commands_ok = _commands_executable(Path(record.bin_dir), record.commands)
    report.checks.append(
        Check(
            name="installed_commands",
            status=CheckStatus.PASS if commands_ok else CheckStatus.FAIL,
            detail=(
                f"{len(record.commands)} commands present and executable"
                if commands_ok
                else "one or more recorded commands are missing"
            ),
            remedy=None if commands_ok else "Reinstall trovium to repair the commands.",
        )
    )
    report.checks.append(
        Check(
            name="self_check",
            status=CheckStatus.PASS
            if record.last_self_check.status == "pass"
            else CheckStatus.FAIL,
            detail=(
                f"last self-check {record.last_self_check.status} at "
                f"{record.last_self_check.checked_at}"
            ),
            remedy=None
            if record.last_self_check.status == "pass"
            else "Reinstall trovium.",
        )
    )
    target = (
        config_path(config_override) if config_override else Path(record.config_path)
    )
    try:
        loaded = load_config(target, required=True)
    except ConfigError as error:
        report.checks.append(
            Check(
                name="config",
                status=CheckStatus.FAIL,
                detail=str(error),
                remedy="Fix the config file and rerun status.",
            )
        )
    else:
        assert loaded is not None
        report.checks.extend(_config_checks(loaded.config))
        report.checks.append(
            Check(
                name="config",
                status=CheckStatus.PASS if not loaded.warnings else CheckStatus.WARN,
                detail="; ".join(loaded.warnings)
                if loaded.warnings
                else "config is valid",
                remedy=None if not loaded.warnings else "Review the config warnings.",
            )
        )
    if not paths.path_contains(Path(record.bin_dir)):
        remedy = f'Add `export PATH="{record.bin_dir}:$PATH"` to your shell profile.'
        report.checks.append(
            Check(
                name="command_path",
                status=CheckStatus.WARN,
                detail=f"{record.bin_dir} is not on PATH",
                remedy=remedy,
            )
        )
    report.status = _report_status(report.checks)
    if report.status is ReportStatus.DEGRADED:
        report.next_steps.append("Review the warnings above and rerun status.")
    return report.finish()


def _remove_directory(path: Path, *, label: str) -> None:
    """Remove a deployment-owned directory and refuse to call a partial removal done."""

    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError as error:
        raise DeployError(
            "unwritable_path",
            f"cannot remove {label} {path}: {error}",
            "Fix the ownership or permissions and rerun uninstall.",
            exit_code=3,
            path=str(path),
        ) from error
    if path.exists():
        raise DeployError(
            "unwritable_path",
            f"{label} {path} still exists after removal",
            "Inspect the directory and remove it manually, then rerun uninstall.",
            exit_code=3,
            path=str(path),
        )


def uninstall(*, purge: bool = False, config_override: Path | None = None) -> Report:
    """Remove commands and state; preserve config/media unless purging."""

    report = Report(operation=Operation.UNINSTALL)
    try:
        return _uninstall(purge=purge, config_override=config_override, report=report)
    except DeployError as failure:
        if failure.report is None:
            failure.report = report
        raise


def _uninstall(*, purge: bool, config_override: Path | None, report: Report) -> Report:
    with acquire_lock():
        record = read_record()
        if record is None:
            target = config_path(config_override)
            if purge and target.exists():
                try:
                    target.unlink()
                except OSError as error:
                    raise DeployError(
                        "unwritable_path",
                        f"config is not removable: {target}",
                        "Fix the path permissions or remove the file, then retry.",
                        exit_code=3,
                        path=str(target),
                    ) from error
                report.actions.append(
                    Action(
                        action="purge_config",
                        target=str(target),
                        outcome=ActionOutcome.OK,
                        detail="removed config",
                    )
                )
                report.status = ReportStatus.OK
            else:
                report.status = ReportStatus.NOOP
                report.next_steps.append("No installation was found.")
            report.checks.append(
                Check(
                    name="record",
                    status=CheckStatus.PASS,
                    detail="no installation found",
                )
            )
            return report.finish()
        report.version = record.version
        report.config_path = record.config_path
        report.install_root = record.tool_dir
        report.bin_dir = record.bin_dir
        report.commands = list(record.commands)
        tool_dir = Path(record.tool_dir)
        bin_dir = Path(record.bin_dir)
        uv_path = Path(record.uv_path)
        try:
            uv_module.tool_uninstall(uv_path, tool_dir=tool_dir, bin_dir=bin_dir)
            report.actions.append(
                Action(
                    action="uv_uninstall",
                    target=record.version,
                    outcome=ActionOutcome.OK,
                    detail="uv tool environment removed",
                )
            )
        except DeployError:
            for command in record.commands:
                link = bin_dir / command
                if link.is_symlink():
                    try:
                        target = link.resolve()
                        target.relative_to(tool_dir)
                    except (OSError, ValueError):
                        continue
                    link.unlink()
                    report.actions.append(
                        Action(
                            action="remove_command",
                            target=str(link),
                            outcome=ActionOutcome.OK,
                            detail="removed recorded symlink",
                        )
                    )
            report.actions.append(
                Action(
                    action="uv_uninstall",
                    target=record.version,
                    outcome=ActionOutcome.SKIPPED,
                    detail="uv unavailable; removed recorded paths instead",
                )
            )
            _remove_directory(tool_dir, label="tool environment")
        _remove_directory(paths.state_dir() / "cache", label="state cache")
        _remove_directory(paths.staging_root(), label="staging directory")
        _remove_directory(paths.toolchain_root(), label="private toolchain")
        record_path = paths.record_path()
        try:
            record_path.unlink(missing_ok=True)
        except OSError as error:
            raise DeployError(
                "unwritable_path",
                f"cannot remove deployment record {record_path}: {error}",
                "Fix the file permissions and rerun uninstall.",
                exit_code=3,
                path=str(record_path),
            ) from error
        report.actions.append(
            Action(
                action="remove_state",
                target=str(paths.record_path()),
                outcome=ActionOutcome.OK,
                detail="removed deployment record, cache, and private toolchain",
            )
        )
        if purge:
            target = (
                Path(record.config_path)
                if config_override is None
                else config_path(config_override)
            )
            if target.exists():
                target.unlink()
                report.actions.append(
                    Action(
                        action="purge_config",
                        target=str(target),
                        outcome=ActionOutcome.OK,
                        detail="removed config",
                    )
                )
        report.status = ReportStatus.OK
        report.checks.append(
            Check(name="record", status=CheckStatus.PASS, detail="installation removed")
        )
        report.next_steps.append(
            "Configuration was preserved."
            if not purge
            else "Configuration was purged; media and source data were untouched."
        )
        return report.finish()


__all__ = ["InstallOptions", "check", "install", "status", "uninstall"]
