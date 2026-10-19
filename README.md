# trovium

Unix-philosophy replacements for the fractured *arr media-automation stack.
Each pipeline step is an independent, single-purpose command-line tool that
composes with the others over explicit streams — no all-in-one monolith, no
shared database, no hidden state between steps.

> **Status: pre-alpha.** The first slice is the **import/ingest** step, with
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
file names preserved), and prints a machine-readable JSON run record.

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

| Option                              | Default              | Notes                                                                                  |
| ----------------------------------- | -------------------- | -------------------------------------------------------------------------------------- |
| `--source PATH`                     | —                    | directory whose direct children are candidates; mutually exclusive with `--client-url` |
| `--client-url URL`                  | `TROVIUM_CLIENT_URL` | qBittorrent WebUI base URL                                                             |
| `--library-root PATH`               | required             | library destination root                                                               |
| `--category {movie,tv,all}`         | `all`                | declared run scope                                                                     |
| `--mode {move,copy,hardlink}`       | `move`               | placement semantics                                                                    |
| `--post-ingest {keep,pause,delete}` | `keep`               | client-side policy (client mode only)                                                  |
| `--dry-run`                         | off                  | emit the plan; touch neither source nor library                                        |
| `--on-fail {stop,continue}`         | `continue`           | per-item failure behavior                                                              |
| `--json {compact,pretty}`           | `pretty`             | formatting of the record (same data)                                                   |

Full contracts live in
[`specs/001-ingest-vertical-slice/contracts/`](specs/001-ingest-vertical-slice/contracts/).

> **Client-mode note.** With `--mode move`, the client is pointed at the
> library folder (`setLocation`). That is safe for single-file torrents only;
> a multi-file torrent is refused as a per-item error with guidance to use
> `--mode copy` or `--mode hardlink`, because the flat library layout does not
> match the client's `<save_path>/<torrent name>/` expectation and moving the
> files would break seeding.

## Development

Requires [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync            # create the environment and install dev dependencies
scripts/check.sh   # the full quality gate (see below)
```

`scripts/check.sh` is the single canonical check — everything the quality
gate runs: ruff (lint + format), mypy, pytest, and the markdown / file-format /
shell linters. The same command runs locally and at every gate boundary. The
Python steps directly, if you prefer:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## License

AGPL-3.0-only. See [LICENSE](LICENSE).
