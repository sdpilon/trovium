# Quickstart: Ingest Vertical Slice

**Feature**: `001-ingest-vertical-slice` | **Date**: 2026-10-17

Runnable validation scenarios proving the ingest step works end-to-end.
References: [spec.md](spec.md), [contracts/cli.md](contracts/cli.md),
[contracts/record-schema.md](contracts/record-schema.md),
[data-model.md](data-model.md).

The scenarios run **in order** and share the `$tmp` tree, so state carries
between them. Each scenario states the starting state it needs in its own
**Setup** block; run that block before the scenario's commands if you are
re-entering the document part-way through.

## Prerequisites

- `uv` present; one-time: `uv sync` (environment + dev deps)
- The command under development is exercised as `uv run trovium-ingest …`
- No download client required for scenarios 1–4 (disk mode is the primary
  path); scenario 5 needs a reachable qBittorrent instance

## Shared setup (disk mode)

```sh
tmp=$(mktemp -d)
mkdir -p "$tmp/source/Movie.Production.2024.1080p-iGor" "$tmp/library"
printf 'x' > "$tmp/source/Movie.Production.2024.1080p-iGor/Movie.Production.2024.1080p-iGor.mkv"
```

## Scenario 1: disk ingest places media and reports (Story P1, ids 1–2)

**Setup**: the shared setup above; `$tmp/source` holds one movie release,
`$tmp/library` is empty.

```sh
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --mode move --json pretty
```

**Expected**: exit 0; stdout JSON has `source: "disk"`; the item appears as
`ingested`, `destination` beneath the library root; the file exists at the
destination with its original name; source dir no longer contains it.
Non-media children in the same source would appear as
`rejected_out_of_scope` with a reason.

**Ending state**: `$tmp/source` holds an empty
`Movie.Production.2024.1080p-iGor/` entry; `$tmp/library` holds the placed
movie.

## Scenario 2: idempotent re-run (SC-002, FR-004, Story P1 id 3)

**Setup**: Scenario 1 has consumed the only candidate with `move`, so a plain
re-run can no longer observe an existing item. `already_handled` requires a
candidate that survives placement, so use **copy mode** with a fresh source:

```sh
mkdir -p "$tmp/source2/Show.Name.S01"
printf 'e' > "$tmp/source2/Show.Name.S01/Show.Name.S01E01.mkv"
printf 'f' > "$tmp/source2/Show.Name.S01/Show.Name.S01E02.mkv"
```

**Run 2a — no-op after move** (the leftover empty entry must not be counted
as a new ingest):

```sh
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --json compact
```

**Expected 2a**: exit 0; the empty entry is reported `rejected_out_of_scope`
with reason `no ingestable media files`; nothing is ingested again; the
library is unchanged; record counts reconcile.

**Run 2b — `already_handled` in copy mode**:

```sh
uv run trovium-ingest --source "$tmp/source2" --library-root "$tmp/library" --mode copy --json compact
uv run trovium-ingest --source "$tmp/source2" --library-root "$tmp/library" --mode copy --json compact
```

**Expected 2b**: run 1 reports the pack as `ingested`; run 2 reports it as
`already_handled` with no duplicate created and the library unchanged; source
files still present after both runs; counts reconcile.

**Ending state**: `$tmp/source2` still holds both episode files;
`$tmp/library` holds the movie and the TV pack.

## Scenario 3: inspect-only mode emits the plan, changes nothing (FR-006, Story P4)

**Setup**: add a candidate that has not been placed yet, so the plan actually
contains actions:

```sh
mkdir -p "$tmp/source/Another.Film.2023.720p-GRP"
printf 'y' > "$tmp/source/Another.Film.2023.720p-GRP/Another.Film.2023.720p-GRP.mkv"
```

```sh
# portable, space-safe snapshot: shasum on macOS, sha256sum on Linux
snapshot() {
  find "$tmp/library" -type f -print0 | sort -z | xargs -0 shasum -a 256 2>/dev/null \
    || find "$tmp/library" -type f -print0 | sort -z | xargs -0 sha256sum
}
before=$(snapshot)
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --dry-run --json compact
after=$(snapshot)
[ "$before" = "$after" ] && echo "library unchanged: OK"
```

> macOS ships `shasum` (not `sha256sum`); the fallback keeps the scenario
> runnable on either target platform. Paths must stay NUL-delimited: library
> destinations contain spaces (e.g. `Movie Production (2024)`), and
> newline-splitting `xargs` silently fails on them.

**Expected**: exit 0; record has `dry_run: true` with a full `actions` plan for
the new film; printed `library unchanged: OK`; the source file is still present
after the dry run. Re-running the same command without `--dry-run` produces the
same `actions` field-for-field (SC-005).

## Scenario 4: misuse is refused before any work (FR-013, Story P1 id 4)

**Setup**: any state — refusals must happen before work, so nothing changes.

```sh
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --client-url http://127.0.0.1:8080
uv run trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --post-ingest delete
```

**Expected**: exit code 2; stderr names the conflicting option pair; the
library is untouched; nothing on stdout.

## Scenario 5: client mode (Story P2; needs qBittorrent)

**Setup**: a reachable qBittorrent instance with a completed, seeded media
torrent and (as a control) an incomplete download; export the credentials:

```sh
export TROVIUM_CLIENT_URL=http://127.0.0.1:8080
export TROVIUM_CLIENT_USERNAME=admin
export TROVIUM_CLIENT_PASSWORD='...'
uv run trovium-ingest --library-root "$tmp/library" --json pretty
```

**Expected**:

- completed, single-file seeded torrent → placed into the library, disposition
  `ingested`, record `source: "client"`;
- a **folder torrent** (multi-file, or one video plus sidecars) under the
  default `--mode move` → per-item `error` recommending `--mode copy` or
  `--mode hardlink`, with nothing placed and the client's `save_path`
  unchanged;
- `--mode copy` or `--mode hardlink` for a folder torrent → `ingested`, source
  kept, seeding still at 100%;
- incomplete downloads left untouched as `not_yet_complete` (no error);
- wrong password / unreachable URL → exit 3 with a named error on stderr and
  nothing placed (FR-008).

Additional checks:

```sh
# folder torrent under move: refused with guidance
uv run trovium-ingest --library-root "$tmp/library" --json compact

# pause + move: pause, setLocation, recheck, in that order; torrent stays 100%
uv run trovium-ingest --library-root "$tmp/library" --post-ingest pause --json compact
```

**Expected**: the first run's item is `error` with the copy/hardlink guidance;
the second run's `client_actions` lists `pause`, `setLocation`, `recheck`, and
the client reports the torrent stopped but complete (100%).

If no client is available, record the client-mode half as **not independently
verified** rather than marking it passed; the automated suite covers the same
paths with a stubbed transport (`tests/integration/test_client_ingest.py`).

## Full quality gate

```sh
scripts/check.sh
```

Runs ruff (lint + format), mypy, pytest, and the file/markdown linters —
identically to CI (constitutions XXVI, XIII).
