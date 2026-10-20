# Data Model: Server Deployment

**Feature**: `002-server-deployment` | **Date**: 2026-10-19

Entities are derived from spec.md "Key Entities" and the plan's technical
decisions. Types are language-agnostic; concrete Python dataclasses land in the
implementation phase.

## Entity Overview

| Entity                  | Persistence           | Purpose                                                        |
| ----------------------- | --------------------- | -------------------------------------------------------------- |
| DeploymentConfiguration | `config.ini`          | Operator settings shared by deployment and pipeline steps      |
| DeploymentRecord        | `deployment.json`     | Installed version, paths, commands, last check, last operation |
| ReleaseBundle           | `.tar.gz` + extracted | Versioned, integrity-verified installation payload             |
| BundleManifest          | `manifest.json`       | Bundle identity, platform, pinned tools, file digests          |
| DeploymentRunReport     | stdout (JSON)         | Machine-readable result of one deployment invocation           |
| DeploymentAction        | part of a run report  | One step taken or considered during an operation               |
| DeploymentCheck         | part of a run report  | One validation result with pass/warn/fail                      |
| DeploymentError         | part of a run report  | Named failure with a remedy                                    |
| SelfCheckResult         | record + run report   | Per-command `--help` verification outcome                      |
| TargetPlatform          | derived               | Normalized host platform used for bundle selection             |

## DeploymentConfiguration

The single INI file read by `trovium-ingest` and `trovium-deploy`. Credential
values never appear here; only the names of environment variables that hold
them.

### Schema

| Section     | Key                   | Type         | Default                   | Validation                                                        |
| ----------- | --------------------- | ------------ | ------------------------- | ----------------------------------------------------------------- |
| `[meta]`    | `schema_version`      | integer      | `1`                       | Missing = 0 (migrate with backup); newer = warn, no rewrite       |
| `[library]` | `root`                | path         | none (required)           | Expanded; may be absent = warning; must be a directory if present |
| `[source]`  | `mode`                | enum         | none                      | `disk` or `client`; if absent, source is unconfigured             |
| `[source]`  | `path`                | path         | none                      | Required when mode = `disk`; expanded; may be absent = warning    |
| `[source]`  | `client_url`          | URL          | none                      | Required when mode = `client`; `http`/`https`; no userinfo        |
| `[source]`  | `client_username_env` | env-var name | `TROVIUM_CLIENT_USERNAME` | Non-empty; no `=`; value is never stored                          |
| `[source]`  | `client_password_env` | env-var name | `TROVIUM_CLIENT_PASSWORD` | Non-empty; no `=`; value is never stored                          |
| `[ingest]`  | `category`            | enum         | `all`                     | `movie`, `tv`, `all`                                              |
| `[ingest]`  | `mode`                | enum         | `move`                    | `move`, `copy`, `hardlink`                                        |
| `[ingest]`  | `post_ingest`         | enum         | `keep`                    | `keep`, `pause`, `delete`; applies only to client mode            |
| `[ingest]`  | `on_fail`             | enum         | `continue`                | `stop`, `continue`                                                |
| `[ingest]`  | `json`                | enum         | `pretty`                  | `compact`, `pretty`                                               |

### Validation rules

- The file is read with `configparser` and `interpolation=None`; duplicate
  sections or keys are a hard error.
- `[library] root` is required for a usable installation. Interactive installs
  prompt for it; non-interactive installs fail with a missing-input list if
  neither the flag, the environment, nor the config file supplies it.
- A supplied path that does not exist is a warning, not a fatal error: the
  volume may be mounted after installation. The installer never creates or
  writes to the library or source path.
- `client_url` must parse as an absolute `http` or `https` URL. Userinfo
  (`user:password@host`) is refused because it would put a secret in a file or
  argument.
- `post_ingest` is ignored in disk mode but remains valid for a later client-mode
  run.
- Unknown sections and keys are preserved on migration; they are not silently
  dropped.
- The file is created with mode 0600 and its parent directory 0700. On install,
  an existing file's mode is tightened to 0600 and the change is reported.
- No key stores a credential value. The only credential-related values are
  environment-variable names.

### Configuration precedence

For `trovium-ingest` and the installer:

1. Explicit command-line option.
2. Environment variable (`TROVIUM_CLIENT_URL`, `TROVIUM_SOURCE`,
   `TROVIUM_LIBRARY_ROOT`, or the configured credential env names).
3. Configuration file.
4. Built-in default, where one exists.

An explicitly supplied `--config PATH` that is missing is an error. The default
config path is optional; when absent, built-in defaults and existing flag
behavior apply.

### Config migration

- `schema_version` missing is treated as 0.
- A known older schema is backed up to
  `config.ini.bak.<UTC timestamp>` before any rewrite.
- Known keys are added or normalized; valid existing values are preserved.
- A newer schema is not rewritten. The report carries a warning with the
  detected and supported versions.
- Invalid syntax or invalid enum values are hard failures before any install
  change.

## DeploymentRecord

The per-user, per-installation state file at
`${XDG_STATE_HOME:-~/.local/state}/trovium/deployment.json`.

