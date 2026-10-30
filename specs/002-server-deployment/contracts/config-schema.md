# Configuration Schema: Server Deployment

**Feature**: `002-server-deployment` | **Date**: 2026-10-19

> **Profile-aware addendum**: `specs/003-media-profiles-books/contracts/config-schema.md`
> adds optional `[ingest] profile` (default `video`) and makes `[ingest]
category` profile-dependent. Existing schema-1 files remain valid.
>
> **Adaptive-mode addendum**: `specs/007-ebooks-full-pipeline/contracts/config-cli.md`
> adds `mode = auto`, the default for new configs. It resolves per candidate:
> a seeding torrent hardlinks on one filesystem and copies across filesystems;
> disk and non-seeding sources move. Existing schema-1 files remain valid.

The configuration file is a single INI document read by `trovium-deploy` and
`trovium-ingest`. It stores settings, never credential values.

## Location and permissions

- Default path:
  `${XDG_CONFIG_HOME:-$HOME/.config}/trovium/config.ini`
- Override for advanced use and tests: `TROVIUM_CONFIG_FILE`.
- The file and any backup are created with mode `0600`.
- The parent directory is created with mode `0700` when the installer creates
  it.
- An existing file with broader permissions is tightened to `0600` and the
  change is reported as an action.

## Example

```ini
# trovium configuration. Schema 1.
[meta]
schema_version = 1

[library]
root = /srv/media

[source]
mode = client
client_url = http://127.0.0.1:8080
client_username_env = TROVIUM_CLIENT_USERNAME
client_password_env = TROVIUM_CLIENT_PASSWORD

[ingest]
category = all
mode = move
post_ingest = keep
on_fail = continue
json = pretty
```

Disk-source variant:

```ini
[source]
mode = disk
path = /srv/downloads/complete
```

## Sections and keys

### `[meta]`

| Key              | Type    | Required | Default | Rules                                                                      |
| ---------------- | ------- | -------- | ------- | -------------------------------------------------------------------------- |
| `schema_version` | integer | no       | `1`     | Missing is treated as 0 and migrated with a backup; newer is not rewritten |

### `[library]`

| Key    | Type | Required | Default | Rules                                                                   |
| ------ | ---- | -------- | ------- | ----------------------------------------------------------------------- |
| `root` | path | yes      | none    | Expanded with `~`; may be absent at install time (warning); not created |

### `[source]`

| Key                   | Type         | Required             | Default                   | Rules                                             |
| --------------------- | ------------ | -------------------- | ------------------------- | ------------------------------------------------- |
| `mode`                | enum         | no                   | none                      | `disk` or `client`; absent means unconfigured     |
| `path`                | path         | when mode = `disk`   | none                      | Expanded; may be absent at install time (warning) |
| `client_url`          | URL          | when mode = `client` | none                      | Absolute `http`/`https`; userinfo is refused      |
| `client_username_env` | env-var name | no                   | `TROVIUM_CLIENT_USERNAME` | Non-empty; no `=`; value never stored             |
| `client_password_env` | env-var name | no                   | `TROVIUM_CLIENT_PASSWORD` | Non-empty; no `=`; value never stored             |

`path` and `client_url` are mutually exclusive in one config. Specifying both
is a validation error.

### `[ingest]`

| Key           | Type | Required | Default    | Rules                                           |
| ------------- | ---- | -------- | ---------- | ----------------------------------------------- |
| `category`    | enum | no       | `all`      | `movie`, `tv`, `all`                            |
| `mode`        | enum | no       | `move`     | `move`, `copy`, `hardlink`                      |
| `post_ingest` | enum | no       | `keep`     | `keep`, `pause`, `delete`; ignored in disk mode |
| `on_fail`     | enum | no       | `continue` | `stop`, `continue`                              |
| `json`        | enum | no       | `pretty`   | `compact`, `pretty`                             |

## Precedence

For `trovium-ingest` and the installer:

1. Explicit command-line option.
2. Environment variable.
3. Configuration file.
4. Built-in default.

The default config path is optional. An explicitly supplied `--config` path that
does not exist is an error. An invalid default config is a hard error rather
than a silent fallback, because ignoring a broken configuration is more
dangerous than refusing to run.

## Install and upgrade behavior

- If the config file exists, the installer validates it and preserves it. It
  does not regenerate or overwrite values. CLI values that conflict with the
  existing config are reported as ignored rather than applied.
- If the config file does not exist, the installer creates it from flags,
  environment variables, prompts (interactive), or documented defaults.
- If `--config` points at an existing file elsewhere, the installer reads that
  file and installs a copy at the canonical path only when the canonical path is
  absent. An existing canonical config wins, and the report says the supplied
  file was not applied.
- A library root is required unless the config supplies one. A supplied path
  that is absent is a warning, not a hard failure.
- An unconfigured source is allowed. Status reports a warning and the config can
  be edited later to add a disk path or client URL.
- An invalid enum, URL, or syntax is a hard failure before any install change.
- On upgrade, valid existing values are preserved. Unknown keys are preserved.
- A config from a newer schema is preserved and reported as a warning; it is not
  rewritten.

## Migration

| Detected state                   | Action                                                                |
| -------------------------------- | --------------------------------------------------------------------- |
| Missing `schema_version`         | Treat as 0; back up; add `[meta] schema_version = 1`; preserve values |
| `schema_version` = 1             | No migration                                                          |
| `schema_version` < 1             | Back up; apply known migrations; preserve unknown keys                |
| `schema_version` > 1             | No rewrite; warn with detected and supported versions                 |
| Invalid syntax or duplicate keys | Fail with `config_invalid`; change nothing                            |

The backup name is `config.ini.bak.<UTC timestamp>`, created with mode `0600`.
The report records the backup path.

## Secret rules

- No credential value is accepted on a command line.
- No credential value is written to the config, the deployment record, or the
  run report.
- Credential environment-variable names are data; their values are not.
- A `client_url` containing userinfo is refused with a remedy to move the
  credentials into the named environment variables.
- The installer may check whether a named variable is set, but reports only
  `set`/`unset`, never the value.
