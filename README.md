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

## Development

Requires [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync            # create the environment and install dev dependencies
scripts/check.sh   # ruff lint + format check + mypy + pytest
```

`scripts/check.sh` is the single canonical check — the same command the
quality gate runs, so a green local run and a green pipeline are the same
signal. The steps directly, if you prefer:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## License

AGPL-3.0-only. See [LICENSE](LICENSE).
