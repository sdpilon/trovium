# Data Model: Ingest Vertical Slice

**Feature**: `001-ingest-vertical-slice` | **Date**: 2026-10-17

Entities extracted from spec.md "Key Entities", typed for the implementing
language-agnostic core. Types are conceptual; concrete Python types land in
the implementation phase.

## Entities

### Candidate

One completed download or one `--source` child entry to be considered in a run.

| Field            | Type                                                                           | Validation / notes                                                  |
| ---------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| name             | string                                                                         | torrent name (client source) or entry name (source mode); non-empty |
| source           | enum {client, disk}                                                            | one run has exactly one value (FR-001)                              |
| files            | list of FileEntry                                                              | paths within the candidate; nested depth unbounded (FR-013)         |
| client_state     | enum {seeding_active_in_place, seeding_active_after_relocation, removed, none} | `none` for disk source                                              |
| completion_state | enum {complete, incomplete, n/a}                                               | disk source candidates are always complete                          |
| exposure         | enum {media, non_media, unresolvable}                                          | produced by classification (FR-002)                                 |

### Classification

The resolved meaning of a candidate's name(s).

| Field    | Type                           | Validation / notes                                                                                                                 |
| -------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| kind     | enum {movie, tv, unresolvable} | tv requires a series title + episode/season marker; movie requires a title marker; confidence rule: no guess on ambiguity (FR-002) |
| title    | string ∅                       | required unless kind = unresolvable                                                                                                |
| season   | integer ∅                      | tv pack may omit (whole series)                                                                                                    |
| episodes | set of (season, episode) ∅     | tv only                                                                                                                            |
| year     | integer ∅                      | optional refinement                                                                                                                |

**State transitions**: `unresolvable` is terminal for a run (candidate is
reported, never placed — Edge Cases).

### LibraryItem

A media entity placed (or already placed) in the library.

| Field       | Type                                         | Validation / notes                                                                        |
| ----------- | -------------------------------------------- | ----------------------------------------------------------------------------------------- |
| kind        | movie                                        | tv                                                                                        |
| destination | path                                         | derived from `--library-root` + layout convention; contains original-named files (FR-003) |
| files       | list of FileEntry                            | names identical to source-side (FR-003)                                                   |
| identity    | (kind, title, [season], composable name set) | convention identity used by already-handled detection (FR-004)                            |

### Disposition

The recorded outcome of one candidate in one run.

| Value                 | Meaning                                                        |
| --------------------- | -------------------------------------------------------------- |
| ingested              | placed fully; client marked handled after commit only (FR-010) |
| already_handled       | destination-identical library item exists (FR-004)             |
| not_yet_complete      | client source only; incomplete download skipped without error  |
| unresolvable          | name grammar not confidently matched; reported with the name   |
| rejected_out_of_scope | non-media content (samples, extras, unrelated files)           |
| error_with_reason     | named failure; consumed by `--on-fail` policy (FR-012)         |

**Lifecycle**: Candidate → Classification → (UNRESOLVED → disposition
unresolvable | RESOLVED → Placement attempt) → Disposition → entry in
RunSummary. Placement failure after partial fs write must leave the library
absent of a half item (FR-010 discipline).

### RunSummary

The stable record emitted every run (contracts/record-schema.md).

| Field    | Type                                             | Notes                            |
| -------- | ------------------------------------------------ | -------------------------------- |
| source   | enum {client, disk}                              | which mode ran                   |
| declared | {category, mode, on_fail, dry_run, library_root} | the run's declared options       |
| items    | list of ItemRecord                               | per-candidate disposition detail |
| counts   | per-disposition + total                          | derived, must equal items        |

ItemRecord: `{name, source, kind, classification ∅, destination ∅,
disposition, reason ∅}` — no secrets, no credentials, never raw environment
values (FR-012/constitution I).

### PlacementContext

The matrix inputs recorded in spec.md (Key Entities) that placement honors:
mode × filesystem relation × destination conflict × client state/policy.
Behavioral outcomes are in the placement matrix below.

## Behavior matrix (Draft contract)

| #   | Placement mode | FS relation  | Destination conflict                   | Disposition / behavior                                                           |
| --- | -------------- | ------------ | -------------------------------------- | -------------------------------------------------------------------------------- |
| 1   | move           | same volume  | none                                   | relocate (rename); disposition ingested                                          |
| 2   | move           | same volume  | identical content                      | relocate; disposition ingested (idempotent net-zero) reported as already_handled |
| 3   | move           | same volume  | same canonical name, different content | do not overwrite (Edge Cases); disposition error_with_reason naming the conflict |
| 4   | move           | cross volume | none per v2                            | copy + delete source; seed-safety warning in record                              |
| 5   | copy/hardlink  | —            | none                                   | original stays; disposition ingested                                             |
| 6   | copy/hardlink  | —            | identical content                      | original stays; disposition already_handled (no duplicate created)               |
| 7   | hardlink       | cross volume | none                                   | falls back to behavior of copy (FR-003), reason recorded                         |
| 8   | copy/hardlink  | —            | name clash, different content          | do not overwrite; disposition error_with_reason                                  |
