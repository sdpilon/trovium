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

### Hash scope for sameness (FR-004 detection)

Identity is resolved by convention first (kind, title, season, file-name
set). Within equal identity, size equality is checked before any hashing;
BLAKE2b content hash is computed only when sizes are equal. If sizes
differ, sameness is rejected without hashing. This bounds the cost of
already-handled detection on large libraries while remaining byte-accurate
where it matters (equal content always, and equal size but different
content hashes to different values and is reported as a collision per the
pinned behavior matrix).

### Classification

The resolved meaning of a candidate's name(s).

| Field    | Type                           | Validation / notes                                                                                                                 |
| -------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| kind     | enum {movie, tv, unresolvable} | tv requires a series title + episode/season marker; movie requires a title marker; confidence rule: no guess on ambiguity (FR-002) |
| title    | string ∅                       | required unless kind = unresolvable                                                                                                |
| season   | integer ∅                      | tv pack may omit (whole series)                                                                                                    |
| episodes | set of (season, episode) ∅     | tv only                                                                                                                            |
| year     | integer ∅                      | optional refinement                                                                                                                |

**Canonical grammar markers** (vocabulary of T005's matcher; anything falling
outside these, or matching ambiguously, resolves to `unresolvable` — the
never-guess rule):

- Movie: title tokens + optional 4-digit year (19xx/20xx) + quality marker
  (e.g. `1080p`, `720p`, `2160p`) + container/codec tokens (`x264`, `HEVC`,
  `mkv`) — e.g. `Movie.Production.2024.1080p-iGor`.
- TV episode: series title tokens + `SxxEyy` (or `S0xE0y` range) marker,
  optionally with a quality/codec suffix — e.g. `Shameless.US.S05E10.720p`.
- TV season/series pack: series title + `Sxx` alone, or a `Season N` phrase,
  contained in a directory holding two or more episode files — pack
  detection requires the file-count signal; a lone `Sxx` name resolves
  unresolvable.
- Resolution precedence when several marker sets fit: episode marker beats
  pack beats movie-with-year; no title tokens at all → `unresolvable`.
- Quality/codec/year tokens are extraction signals for the grammar only,
  never written into folder names by this step (FR-003 preserves names).

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

| Value                 | Meaning                                                                                                                          |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| ingested              | placed fully; client marked handled after commit only (FR-010)                                                                   |
| already_handled       | destination-identical library item exists (FR-004)                                                                               |
| not_yet_complete      | client source only; incomplete download skipped without error                                                                    |
| unresolvable          | name grammar not confidently matched; reported with the name                                                                     |
| rejected_out_of_scope | non-media content (samples, extras, unrelated files), or a candidate outside the declared category scope; the reason names which |
| error                 | named failure; reason required with this value; consumed by `--on-fail` policy (FR-012)                                          |

The record-schema spelling of the error disposition is `error` (T1
normalization), applied to the Disposition table and the behavior matrix
below; `error_with_reason` in the original spec bullet is thereby resolved
to the single canonical spelling, with `reason` required whenever `error`
is used.

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

## Behavior matrix (Pinned)

Conflict-outcome policy (authoritative; spec.md Edge Cases wording defers to
this table):

- Destination holds a file with IDENTICAL content (size + hash equal) to the
  candidate's file: the placement degrades to a verified no-op and the
  candidate is reported disposition `already_handled` — never re-copied,
  never silently replaced. In move mode the now-redundant source file is
  removed to complete the move-equivalent, and this is reported — except
  when the source _is_ the destination file (same inode), which is a pure
  no-op: nothing is removed and no `delete` action is planned.
- Destination exists with the same canonical name but DIFFERENT content: the
  step never overwrites and never auto-renames; the disposition is `error`,
  naming the collision path. The spec Edge Case wording's "replaces it
  deliberately" is always a caller-opt-in decision taken in a later step —
  never the default behavior of this step.
- Client seeding layout (decided scope boundary): move-mode `setLocation` is
  safe for single-file torrents. Multi-file torrents keep a flat library
  layout, which does not match the client's `<location>/<torrent name>/`
  expectation; seeding from the library is therefore not preserved for them.
  Use `--mode copy` or `--mode hardlink` for multi-file torrents; the
  placement's `client_actions[].detail` states this when it applies.

| #   | Placement mode | FS relation  | Destination conflict                   | Disposition / behavior                                                                                                          |
| --- | -------------- | ------------ | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 1   | move           | same volume  | none                                   | relocate (rename); disposition ingested                                                                                         |
| 2   | move           | same volume  | identical content                      | verified no-op (extra relocation is net-zero); disposition `already_handled`; now-redundant source removed and removal reported |
| 3   | move           | same volume  | same canonical name, different content | do not overwrite (Edge Cases); disposition `error` naming the conflict                                                          |
| 4   | move           | cross volume | none                                   | copy + delete source; seed-safety warning in record                                                                             |
| 5   | copy/hardlink  | —            | none                                   | original stays; disposition ingested                                                                                            |
| 6   | copy/hardlink  | —            | identical content                      | original stays; disposition already_handled (no duplicate created)                                                              |
| 7   | hardlink       | cross volume | none                                   | falls back to behavior of copy (FR-003); action records `op: "copy"` with a `note` naming the fallback                          |
| 8   | copy/hardlink  | —            | name clash, different content          | do not overwrite; disposition `error`                                                                                           |