| Field              | Type              | Validation / notes                                        |
| ------------------ | ----------------- | --------------------------------------------------------- |
| `schema_version`   | integer           | `1` for this feature                                      |
| `version`          | string            | Installed trovium version, matching the wheel metadata    |
| `previous_version` | string or null    | Version active before the last successful operation       |
| `installed_at`     | timestamp         | ISO 8601 UTC                                              |
| `config_path`      | absolute path     | The config file the installer used or created             |
| `tool_dir`         | absolute path     | Private uv tool environment root                          |
| `bin_dir`          | absolute path     | Directory containing the console-script links             |
| `uv_path`          | absolute path     | Private uv binary used for install/uninstall              |
| `python_path`      | absolute path     | Private CPython interpreter used for the tool environment |
| `commands`         | list of strings   | Every console script exported by the installed wheel      |
| `wheel_cache`      | absolute path     | Cached wheel used for rollback                            |
| `wheel_sha256`     | string            | SHA-256 of the cached wheel                               |
| `bundle_platform`  | string            | Platform of the bundle that produced this installation    |
| `last_self_check`  | SelfCheckResult   | Last self-check outcome and timestamp                     |
| `last_operation`   | operation summary | Operation, status, timestamp, and error code if any       |

### Invariants

- Exactly one active version per user; all commands come from the same wheel.
- The record is written only by `trovium-deploy`; users may inspect it but the
  tooling owns it.
- The record contains no credential values and no secret-bearing environment
  values.
- Paths are absolute and expanded; a relative path is a record validation error.
- Writes are atomic: temp file in the same directory, fsync, `os.replace`, mode 0600.
- The parent state directory is mode 0700.
- A lock file in the same directory serializes operations.

## ReleaseBundle

A platform-specific, self-contained installation payload.

| Part                            | Contents                                               |
| ------------------------------- | ------------------------------------------------------ |
| `manifest.json`                 | Identity, platform, pinned tool versions, file digests |
| `wheelhouse/`                   | trovium wheel plus every runtime dependency wheel      |
| `toolchain/uv-<ver>`            | Pinned uv binary                                       |
| `toolchain/python-<ver>.tar.gz` | Pinned CPython standalone distribution                 |
| `install.sh`                    | Bootstrap script shipped with the bundle               |
| `LICENSES/`                     | Project and third-party license notices                |

### BundleManifest

| Field            | Type               | Validation / notes                                                 |
| ---------------- | ------------------ | ------------------------------------------------------------------ |
| `schema_version` | integer            | `1`                                                                |
| `version`        | string             | Must equal the trovium wheel metadata version                      |
| `platform`       | string             | `linux-x86_64`, `linux-aarch64`, `darwin-x86_64`, `darwin-aarch64` |
| `python_version` | string             | Must satisfy `>=3.13`                                              |
| `uv_version`     | string             | Informational; the binary path carries the same version            |
| `files`          | map path -> digest | Every regular file except `manifest.json`; `sha256:<hex>`          |

### Verification rules

- The outer tarball's detached `.sha256` must match before extraction; that
  checksum covers every bundled file and is the bootstrap's trust anchor for
  executing bundled tools.
- For an extracted directory supplied to the deploy CLI, every manifest entry
  must exist and match its digest before any bundled executable is run or the
  Python tarball is extracted.
- For a tarball, the bootstrap verifies the outer checksum, then the deploy CLI
  verifies manifest entries before using the uv binary, Python, or wheel.
- Paths in the manifest must be relative, must not traverse outside the bundle,
  and must not be absolute.
- The manifest platform must match the normalized host platform.
- The wheel's `METADATA` version must equal the manifest version.
- The wheel's `entry_points.txt` must list at least one `console_scripts` entry.
- The Python tarball must contain `bin/python3` and report a 3.13+ version.
- The uv binary must be executable after extraction; the deploy CLI sets mode
  0755 if needed.
- Extra files not listed in the manifest are ignored but not executed.

## TargetPlatform

Normalized host identity used to select and verify a bundle.

| Field             | Type   | Validation / notes                                   |
| ----------------- | ------ | ---------------------------------------------------- |
| `os`              | enum   | `linux` or `darwin`                                  |
| `arch`            | enum   | `x86_64` or `aarch64`; `arm64` and `amd64` normalize |
| `bundle_platform` | string | `<os>-<arch>`; must equal the manifest platform      |

Unsupported OS/architecture combinations are refused before any change.

## DeploymentRunReport

The JSON document emitted to stdout for every `install`, `status`, and
`uninstall` invocation. The authoritative field-level contract is
`contracts/report-schema.md`.

