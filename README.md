# trovium

Unix-philosophy replacements for the fractured *arr media-automation stack.
Each pipeline step is an independent, single-purpose command-line tool that
composes with the others over explicit streams — no all-in-one monolith, no
shared database, no hidden state between steps.

> **Status: pre-alpha (`v0.2.0`).** Four commands ship today: the
> **import/ingest** step (`trovium-ingest`), **renaming**
> (`trovium-rename`), the **pipeline runner** (`trovium-run`), and
> **server deployment** (`trovium-deploy`), with qBittorrent as the first
> download client.

## Install

The current release is `v0.2.0`. On a Linux server, use the release installer
described in [Install on a server](#install-on-a-server). For macOS, or to
track the current `main`, install it as a user-scoped tool with
[`uv`](https://docs.astral.sh/uv/):

```sh
uv tool install --from git+https://github.com/sdpilon/trovium trovium
```

That puts `trovium-ingest`, `trovium-rename`, `trovium-run`, and
`trovium-deploy` in `~/.local/bin`. Make sure that directory is on your
`PATH` (`uv tool update-shell` can add it), then verify the install:

```sh
trovium-run --help

# inspect a first run without changing anything
trovium-run --source ~/Downloads/incoming --library-root ~/Media --dry-run
```

Update the installed copy after new commits land:

```sh
uv tool install --from git+https://github.com/sdpilon/trovium trovium --force
```

`uv tool install` installs the commands only. `trovium-deploy status` reports
`not_installed` until you run the managed bundle installer described in
[Install on a server](#install-on-a-server).

### From a checkout

For development, or to run a branch you are working on:

```sh
uv sync
uv run trovium-run --help
```

The usage examples below use the installed command. Inside a checkout, prefix
them with `uv run`.

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

The examples assume the commands are installed. From a checkout, prefix each
one with `uv run`.

### `trovium-ingest`

The import/ingest step. It takes candidates from either a download client
(qBittorrent, through the single adapter) or a directory of files already on
disk, classifies each through the selected **media profile** (video:
movie/TV; books: ebook), places resolvable items into the library (folder
structure derived; original file names preserved), and prints a
machine-readable JSON run record. Every candidate appears in the record once
with a `disposition` (`ingested`, `already_handled`, `not_yet_complete`,
`unresolvable`, `rejected_out_of_scope`, or `error`), so nothing is dropped
silently. Profiles are how a new media type reuses this step instead of
becoming a new application; see [`docs/profiles.md`](docs/profiles.md).

```sh
# disk source — no download client involved
trovium-ingest --source ~/Downloads/incoming --library-root ~/Media

# ebooks
trovium-ingest --profile books --source ~/Books/incoming --library-root ~/Media

# inspect what would happen, changing nothing
trovium-ingest --source ~/Downloads/incoming --library-root ~/Media --dry-run

# qBittorrent source (credentials from the environment only)
export TROVIUM_CLIENT_URL=http://127.0.0.1:8080
export TROVIUM_CLIENT_USERNAME=admin
export TROVIUM_CLIENT_PASSWORD=...
trovium-ingest --library-root ~/Media
```

The command exits `0` when the run completed — per-item problems are recorded,
not fatal — `2` on misuse, and `3` on a run-level client failure (unreachable,
unauthenticated, or a malformed response).

| Option                              | Default              | Notes                                                                                                                                       |
| ----------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `--source PATH`                     | —                    | directory whose direct children are candidates; mutually exclusive with `--client-url`                                                      |
| `--client-url URL`                  | `TROVIUM_CLIENT_URL` | qBittorrent WebUI base URL                                                                                                                  |
| `--library-root PATH`               | required             | library destination root                                                                                                                    |
| `--config PATH`                     | XDG                  | configuration file (default: XDG `trovium/config.ini`)                                                                                      |
| `--profile NAME`                    | `video`              | media profile (`video`, `books`)                                                                                                            |
| `--category VALUE`                  | `all`                | declared run scope; the profile defines the values (video: movie/tv/all; books: book/all)                                                   |
| `--mode {auto,move,copy,hardlink}`  | `auto`               | placement semantics: `auto` hardlinks a seeding torrent on one filesystem, copies across filesystems, and moves disk or non-seeding sources |
| `--post-ingest {keep,pause,delete}` | `keep`               | client-side policy (client mode only)                                                                                                       |
| `--dry-run`                         | off                  | emit the plan; touch neither source nor library                                                                                             |
| `--on-fail {stop,continue}`         | `continue`           | per-item failure behavior                                                                                                                   |
| `--json {compact,pretty}`           | `pretty`             | formatting of the record (same data)                                                                                                        |

`--source`, `--client-url`, `--library-root`, and `--config` also read
environment fallbacks (`TROVIUM_SOURCE`, `TROVIUM_CLIENT_URL`,
`TROVIUM_LIBRARY_ROOT`, `TROVIUM_CONFIG_FILE`). Options resolve flags →
environment → config file → built-in defaults.

Full contracts live in
[`specs/001-ingest-vertical-slice/contracts/`](specs/001-ingest-vertical-slice/contracts/)
and the profile-aware updates in
[`specs/003-media-profiles-books/contracts/`](specs/003-media-profiles-books/contracts/).

The `books` profile reads EPUB metadata first, falls back to a Calibre
`metadata.opf` sidecar, then to a conservative filename grammar
(`Author - Title (Year)` and a few close variants, plus a leading
`N - Title` series index). A non-EPUB file without its own metadata reuses a
same-stem sibling EPUB's metadata when exactly one exists. Ebooks land under
`Books/<Author>/<Title> (Year)/`; ambiguous names are reported as
`unresolvable` rather than guessed. A client folder torrent holding one book
plus its sidecars is placed as one item and the sidecars travel with it; a
torrent holding several distinct books is `unresolvable` with the files named.

> **Client-mode note.** The default `auto` mode keeps seeding: a completed
> torrent is hardlinked when the download and library directories share a
> filesystem and copied when they do not, with no `setLocation` call. An
> explicit `--mode move` points the client at the library folder
> (`setLocation`), which is safe for single-file torrents only; a **folder
> torrent** is refused as a per-item error with guidance to keep seeding,
> because the flat library layout does not match the client's
> `<save_path>/<torrent name>/` expectation.

### `trovium-rename`

The second pipeline step. It reads an ingest record (stdin by default), asks
the record's profile for canonical names, and renames the placed files. It is
dry-runnable and idempotent.

```sh
# one pipeline
trovium-ingest \
    --profile books --source ~/Books/incoming --library-root ~/Media \
    | trovium-rename

# or inspect the plan first
trovium-ingest \
    --profile books --source ~/Books/incoming --library-root ~/Media > ingest.json
trovium-rename --record ingest.json --dry-run
trovium-rename --record ingest.json
```

Books become `Author - Title (Year).ext` (or
`Author - Series #N - Title (Year).ext`); movies become `Title (Year).ext`;
TV episodes become `Show - S01E01.ext`. Sidecars keep their names. Multi-file
movies and TV files without an episode marker are `skipped` with a reason.

The default is safe and idempotent: copy, hardlink, and `auto` records are
renamed, and a later ingest recognizes the renamed file by content rather than
by name. Only a client item whose torrent was relocated into the library is
skipped, because renaming the file the client tracks breaks seeding.
`--allow-unsafe` overrides that skip after seeding stops.

Full contract:
[`specs/004-profile-rename/contracts/`](specs/004-profile-rename/contracts/).

### `trovium-run`

The configured pipeline. It resolves the same options as ingest, runs ingest,
then runs rename when the record is move-mode and the run is not a dry-run. It
emits one combined JSON record with `ingest` and `rename` sections. This is the
command to put behind cron or a systemd timer.

```sh
# one command, configured source/profile/library
trovium-run --config ~/.config/trovium/config.ini

# inspect the whole pipeline without placing or renaming
trovium-run --config ~/.config/trovium/config.ini --dry-run

# books from an explicit source
trovium-run --profile books --source ~/Books/incoming --library-root ~/Media
```

Copy, hardlink, and `auto` runs rename the placed files. Only client items
whose torrent was relocated into the library are skipped; `--allow-unsafe`
passes the rename override through. `--skip-rename` runs ingest only.

Full contract:
[`specs/005-pipeline-runner/contracts/`](specs/005-pipeline-runner/contracts/).

## Install on a server

The deployment feature is defined in
[`specs/002-server-deployment/`](specs/002-server-deployment/). It installs every
shipped pipeline step for the current user, creates a configuration file, runs a
self-check, and records deployment state. It is user-scoped and does not require
root.

Online:

```sh
curl -fsSL https://github.com/sdpilon/trovium/releases/latest/download/install.sh \
  -o install.sh

bash install.sh                                              # interactive
bash install.sh --non-interactive --library-root /srv/media \
  --source /srv/incoming                                     # unattended, disk source
bash install.sh --non-interactive --library-root /srv/media \
  --client-url http://127.0.0.1:8080                         # unattended, client source
bash install.sh --non-interactive --library-root /srv/media \
  --client-url http://127.0.0.1:8080 --profile books         # ebooks
bash install.sh --version 0.2.0 --non-interactive \
  --library-root /srv/media --source /srv/incoming           # pinned version
```

An unattended install needs one of `--source` or `--client-url`. Without one
the install succeeds, but the config has no source and `trovium-deploy status`
reports `degraded`. Pass `--profile books` (or any registered profile) to write
that profile into the config; new installs use the adaptive `auto` mode.

Downloading first and then running `bash install.sh` keeps a failed download
from being piped into the shell as if it were a script.

From a checkout, for development or an unreleased branch:

```sh
uv run python tools/release/build_bundle.py --version 0.2.0 --out dist
bash install.sh --bundle dist/trovium-0.2.0-linux-x86_64.tar.gz \
  --non-interactive --library-root /srv/media --source /srv/incoming
```

Pick the bundle matching the host: `linux-x86_64`, `linux-aarch64`, or
`darwin-aarch64`. The default build uses the host toolchain; `--locked` builds
the self-contained Linux server bundle from the pinned toolchain.

The bundle installer also writes to `~/.local/bin`. Use it instead of
`uv tool install` on a server, not alongside it.

Inspect, upgrade, or remove the installation:

```sh
trovium-deploy status
trovium-deploy check --version 0.2.0  # fast health check; exit 1 when not current
bash install.sh --version 0.2.0 --non-interactive  # upgrades reuse the config
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
