# trovium

Unix-philosophy replacements for the fractured *arr media-automation stack.
Each pipeline step is an independent, single-purpose command-line tool that
composes with the others over explicit streams — no all-in-one monolith, no
shared database, no hidden state between steps.

> **Status: pre-alpha.** Two commands ship today: the **import/ingest** step
> (`trovium-ingest`) and **server deployment** (`trovium-deploy`), with
> qBittorrent as the first download client.

## Why

The *arr stack solves a real problem, but it bundles every concern — indexers,
download clients, renaming, quality profiles, notifications — into a few large
applications whose internals are hard to reason about, replace, or test in
isolation.

trovium takes the opposite approach: one tool per pipeline step, each with a
stable text/JSON contract, so any step can be run, inspected, and replaced on
its own.

## Design

- **One tool per step.** Each step is a single-purpose CLI that reads and writes
  plain text or JSON over stdin/stdout.
- **Files are the interface.** Steps exchange inspectable files, never in-process
  state.
- **One client adapter.** All download-client interaction passes through a single
  adapter (qBittorrent first).
- **Typed Python.** Python ≥3.13 with static type checking; `ruff`, `mypy`, and
  `pytest` are the canonical checks.

The full set of project principles lives in the
[constitution](.specify/memory/constitution.md).

## Usage

### `trovium-ingest`

The import/ingest step. It takes candidates from either a download client
(qBittorrent, through the single adapter) or a directory of media already on
disk, classifies each as a movie / TV / unresolvable using its own names only,
places resolvable items into the library (folder structure derived; original
file names preserved), and prints a machine-readable JSON run record. Every
candidate appears in the record once with a `disposition` (`ingested`,
`already_handled`, `not_yet_complete`, `unresolvable`,
`rejected_out_of_scope`, or `error`), so nothing is dropped silently.

```sh
# disk source — no download client involved
uv run trovium-ingest --source ~/Downloads/incoming --library-root ~/Media

# inspect what would happen, changing nothing
uv run trovium-ingest --source ~/Downloads/incoming --library-root ~/Media --dry-run

# qBittorrent source (credentials from the environment only)
export TROVIUM_CLIENT_URL=http://127.0.0.1:8080
export TROVIUM_CLIENT_USERNAME=admin
export TROVIUM_CLIENT_PASSWORD=...
uv run trovium-ingest --library-root ~/Media
```

The command exits `0` when the run completed — per-item problems are recorded,
not fatal — `2` on misuse, and `3` on a run-level client failure (unreachable,
unauthenticated, or a malformed response).

| Option                              | Default              | Notes                                                                                  |
| ----------------------------------- | -------------------- | -------------------------------------------------------------------------------------- |
| `--source PATH`                     | —                    | directory whose direct children are candidates; mutually exclusive with `--client-url` |
| `--client-url URL`                  | `TROVIUM_CLIENT_URL` | qBittorrent WebUI base URL                                                             |
| `--library-root PATH`               | required             | library destination root                                                               |
| `--config PATH`                     | XDG                  | configuration file (default: XDG `trovium/config.ini`)                                 |
| `--category {movie,tv,all}`         | `all`                | declared run scope                                                                     |
| `--mode {move,copy,hardlink}`       | `move`               | placement semantics                                                                    |
| `--post-ingest {keep,pause,delete}` | `keep`               | client-side policy (client mode only)                                                  |
| `--dry-run`                         | off                  | emit the plan; touch neither source nor library                                        |
| `--on-fail {stop,continue}`         | `continue`           | per-item failure behavior                                                              |
| `--json {compact,pretty}`           | `pretty`             | formatting of the record (same data)                                                   |

`--source`, `--client-url`, `--library-root`, and `--config` also read
environment fallbacks (`TROVIUM_SOURCE`, `TROVIUM_CLIENT_URL`,
`TROVIUM_LIBRARY_ROOT`, `TROVIUM_CONFIG_FILE`). Options resolve flags →
environment → config file → built-in defaults.

Full contracts live in
[`specs/001-ingest-vertical-slice/contracts/`](specs/001-ingest-vertical-slice/contracts/).

> **Client-mode note.** With `--mode move`, the client is pointed at the
> library folder (`setLocation`). That is safe for single-file torrents only;
> a **folder torrent** (including one holding a single video plus sidecars) is
> refused as a per-item error with guidance to use `--mode copy` or
> `--mode hardlink`, because the flat library layout does not match the
> client's `<save_path>/<torrent name>/` expectation and moving the files would
> break seeding.

## Install on a server

The deployment feature is defined in
[`specs/002-server-deployment/`](specs/002-server-deployment/). It installs every
shipped pipeline step for the current user, creates a configuration file, runs a
self-check, and records deployment state. It is user-scoped and does not require
root.

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
```

Inspect, upgrade, or remove the installation:

```sh
trovium-deploy status
trovium-deploy check --version 0.2.0  # fast health check; exit 1 when not current
bash install.sh --version 0.2.0 --non-interactive --library-root /srv/media
trovium-deploy uninstall          # keeps config and media
trovium-deploy uninstall --purge  # also removes config, never media
```

The configuration file is `${XDG_CONFIG_HOME:-~/.config}/trovium/config.ini`.
Deployment targets one server and one media library; scheduling, containers, and
multi-server fleet management are out of scope. Exact CLI and config contracts
live in [`specs/002-server-deployment/contracts/`](specs/002-server-deployment/contracts/).

### Supported hosts

Release bundles target Linux on x86_64 and aarch64. macOS builds are for local
development only. The installer refuses musl-based Linux with
`unsupported_platform` until the static toolchain has been verified there; set
`TROVIUM_ALLOW_MUSL=1` only after performing that verification yourself. glibc
Linux is the supported server target.

## Development

Requires [`uv`](https://docs.astral.sh/uv/). The gate also runs the pinned Node
linters (`npm ci`) and shellcheck (pinned in `.tool-versions`).

```sh
uv sync            # create the environment and install dev dependencies
npm ci             # once: pinned prettier/markdownlint-cli2 for the gate
scripts/check.sh   # the full quality gate (see below)
```

`scripts/check.sh` is the single canonical check — everything the quality
gate runs: ruff (lint + format), mypy, pytest, and the markdown / file-format /
shell linters. The same command runs locally and at every gate boundary. Run
the Python steps directly, if you prefer:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

### Live client testing

`tests/` uses stubbed HTTP transports, so it cannot observe what qBittorrent
does with the files afterwards. [`tools/qbt-live-rig/`](tools/qbt-live-rig/)
runs two local qBittorrent instances plus a tracker and hands the CLI a real
directory of peer-downloaded files; no root or external services are needed.
See its [README](tools/qbt-live-rig/README.md) for the quick start.

## License

AGPL-3.0-only. See [LICENSE](LICENSE).