| Field              | Type                  | Notes                                              |
| ------------------ | --------------------- | -------------------------------------------------- |
| `schema_version`   | integer               | `1`                                                |
| `operation`        | enum                  | `install`, `upgrade`, `status`, `uninstall`        |
| `status`           | enum                  | `ok`, `noop`, `degraded`, `not_installed`, `error` |
| `version`          | string or null        | Active version after the operation                 |
| `previous_version` | string or null        | Active version before the operation                |
| `config_path`      | absolute path or null | The config file in use                             |
| `install_root`     | absolute path or null | Private tool environment                           |
| `bin_dir`          | absolute path or null | Command directory                                  |
| `commands`         | list of strings       | Console scripts found or expected                  |
| `actions`          | list of Action        | Ordered actions with outcomes                      |
| `checks`           | list of Check         | Validation results                                 |
| `next_steps`       | list of strings       | Operator guidance, secret-free                     |
| `error`            | Error or null         | Required when status = `error`                     |
| `finished_at`      | timestamp             | ISO 8601 UTC                                       |

### DeploymentAction

| Field     | Type           | Notes                                                              |
| --------- | -------------- | ------------------------------------------------------------------ |
| `action`  | string         | e.g. `verify_bundle`, `stage`, `self_check`, `promote`, `rollback` |
| `target`  | string         | Path, command, or version the action applies to                    |
| `outcome` | enum           | `ok`, `skipped`, `failed`                                          |
| `detail`  | string or null | Secret-free explanation                                            |

### DeploymentCheck

| Field    | Type           | Notes                                                   |
| -------- | -------------- | ------------------------------------------------------- |
| `name`   | string         | e.g. `platform`, `config`, `installed_commands`, `path` |
| `status` | enum           | `pass`, `warn`, `fail`                                  |
| `detail` | string         | Secret-free observation                                 |
| `remedy` | string or null | Actionable guidance when not passing                    |

### DeploymentError

| Field     | Type           | Notes                             |
| --------- | -------------- | --------------------------------- |
| `code`    | string         | Stable machine-readable code      |
| `message` | string         | Human-readable cause, secret-free |
| `remedy`  | string         | Actionable next step              |
| `path`    | string or null | Relevant path, if any             |

## SelfCheckResult

| Field         | Type                 | Notes                        |
| ------------- | -------------------- | ---------------------------- |
| `status`      | enum                 | `pass` or `fail`             |
| `checked_at`  | timestamp            | ISO 8601 UTC                 |
| `commands`    | list of CommandCheck | One entry per console script |
| `duration_ms` | integer              | Total elapsed time           |

CommandCheck: `{name, status, exit_code, detail}`. Each command is run with
`--help` in a sanitized environment (`HOME`, `PATH`, `XDG_*`, `LC_ALL=C`, no
credential variables) with a short timeout. A non-zero exit, timeout, or
traceback is a failure.

## State Transitions

| Current state | Operation                    | Next state                                    |
| ------------- | ---------------------------- | --------------------------------------------- |
| none          | install                      | installed (or unchanged on preflight failure) |
| installed     | install, same version/config | installed, report `noop`                      |
| installed     | install, different version   | upgrading → installed or rolled back          |
| installed     | status                       | installed, no mutation                        |
| installed     | uninstall (no purge)         | none, config preserved                        |
| installed     | uninstall (purge)            | none, config removed                          |
| none          | uninstall                    | none, report `noop`                           |
| any           | lock held                    | unchanged, report `error`                     |
| staging       | self-check pass              | promote                                       |
| staging       | self-check fail              | unchanged, report `error`                     |
| promote       | active self-check pass       | installed, record updated                     |
| promote       | active self-check fail       | rollback to cached previous wheel             |
| promote       | rollback fail                | unchanged or degraded, report `error`         |

## Paths

| Purpose           | Default                                                  | Override              |
| ----------------- | -------------------------------------------------------- | --------------------- |
| Config file       | `${XDG_CONFIG_HOME:-~/.config}/trovium/config.ini`       | `TROVIUM_CONFIG_FILE` |
| State directory   | `${XDG_STATE_HOME:-~/.local/state}/trovium`              | `TROVIUM_STATE_HOME`  |
| Data directory    | `${XDG_DATA_HOME:-~/.local/share}/trovium`               | `TROVIUM_DATA_HOME`   |
| Command directory | `${TROVIUM_BIN_DIR:-~/.local/bin}`                       | `TROVIUM_BIN_DIR`     |
| Lock file         | `<state>/deploy.lock`                                    | derived               |
| Record            | `<state>/deployment.json`                                | derived               |
| Wheel cache       | `<state>/cache/<version>/`                               | derived               |
| Bundle cache      | `${XDG_CACHE_HOME:-~/.cache}/trovium/bundles/<version>/` | `TROVIUM_CACHE_HOME`  |
| Tool environment  | `<data>/tools/trovium`                                   | derived               |
| Private uv        | `<data>/toolchain/uv-<version>`                          | derived               |
| Private Python    | `<data>/toolchain/python-<version>/`                     | derived               |

## Cross-Entity Invariants

- A report never contains a credential value, a password environment value, or
  a URL with userinfo.
- The config file is the only place runtime settings are read from; no pipeline
  step invents a second config parser.
- The deployment record and config file are separate: state is not configuration
  and configuration is not state.
- Installation, upgrade, uninstall, and status never write to the library,
  source, or client data. Only the pipeline steps do, under their own contracts.
- The active version and every command in the record come from one wheel; mixed
  versions are invalid.
- A failed or interrupted operation never leaves a record claiming success for
  work that did not complete.
