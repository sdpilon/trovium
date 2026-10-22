# Rename Record Schema

**Feature**: `004-profile-rename` | **Date**: 2026-10-21

The JSON emitted by `trovium-rename`. It is deliberately close to the ingest
record so a rename record can be fed back into rename.

## Top level

| Field      | Type       | Notes                                                 |
| ---------- | ---------- | ----------------------------------------------------- |
| `source`   | `"rename"` | identifies the step                                   |
| `dry_run`  | boolean    | true when no file changed                             |
| `declared` | object     | `{profile, library_root, mode}` echoed from the input |
| `items`    | array      | one entry per input item                              |
| `counts`   | object     | `{renamed, already_handled, skipped, error, total}`   |

`counts` always reconciles with `items`.

## Item

| Field         | Type     | Notes                                            |
| ------------- | -------- | ------------------------------------------------ |
| `name`        | string   | input item name                                  |
| `disposition` | enum     | `renamed`, `already_handled`, `skipped`, `error` |
| `reason`      | string ∅ | required for `skipped` and `error`               |
| `kind`        | string ∅ | echoed from the input classification             |
| `title`       | string ∅ | echoed from the input classification             |
| `details`     | object ∅ | echoed from the input classification             |
| `destination` | string ∅ | the library folder scanned                       |
| `actions`     | array ∅  | `{op: "rename", from, to, bytes, note?}`         |

The classification fields are echoed so the rename record is a valid input to
a second rename run.

## Invariants

- A target is never overwritten. An existing target makes the item `error` and
  no file in that item is renamed.
- A partial item is rolled back before the record is emitted.
- A second run of the same record reports `already_handled` and changes
  nothing.
- `dry_run: true` actions match the subsequent real run field-for-field.
- No credentials or secret values appear in the record.
