# CLI Contract: Server Deployment

**Feature**: `002-server-deployment` | **Date**: 2026-10-19

This contract is authoritative for the deployment commands and the
configuration extension to `trovium-ingest`.

## Commands

| Command          | Role                                                                                |
| ---------------- | ----------------------------------------------------------------------------------- |
| `install.sh`     | Bootstrap: install, upgrade, status, and uninstall without a prior install          |
| `trovium-deploy` | Installed lifecycle CLI: `install` engine, `check` fast path, `status`, `uninstall` |
| `trovium-ingest` | Existing pipeline step, extended with configuration-file fallbacks                  |

## install.sh

### install.sh usage

```text
install.sh [bootstrap-options] [mode-options]
```

The bootstrap resolves a bundle, verifies it, extracts it, and runs the
bundle's `trovium-deploy` CLI. The default mode installs or upgrades. `--status`
and `--uninstall` make lifecycle operations available even when the installed
command is missing or broken.

### Bootstrap options

| Option                   | Value          | Default                                       | Meaning                                                         |
| ------------------------ | -------------- | --------------------------------------------- | --------------------------------------------------------------- |
| `--version VERSION`      | version string | latest stable                                 | Use this bundle version; mutually exclusive with `--bundle`     |
| `--bundle PATH`          | tarball        | none                                          | Use a local bundle tarball; mutually exclusive with `--version` |
| `--sha256 HEX`           | 64 hex chars   | sidecar for tarballs                          | Required for a local tarball without a `.sha256` sidecar        |
| `--release-base-url URL` | URL            | `https://github.com/sdpilon/trovium/releases` | Alternate release location                                      |
| `--status`               | none           | none                                          | Report installation state without changing it                   |
| `--uninstall`            | none           | none                                          | Remove the installation                                         |
| `--purge`                | none           | off                                           | With `--uninstall`, remove the config file too                  |
| `-h`, `--help`           | none           | none                                          | Print usage and exit 0                                          |

### Mode options (install and upgrade)

| Option                    | Value | Default       | Meaning                                        |
| ------------------------- | ----- | ------------- | ---------------------------------------------- |
| `--non-interactive`       | none  | off           | Never prompt; fail with missing inputs instead |
| `--library-root PATH`     | path  | config/prompt | Media library root written to config           |
| `--source PATH`           | path  | config        | Disk source written to config                  |
| `--client-url URL`        | URL   | config        | qBittorrent WebUI base URL written to config   |
| `--config PATH`           | path  | XDG default   | Config file to read or create                  |
| `--force`                 | none  | off           | Replace an unmanaged existing installation     |
| `--json {compact,pretty}` | enum  | `pretty`      | Formatting of the JSON report                  |

Unknown options are misuse (exit 2). `--source` and `--client-url` are mutually
exclusive. No credential option exists. `--release-base-url` must be an absolute
`http`/`https` URL without userinfo; a URL carrying credentials is refused so it
cannot reach a report or log. Mode options are rejected with `--status` or
`--uninstall` when they do not apply. `--json` is accepted in every mode; it is
listed with the install options for brevity.

### Environment inputs

| Variable                   | Meaning                           |
| -------------------------- | --------------------------------- |
| `TROVIUM_LIBRARY_ROOT`     | Fallback for `--library-root`     |
| `TROVIUM_SOURCE`           | Fallback for `--source`           |
| `TROVIUM_CLIENT_URL`       | Fallback for `--client-url`       |
| `TROVIUM_CONFIG_FILE`      | Overrides the default config path |
| `TROVIUM_STATE_HOME`       | Overrides the state directory     |
| `TROVIUM_DATA_HOME`        | Overrides the data directory      |
| `TROVIUM_CACHE_HOME`       | Overrides the cache directory     |
| `TROVIUM_BIN_DIR`          | Overrides the command directory   |
| `TROVIUM_RELEASE_BASE_URL` | Fallback for `--release-base-url` |

Credential values are read only from the environment variables named in the
config (defaults `TROVIUM_CLIENT_USERNAME` and `TROVIUM_CLIENT_PASSWORD`). They
are never accepted as options and never printed.

### Interactive and non-interactive behavior

- Without `--non-interactive`, a missing required input is prompted for when a
  terminal is available. If stdin is not a terminal (the `curl | bash` case),
  prompts read from `/dev/tty`.
- With `--non-interactive`, or with no terminal and no `/dev/tty`, the command
  fails before changing anything with a list of missing inputs.
- The only required input is a library root, unless a config file already
  supplies it.
- The installer also offers to configure a disk source or client URL. Skipping
  leaves `[source]` unset; status reports a warning and the config can be edited
  later.
- Client credentials are never required to install; their absence is a warning
  that status reports.

### install.sh examples

```sh
# Online, interactive
curl -fsSL https://github.com/sdpilon/trovium/releases/latest/download/install.sh | bash -s --

# Online, unattended
curl -fsSL https://github.com/sdpilon/trovium/releases/latest/download/install.sh \
  | bash -s -- --non-interactive --library-root /srv/media

# Offline, local bundle
bash install.sh --bundle ./trovium-0.1.0-linux-x86_64.tar.gz \
  --non-interactive --library-root /srv/media

# Pinned version
bash install.sh --version 0.1.0 --non-interactive --library-root /srv/media

# Status and uninstall remain available without a working installed command
bash install.sh --status
bash install.sh --uninstall
bash install.sh --uninstall --purge
```

