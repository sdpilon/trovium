# Report Schema: Server Deployment

**Feature**: `002-server-deployment` | **Date**: 2026-10-19

Every `install`, `status`, and `uninstall` invocation writes exactly one JSON
document to **stdout**, including failures. A human summary and progress go to
**stderr**. The same data is emitted with `--json compact` or `--json pretty`;
only whitespace differs.

## Top-level object

| Field              | Type                | Required | Notes                                                       |
| ------------------ | ------------------- | -------- | ----------------------------------------------------------- |
| `schema_version`   | integer             | yes      | `1` for this contract                                       |
| `operation`        | string enum         | yes      | `install`, `upgrade`, `status`, `uninstall`                 |
| `status`           | string enum         | yes      | `ok`, `noop`, `degraded`, `not_installed`, `error`          |
| `version`          | string or null      | yes      | Active version after the operation                          |
| `previous_version` | string or null      | yes      | Active version before the operation                         |
| `config_path`      | string or null      | yes      | Absolute path of the config file in use                     |
| `install_root`     | string or null      | yes      | Absolute private tool-environment path                      |
| `bin_dir`          | string or null      | yes      | Absolute directory containing command links                 |
| `commands`         | array of strings    | yes      | Console scripts found or expected; empty when not installed |
| `actions`          | array of Action     | yes      | Ordered steps; empty for `status`                           |
| `checks`           | array of Check      | yes      | Validation results                                          |
| `next_steps`       | array of strings    | yes      | Secret-free operator guidance                               |
| `error`            | Error or null       | yes      | Required when `status` is `error`; otherwise null           |
| `finished_at`      | ISO 8601 UTC string | yes      | Completion time                                             |

No field may contain a credential value, a secret environment value, or a URL
with userinfo.

Bootstrap failures before the Python CLI starts emit the same top-level object:
`schema_version: 1`, the requested `operation`, `status: "error"`,
`version`/`previous_version`/`config_path`/`install_root`/`bin_dir` set to
`null`, `commands`/`actions`/`checks`/`next_steps` as empty arrays, a populated
`error`, and `finished_at`. Do not emit a reduced shape.

## Action

| Field     | Type           | Required | Notes                                                                                                                                                                                                          |
| --------- | -------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `action`  | string         | yes      | Stable action name: `verify_bundle`, `preflight`, `stage`, `self_check`, `promote`, `rollback`, `write_config`, `write_record`, `uv_install`, `uv_uninstall`, `remove_command`, `remove_state`, `purge_config` |
| `target`  | string         | yes      | Path, command, or version the action applies to                                                                                                                                                                |
| `outcome` | string enum    | yes      | `ok`, `skipped`, `failed`                                                                                                                                                                                      |
| `detail`  | string or null | yes      | Secret-free explanation                                                                                                                                                                                        |

## Check

