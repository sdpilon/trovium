# Combined Run Record Schema

**Feature**: `005-pipeline-runner` | **Date**: 2026-10-22

The JSON emitted by `trovium-run`. It embeds the existing ingest and rename
records without changing either shape.

## Top level

| Field            | Type     | Notes                                     |
| ---------------- | -------- | ----------------------------------------- |
| `source`         | `"run"`  | identifies the runner                     |
| `dry_run`        | boolean  | true when ingest was inspect-only         |
| `profile`        | string   | the resolved profile name                 |
| `library_root`   | string   | the resolved library root                 |
| `ingest`         | object   | the full `trovium-ingest` record          |
| `rename`         | object ∅ | the full `trovium-rename` record, or null |
| `rename_skipped` | string ∅ | why rename did not run, or null           |

Exactly one of `rename` and `rename_skipped` is non-null.

## Invariants

- `ingest` and `rename` follow their own contracts.
- A run-level ingest failure produces no output record and exit `3`.
- A dry-run produces an `ingest` record with `dry_run: true` and no `rename`.
- A copy/hardlink run without `--allow-unsafe` produces an `ingest` record and
  a `rename_skipped` reason.
- No credentials or secret values appear anywhere in the combined record.
- `counts` in each embedded record still reconcile with its `items`.