The bootstrap verifies the bundle before extracting or executing it. Online
progress goes to stderr; stdout is reserved for the JSON report produced by
`trovium-deploy`.

## trovium-deploy

### trovium-deploy usage

```text
trovium-deploy install --bundle DIR [install-options]
trovium-deploy check --version VERSION [--json {compact,pretty}]
trovium-deploy status [--config PATH] [--json {compact,pretty}]
trovium-deploy uninstall [--purge] [--json {compact,pretty}]
```

`install` is the engine invoked by `install.sh`. Users normally use
`install.sh` for install and upgrade; invoking `trovium-deploy install
--bundle` directly runs the same path when an extracted bundle is already
available. Prefer `install.sh` because it runs the bundle's CLI in an ephemeral
environment, so promotion never replaces the running installer.

### install options

| Option                    | Value                | Required | Meaning                                            |
| ------------------------- | -------------------- | -------- | -------------------------------------------------- |
| `--bundle DIR`            | extracted bundle dir | yes      | Verified bundle containing the wheel and toolchain |
| `--non-interactive`       | none                 | no       | Never prompt                                       |
| `--library-root PATH`     | path                 | cond.    | Required if config has no library root             |
| `--source PATH`           | path                 | no       | Disk source                                        |
| `--client-url URL`        | URL                  | no       | Client WebUI URL; no userinfo                      |
| `--config PATH`           | path                 | no       | Config file to read or create                      |
| `--force`                 | none                 | no       | Replace an unmanaged existing installation         |
| `--json {compact,pretty}` | enum                 | no       | Report formatting                                  |

### check (internal fast path)

`check --version VERSION` reads the deployment record and reports whether that
exact version is already installed. It is used by `install.sh` to avoid
downloading a bundle for an identical re-run. When current, it emits the
standard no-op install report and exits 0. When not current, it emits nothing on
stdout and exits 1; the bootstrap then resolves the bundle. It never changes
installation state and is not a normal operator command.

### status options

`status` reads the deployment record and the config file. It never changes
installation state and never contacts the download client. It reports the
active version, config path, command presence, config validation, path
warnings, and the last self-check result.

### uninstall options

`uninstall` removes the commands and tool environment recorded by the
deployment, plus the state record, cache, and private toolchain. It preserves
the config file and all media unless `--purge` is supplied. A host with no
record is a successful no-op.

### trovium-deploy examples

```sh
trovium-deploy status
trovium-deploy status --json compact
trovium-deploy uninstall
trovium-deploy uninstall --purge
```

## trovium-ingest configuration extension

This section extends `specs/001-ingest-vertical-slice/contracts/cli.md`. Existing
flags, exit codes, and misuse rules remain; configuration fallbacks and
`--config` are additive.

### New option

| Option          | Value | Default                                            | Meaning                    |
| --------------- | ----- | -------------------------------------------------- | -------------------------- |
| `--config PATH` | path  | `${XDG_CONFIG_HOME:-~/.config}/trovium/config.ini` | Configuration file to read |

An explicitly supplied `--config` that does not exist is misuse (exit 2). The
default config path is optional; when it does not exist, existing flag and
environment behavior is unchanged.

### Precedence

1. Explicit CLI option.
2. Environment variable (`TROVIUM_LIBRARY_ROOT`, `TROVIUM_SOURCE`,
   `TROVIUM_CLIENT_URL`, or the credential variables named by the config).
3. Config file.
4. Existing built-in default.

`--library-root` is required only when no CLI option, environment variable, or
config value supplies it. The existing mutual-exclusion and misuse rules still
apply. When config supplies `[source] mode = disk`, `path` is used unless
`--source` or `--client-url` is supplied. When config supplies `mode = client`,
`client_url` is used unless overridden.

### Credentials

The config stores `client_username_env` and `client_password_env` names. The
actual values are read from those environment variables at run time. They are
never stored in the config, echoed in the record, or printed in diagnostics.

### trovium-ingest examples

```sh
# Use the default config path
trovium-ingest

# Use a specific config file
trovium-ingest --config /etc/trovium/config.ini

# CLI still overrides config
trovium-ingest --library-root /mnt/other-library --mode copy
```

## Output streams and exit codes

- **stdout**: exactly one JSON deployment report for `install`, `status`, and
  `uninstall`, including failures. See `contracts/report-schema.md`.
- **stderr**: progress, human-readable summary, and a one-line error message.
- **Secrets**: never present in either stream.
- **`--json`**: affects formatting only; the data is identical.

| Code | Name      | Meaning                                                                        |
| ---- | --------- | ------------------------------------------------------------------------------ |
| 0    | success   | Operation completed, or a valid no-op/not-installed status                     |
| 1    | check     | Internal `check`: requested version is not installed; bootstrap continues      |
| 2    | misuse    | Unknown option, missing required input, conflicting options                    |
| 3    | preflight | Unsupported platform, missing prerequisite, unwritable path, unmanaged install |
| 4    | bundle    | Download, checksum, manifest, platform, or wheel-metadata failure              |
| 5    | install   | Staging, self-check, promotion, rollback, or tool-operation failure            |
| 6    | lock      | Another deployment operation holds the lock                                    |
| 7    | config    | Invalid syntax, unsupported schema, or invalid config value                    |

`status` exits 0 with `status: "not_installed"` when no record exists, and with
`status: "degraded"` when only warnings are present. It exits 3 when a check
fails or the record and installed commands disagree.
