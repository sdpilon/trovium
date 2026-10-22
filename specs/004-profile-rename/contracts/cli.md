# CLI Contract: `trovium-rename`

**Feature**: `004-profile-rename` | **Date**: 2026-10-21

`trovium-rename` reads an ingest record and renames the placed files using the
record's profile. It is the second pipeline step.

## Usage

```text
trovium-rename [--record PATH]
               [--dry-run]
               [--allow-unsafe]
               [--on-fail {stop,continue}]
               [--json {compact,pretty}]
```

| Option           | Default    | Notes                                                                                                |
| ---------------- | ---------- | ---------------------------------------------------------------------------------------------------- |
| `--record PATH`  | stdin      | Path to an ingest or previous rename record; `-` means stdin                                         |
| `--dry-run`      | off        | Emit the full plan; change nothing                                                                   |
| `--allow-unsafe` | off        | Permit copy/hardlink and client-relocated items; use only after seeding stops and the source is gone |
| `--on-fail`      | `continue` | Stop after the first `error` item, or continue                                                       |
| `--json`         | `pretty`   | Formatting of the emitted record                                                                     |

No `--profile` or `--library-root`: the record carries both.

## Pipeline

```sh
trovium-ingest --profile books --source ~/Books/incoming \
  --library-root ~/Media --json compact \
  | trovium-rename --json compact
```

Or two steps:

```sh
trovium-ingest --profile books --source ~/Books/incoming \
  --library-root ~/Media --json compact > ingest.json
trovium-rename --record ingest.json --dry-run
trovium-rename --record ingest.json
```

## Safety

- A record whose `declared.mode` is not `move` is refused with exit `2`
  unless `--allow-unsafe` is given. A copy/hardlink library still has its
  source, so renaming breaks the ingest no-op rerun; a hardlink can also be
  the file a client is seeding.
- An item whose `client_actions` contains `setLocation` is `skipped` unless
  `--allow-unsafe` is given: the client points at the library, so renaming
  would break seeding.
- `--allow-unsafe` writes a warning to stderr.

## Naming

| Profile | Candidate                          | Target                                     |
| ------- | ---------------------------------- | ------------------------------------------ |
| books   | author, title, year                | `Author - Title (Year).ext`                |
| books   | author, series, index, title, year | `Author - Series #N - Title (Year).ext`    |
| books   | no author                          | `Title (Year).ext`                         |
| video   | single-file movie                  | `Title (Year).ext`                         |
| video   | TV episode                         | `Show - S01E01.ext`; extra episodes `-E02` |
| all     | sidecars                           | unchanged                                  |

A multi-file movie or a TV file without an episode marker is `skipped` with a
reason.

## Exit codes

| Code | Meaning                                                                                             |
| ---- | --------------------------------------------------------------------------------------------------- |
| `0`  | Run completed; per-item skips/errors are in the record                                              |
| `2`  | Misuse, malformed/unsupported record, unknown profile, or an unsafe record without `--allow-unsafe` |
