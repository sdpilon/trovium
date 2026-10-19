# CLI Contract: trovium-ingest

**Feature**: `001-ingest-vertical-slice` | **Date**: 2026-10-17

The stable surface of the `trovium-ingest` command. Contract tests pin this
document's schema.

## Usage

```text
trovium-ingest (--client-url URL | --source PATH)
               --library-root PATH
               [--category {movie,tv,all}]
               [--mode {move,copy,hardlink}]
               [--post-ingest {keep,pause,delete}]
               [--dry-run]
               [--on-fail {stop,continue}]
               [--json {compact,pretty}]
```

## Options

| Option                              | Required                            | Default                  | Applies to       | Notes                                                                                                                                                                          |
| ----------------------------------- | ----------------------------------- | ------------------------ | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--client-url URL`                  | one of `--client-url` or `--source` | env `TROVIUM_CLIENT_URL` | client mode      | base URL of qBittorrent WebUI endpoint                                                                                                                                         |
| `--source PATH`                     | as above                            | —                        | disk mode        | directory whose direct children are candidates (FR-013)                                                                                                                        |
| `--library-root PATH`               | required (both modes)               | —                        | both             | library destination root; layout convention applies beneath it. No default exists — a missing, non-directory, or unreadable path is a misuse refusal (exit 2, named on stderr) |
| `--category {movie,tv,all}`         | no                                  | `all`                    | both             | run scope filter (FR-005)                                                                                                                                                      |
| `--mode {move,copy,hardlink}`       | no                                  | `move`                   | both             | placement semantics (FR-012)                                                                                                                                                   |
| `--post-ingest {keep,pause,delete}` | no                                  | `keep`                   | client mode only | client-side policy after successful placement (FR-010)                                                                                                                         |
| `--dry-run`                         | no                                  | off                      | both             | inspect-only: emit the plan, change nothing (FR-006)                                                                                                                           |
| `--on-fail {stop,continue}`         | no                                  | `continue`               | both             | per-item failure policy (FR-012)                                                                                                                                               |
| `--json {compact,pretty}`           | no                                  | `pretty`                 | both             | formatting of the run record (FR-007)                                                                                                                                          |

## Environment variables

| Variable                  | Meaning                                                       |
| ------------------------- | ------------------------------------------------------------- |
| `TROVIUM_CLIENT_URL`      | default client base URL (may be overridden by `--client-url`) |
| `TROVIUM_CLIENT_USERNAME` | qBittorrent login username                                    |
| `TROVIUM_CLIENT_PASSWORD` | qBittorrent login password                                    |

Credentials are read from the environment only — accepted nowhere on the
command line and never emitted into the run record (constitution I, FR-012).

## Misuse refusal (before any work)

- `--source` together with `--client-url` → refuse (FR-013).
- `--source` together with `--post-ingest` → refuse (FR-013).
- `--source` that does not exist, is not a directory, or is unreadable → refuse
  (exit 2), naming the path.
- No source given and `TROVIUM_CLIENT_URL` unset → refuse.
- Missing, non-directory, or unreadable `--library-root` (in either mode) → refuse.
- Refusal messages name the conflicting option and exit code 2.

## Completion-side behaviors

- In client mode, unreachable endpoint, invalid credentials, or a
  **malformed/unparseable client response** → run fails closed with a named
  error, exit code 3; nothing ingested, no success in the record (FR-008,
  constitution VI).
- Placement executes only for fully classified candidates; file names are
  preserved byte-for-byte (FR-003).
- In client mode, `--mode move` issues `setLocation` to the library folder.
  That path is **single-file-torrent-safe**. For multi-file torrents the flat
  library layout does not match the client's expected
  `<location>/<torrent name>/` layout, so seeding from the library is not
  preserved — use `--mode copy` or `--mode hardlink` for multi-file torrents.
  The item's `client_actions[].detail` carries this note at runtime.
- A **read failure on source files during placement** (e.g. permission denied
  on a candidate's file) is a per-item failure, not a run-level one: the item's
  disposition is `error` with the named cause, governed by
  `--on-fail {stop|continue}` (default `continue`); nothing is half-placed and
  no success is recorded for that item. A source that disappears entirely
  mid-run is treated the same way per item and named in the record.

## Exit codes

| Code | Meaning                                                                           |
| ---- | --------------------------------------------------------------------------------- |
| 0    | run completed; outcome (including skips/errors already reported) is in the record |
| 2    | CLI misuse (refusal rules above) — no partial work                                |
| 3    | run-level failure: client unreachable/auth invalid (FR-008)                       |

Per-item errors inside a completed run do not change the exit code beyond the
above; they are visible as dispositions in the record.

## Streams

- **stdout**: the run record, machine-readable JSON always (FR-007).
- **stderr**: human-facing diagnostics, misuse/connection errors, one line
  per problem; never contains credentials.
- **stdin**: unused.
