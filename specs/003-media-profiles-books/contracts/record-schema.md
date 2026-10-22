# Run Record Schema v2: profile-aware ingest

**Feature**: `003-media-profiles-books` | **Date**: 2026-10-21

This extends `specs/001-ingest-vertical-slice/contracts/record-schema.md`. The
envelope, dispositions, actions, and counts are unchanged. The changes are
additive: `declared.profile`, profile-defined `kind`/`category`, and an
optional per-item `details` object.

## Top level

| Field      | Type                 | Notes                                                           |
| ---------- | -------------------- | --------------------------------------------------------------- |
| `source`   | `"client" \| "disk"` | run's declared source                                           |
| `dry_run`  | boolean              | true when inspect-only                                          |
| `declared` | object               | `{profile, library_root, category, mode, post_ingest, on_fail}` |
| `items`    | array                | one entry per candidate considered                              |
| `counts`   | object               | per-disposition tallies + `total`; MUST equal `items`           |

`declared.profile` is the registered profile name (`"video"`, `"books"`, or a
future profile). `declared.category` is one of that profile's categories,
always including `"all"`.

## Item record

| Field            | Type     | Notes                                                         |
| ---------------- | -------- | ------------------------------------------------------------- |
| `name`           | string   | candidate display name                                        |
| `disposition`    | enum     | unchanged from v1                                             |
| `reason`         | string ∅ | required for `unresolvable`, `rejected_out_of_scope`, `error` |
| `kind`           | string ∅ | profile-defined; `movie`/`tv` for video, `book` for books     |
| `title`          | string ∅ | resolved title; null when unresolved                          |
| `details`        | object ∅ | profile-defined; omitted when the profile has nothing to add  |
| `destination`    | string ∅ | resolved/placed library path                                  |
| `actions`        | array ∅  | unchanged from v1                                             |
| `client_actions` | array ∅  | unchanged from v1                                             |

## Video profile

- `kind`: `"movie"` or `"tv"`.
- `details`: `{year}` for movies; `{season, episodes}` for TV, where
  `episodes` is an array of `[season, episode]` pairs.
- The existing `Movies/` and `TV/` destinations and category values
  (`movie`, `tv`, `all`) are unchanged.

## Books profile

- `kind`: `"book"`.
- `details`:

  | Key               | Type                | Notes                                                   |
  | ----------------- | ------------------- | ------------------------------------------------------- |
  | `author`          | string ∅            | null when unknown                                       |
  | `year`            | integer ∅           | null when unknown                                       |
  | `series`          | string ∅            | from Calibre/OPF or the filename grammar                |
  | `series_index`    | integer or number ∅ | series position                                         |
  | `format`          | string              | lowercase suffix without the dot                        |
  | `metadata_source` | string              | `epub`, `opf`, `filename`, or a `+filename` combination |

- Categories: `book`, `all`.
- Destination: `Books/<Author>/<Title> (Year)/`; `Unknown` author; year
  omitted when absent.

## Invariants

- `counts` always reconcile with `items`.
- No credentials, tokens, or password values appear anywhere in the record.
- `dry_run: true` records contain the full `actions` plan and match the
  subsequent real run field-for-field.
- `destination` and `actions[].to` are absolute display paths.
- A profile may add `details` keys, but must not change the envelope or the
  disposition enum.
