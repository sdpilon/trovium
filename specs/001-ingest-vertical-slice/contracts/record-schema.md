# Run Record Schema: trovium-ingest stdout JSON

**Feature**: `001-ingest-vertical-slice` | **Date**: 2026-10-17

The stable machine-readable record emitted every run (SC-004, FR-007).
Formatting only (`--json {compact|pretty}`); the data shape is fixed.
Contract tests pin field names and enums.

## Top level

| Field      | Type                 | Notes                                                                                   |
| ---------- | -------------------- | --------------------------------------------------------------------------------------- |
| `source`   | `"client" \| "disk"` | run's declared source (FR-001)                                                          |
| `dry_run`  | boolean              | true when inspect-only (FR-006)                                                         |
| `declared` | object               | the run's options: `{library_root, category, mode, post_ingest (client only), on_fail}` |
| `items`    | array                | one entry per candidate considered                                                      |
| `counts`   | object               | per-disposition tallies + `total`; MUST equal items                                     |

## Item record

| Field            | Type                      | Notes                                                                                                                                                                                                     |
| ---------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`           | string                    | candidate display name (torrent name or entry name)                                                                                                                                                       |
| `disposition`    | enum                      | `ingested` \| `already_handled` \| `not_yet_complete` \| `unresolvable` \| `rejected_out_of_scope` \| `error`                                                                                             |
| `reason`         | string ∅                  | required for `unresolvable`, `rejected_out_of_scope`, `error`; else nullable                                                                                                                              |
| `kind`           | `"movie" \| "tv" \| null` | resolved classification; null when unresolved (FR-002)                                                                                                                                                    |
| `title`          | string ∅                  | resolved title; null when unresolved                                                                                                                                                                      |
| `destination`    | string ∅                  | resolved/placed library path; null when not applicable                                                                                                                                                    |
| `actions`        | array ∅                   | inspect-only plans and executed ops: `{op: "move"\|"copy"\|"hardlink"\|"delete", from, to, bytes}`. For `delete`, `from` is the removed redundant source and `to` is the existing identical library path. |
| `client_actions` | array ∅                   | client-mode only, present when operations were performed: `{op: "setLocation"\|"pause"\|"delete", detail}` — additive; never contains credentials                                                         |

## Invariants

- `counts` always reconcile with `items` (SC-004).
- No credentials, tokens, or password values appear anywhere in the record
  (constitution I).
- `dry_run: true` records contain a full `actions` plan and are byte-identical
  to the subsequent real run record's plan field-for-field (SC-005, Story P4).
- `destination` and `actions[].to` are absolute but display paths only; no
  environment-provided secret values are embedded.
