# Quickstart: Ingest Vertical Slice

**Feature**: `001-ingest-vertical-slice` | **Date**: 2026-10-17

Runnable validation scenarios proving the ingest step works end-to-end.
References: [spec.md](spec.md), [contracts/cli.md](contracts/cli.md),
[contracts/record-schema.md](contracts/record-schema.md),
[data-model.md](data-model.md).

## Prerequisites

- `uv` present; one-time: `uv sync` (environment + dev deps)
- The command under development is exercised as `uv run trovium-ingest …`
- No download client required for scenarios 1–4 (disk mode is the primary
  path); scenario 5 needs a reachable qBittorrent instance

## Setup (disk mode)

```sh
tmp=$(mktemp -d)
mkdir -p "$tmp/source/Movie.Production.2024.1080p-iGor" "$tmp/library"
printf 'x' > "$tmp/source/Movie.Production.2024.1080p-iGor/Movie.Production.2024.1080p-iGor.mkv"
```

## Scenario 1: disk ingest places media and reports (Story P1, ids 1–2)

```sh
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --mode move --json pretty
```

**Expected**: exit 0; stdout JSON has `source: "disk"`; the item appears as
`ingested`, `destination` beneath the library root; the file exists at the
destination with its original name; source dir no longer contains it.
Non-media children in the same source would appear as
`rejected_out_of_scope` with a reason.

## Scenario 2: idempotent re-run (SC-002, FR-004, Story P1 id 3)

```sh
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --json compact
```

**Expected**: exit 0; item disposition `already_handled`; no duplicate or new
file created; record counts reconcile.

## Scenario 3: inspect-only mode emits the plan, changes nothing (FR-006, Story P4)

```sh
before=$(find "$tmp/library" -type f | sort | sha256sum)
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --dry-run --json compact
after=$(find "$tmp/library" -type f | sort | sha256sum)
```

**Expected**: exit 0; record has `dry_run: true` with full `actions`; snapshot
hash `before == after` (library unchanged); with a client configured, the
client state would also be untouched.

## Scenario 4: misuse is refused before any work (FR-013, Story P1 id 4)

```sh
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --client-url http://127.0.0.1:8080
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --post-ingest delete
```

**Expected**: exit code 2; stderr names the conflicting option pair; the
library is untouched; nothing on stdout.

## Scenario 5: client mode (Story P2; needs qBittorrent)

Prepopulate: put a `TZARCHIVE.Incelemede.S01E01.1080p-iGor` torrent with
`TROVIUM_CLIENT_URL=http://127.0.0.1:8080`, `TROVIUM_CLIENT_USERNAME`,
`TROVIUM_CLIENT_PASSWORD` exported, then:

```sh
export TROVIUM_CLIENT_URL=http://127.0.0.1:8080
export TROVIUM_CLIENT_USERNAME=admin
export TROVIUM_CLIENT_PASSWORD='...'
uv run trovium-ingest --library-root "$tmp/library" --json pretty
```

**Expected**:

- completed, seeded torrent → placed into the library, disposition
  `ingested`, record `source: "client"`;
- incomplete downloads left untouched as `not_yet_complete` (no error);
- wrong password / unreachable URL → exit 3 with a named error on stderr and
  nothing placed (FR-008).

## Full quality gate

```sh
scripts/check.sh
```

Runs ruff (lint + format), mypy, pytest, and the file/markdown linters —
identically to CI (constitutions XXVI, XIII).