| Field    | Type           | Required | Notes                                                                                                                                                           |
| -------- | -------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`   | string         | yes      | `platform`, `bundle`, `config`, `library_path`, `source_path`, `source_configured`, `credentials`, `installed_commands`, `command_path`, `record`, `self_check` |
| `status` | string enum    | yes      | `pass`, `warn`, `fail`                                                                                                                                          |
| `detail` | string         | yes      | Secret-free observation                                                                                                                                         |
| `remedy` | string or null | yes      | Actionable guidance when not `pass`                                                                                                                             |

A `fail` check makes the report `error` unless the check is specifically
informational. `warn` checks produce `degraded` for `status` and do not fail
the operation.

## Error

| Field     | Type           | Required | Notes                             |
| --------- | -------------- | -------- | --------------------------------- |
| `code`    | string         | yes      | Stable machine-readable code      |
| `message` | string         | yes      | Human-readable cause, secret-free |
| `remedy`  | string         | yes      | Actionable next step              |
| `path`    | string or null | yes      | Relevant path, if any             |

### Error codes

| Code                   | Typical exit | Meaning                                                     |
| ---------------------- | ------------ | ----------------------------------------------------------- |
| `misuse`               | 2            | Unknown option, missing input, conflicting options          |
| `unsupported_platform` | 3            | Host platform is not a supported bundle platform            |
| `missing_prerequisite` | 3            | Required command (tar, checksum tool, downloader) is absent |
| `unwritable_path`      | 3            | Config, state, data, or bin directory is not writable       |
| `unmanaged_install`    | 3            | Commands exist without a deployment record                  |
| `bundle_download`      | 4            | Remote bundle could not be fetched                          |
| `bundle_integrity`     | 4            | Checksum or manifest digest mismatch                        |
| `bundle_invalid`       | 4            | Missing file, bad layout, wrong version, wrong platform     |
| `lock_held`            | 6            | Another deployment operation holds the lock                 |
| `config_invalid`       | 7            | Syntax, schema, enum, URL, or path validation failure       |
| `install_failed`       | 5            | uv install, staging, or promotion failed                    |
| `self_check_failed`    | 5            | One or more installed commands failed `--help`              |
| `rollback_failed`      | 5            | The previous version could not be restored                  |
| `internal`             | 5            | Unexpected failure; message names the cause and remedy      |

## Status semantics

| `status`        | Meaning                                                  |
| --------------- | -------------------------------------------------------- |
| `ok`            | Operation completed and every check passed               |
| `noop`          | Requested state already present; nothing changed         |
| `degraded`      | Completed, but one or more checks produced warnings      |
| `not_installed` | `status` found no deployment record and no commands      |
| `error`         | Operation failed or `status` found a broken installation |

When a no-op also has warnings, `degraded` takes precedence over `noop` so the
warnings remain visible; `actions` is still empty when nothing changed.

`operation` is `upgrade` when an existing version was replaced. A same-version
re-run is `operation: "install"` with `status: "noop"` and
`previous_version` equal to `version`.

## Examples

### Successful install with a warning

```json
{
  "schema_version": 1,
  "operation": "install",
  "status": "degraded",
  "version": "0.1.0",
  "previous_version": null,
  "config_path": "/home/media/.config/trovium/config.ini",
  "install_root": "/home/media/.local/share/trovium/tools/trovium",
  "bin_dir": "/home/media/.local/bin",
  "commands": ["trovium-deploy", "trovium-ingest"],
  "actions": [
    {
      "action": "verify_bundle",
      "target": "trovium-0.1.0-linux-x86_64",
      "outcome": "ok",
      "detail": "manifest and checksums verified"
    },
    {
      "action": "stage",
      "target": "0.1.0",
      "outcome": "ok",
      "detail": "staged in an isolated tool directory"
    },
    {
      "action": "self_check",
      "target": "trovium-ingest",
      "outcome": "ok",
      "detail": "--help exited 0"
    },
    {
      "action": "promote",
      "target": "0.1.0",
      "outcome": "ok",
      "detail": "active tool environment replaced"
    },
    {
      "action": "write_config",
      "target": "/home/media/.config/trovium/config.ini",
      "outcome": "ok",
      "detail": "created with mode 0600"
    }
  ],
  "checks": [
    {
      "name": "platform",
      "status": "pass",
      "detail": "linux-x86_64",
      "remedy": null
    },
    {
      "name": "library_path",
      "status": "pass",
      "detail": "/srv/media exists and is writable",
      "remedy": null
    },
    {
      "name": "credentials",
      "status": "warn",
      "detail": "client mode is configured but TROVIUM_CLIENT_PASSWORD is unset",
      "remedy": "Export the credential variables named in the config before the first client run."
    }
  ],
  "next_steps": [
    "Run trovium-ingest --help to inspect the pipeline options.",
    "Export TROVIUM_CLIENT_USERNAME and TROVIUM_CLIENT_PASSWORD before a client-mode run."
  ],
  "error": null,
  "finished_at": "2026-10-19T18:00:00Z"
}
```

### Successful no-op

```json
{
  "schema_version": 1,
  "operation": "install",
  "status": "noop",
  "version": "0.1.0",
  "previous_version": "0.1.0",
  "config_path": "/home/media/.config/trovium/config.ini",
  "install_root": "/home/media/.local/share/trovium/tools/trovium",
  "bin_dir": "/home/media/.local/bin",
  "commands": ["trovium-deploy", "trovium-ingest"],
  "actions": [],
  "checks": [
    {
      "name": "record",
      "status": "pass",
      "detail": "version and config are current",
      "remedy": null
    }
  ],
  "next_steps": ["Run trovium-deploy status for the full installation view."],
  "error": null,
  "finished_at": "2026-10-19T18:01:00Z"
}
```

### Status with warnings

```json
{
  "schema_version": 1,
  "operation": "status",
  "status": "degraded",
  "version": "0.1.0",
  "previous_version": null,
  "config_path": "/home/media/.config/trovium/config.ini",
  "install_root": "/home/media/.local/share/trovium/tools/trovium",
  "bin_dir": "/home/media/.local/bin",
  "commands": ["trovium-deploy", "trovium-ingest"],
  "actions": [],
  "checks": [
    {
      "name": "library_path",
      "status": "warn",
      "detail": "/srv/media is not present",
      "remedy": "Mount the library volume before the next pipeline run."
    },
    {
      "name": "installed_commands",
      "status": "pass",
      "detail": "2 commands present and executable",
      "remedy": null
    },
    {
      "name": "self_check",
      "status": "pass",
      "detail": "last self-check passed at 2026-10-19T17:59:00Z for 2 commands",
      "remedy": null
    }
  ],
  "next_steps": [
    "Mount the library volume, then run trovium-deploy status again."
  ],
  "error": null,
  "finished_at": "2026-10-19T18:02:00Z"
}
```

### Failed install

```json
{
  "schema_version": 1,
  "operation": "install",
  "status": "error",
  "version": null,
  "previous_version": null,
  "config_path": null,
  "install_root": null,
  "bin_dir": null,
  "commands": [],
  "actions": [
    {
      "action": "verify_bundle",
      "target": "trovium-0.1.0-linux-x86_64",
      "outcome": "failed",
      "detail": "wheel digest does not match the manifest"
    }
  ],
  "checks": [
    {
      "name": "bundle",
      "status": "fail",
      "detail": "manifest digest mismatch for wheelhouse/trovium-0.1.0-py3-none-any.whl",
      "remedy": "Download the bundle again and verify its .sha256 sidecar."
    }
  ],
  "next_steps": [],
  "error": {
    "code": "bundle_integrity",
    "message": "bundle integrity verification failed",
    "remedy": "Download the bundle again and verify its .sha256 sidecar.",
    "path": "wheelhouse/trovium-0.1.0-py3-none-any.whl"
  },
  "finished_at": "2026-10-19T18:03:00Z"
}
```

## Stream and formatting rules

- The JSON document is the only stdout content. Progress and human summaries
  use stderr.
- `--json compact` removes insignificant whitespace; `--json pretty` uses
  two-space indentation. Both parse to the same object.
- A trailing newline follows the JSON document.
- Missing optional values are `null`, not omitted, so consumers can rely on
  stable keys.
- Timestamps are ISO 8601 UTC with a trailing `Z`.
- Consumers must ignore unknown fields for forward compatibility.
