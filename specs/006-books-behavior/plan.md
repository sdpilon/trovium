# Implementation Plan: Books Series Prefixes and Sibling Metadata

**Feature**: `006-books-behavior` | **Date**: 2026-10-26 |
**Spec**: [spec.md](spec.md)

## Summary

Teach the books profile two related behaviors:

1. A leading `N - Title` or `N. Title` (integer 1–999, optional trailing
   year) is a series index, not an author.
2. A non-EPUB candidate without its own metadata reuses the embedded metadata
   of exactly one same-stem sibling EPUB in the same folder.

The change stays in the books profile, its tests, and a small additive
extension to the profile result type so an ambiguous sibling pairing can carry
a named reason. There is no new pipeline step, no new metadata reader, and no
new runtime dependency. `trovium-rename` keeps the numeric index in the
canonical filename when the series name is unknown.

## Technical Context

**Language/Version**: Python 3.13, managed with uv.

**Primary Dependencies**: none added. `httpx` remains the only runtime
dependency; parsing uses the standard library (`re`, `pathlib`, `zipfile`,
`xml.etree.ElementTree`).

**Storage**: filesystem only. Classification reads the candidate folder and,
for EPUB/OPF metadata, the existing capped readers. No database, no network.

**Testing**: pytest via `uv run pytest`; ruff, mypy strict, prettier,
markdownlint, and shellcheck through `scripts/check.sh`.

**Target Platform**: macOS development; Linux x86_64/aarch64 CI and deploy.
Sibling matching is case-sensitive at the `Path.stem` level. A test that needs
two same-stem EPUBs must skip on a filesystem that cannot hold them.

**Project Type**: single Python package with CLI entry points; the books
profile is the only media-specific code touched.

**Performance Goals**: no new target. Sibling discovery is one directory read
per non-EPUB candidate lacking own metadata, the same order as the existing
sidecar scan. EPUB reads keep their existing size caps.

**Constraints**: no new runtime dependency; no change to video or music; no
change to the #41 ambiguous-name behavior; record envelope and dispositions
unchanged; rename safety rules unchanged; deterministic output.

**Scale/Scope**: one source folder at a time; typical ebook folders hold a
handful of formats per book. A flat folder of thousands of books already pays
the same per-candidate directory scan for sidecars; this feature does not add
a cache or hidden state.

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

| Area                                                                       | Status | Notes                                                                                                       |
| -------------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------- |
| I–III (secrets, branch, commits)                                           | Pass   | No secrets; work stays on `006-books-behavior`; conventional commit at the end.                             |
| IV–IX (gates, policy, constitution)                                        | Pass   | No gate, policy, or constitution edits.                                                                     |
| X–XIII (worktree, scope, verification)                                     | Pass   | Only feature paths change; `scripts/check.sh` runs before the PR.                                           |
| XIV–XVIII (fail loudly, coverage, chokepoints)                             | Pass   | Ambiguity gets a named reason; each behavior gets tests; the books profile remains the only sibling lookup. |
| XIX–XXII (out of scope, projection, stop hook)                             | Pass   | No new capability; no `.specify`/`.opencode` edits; gate is green before handoff.                           |
| XXIII–XXVII (spec boundary, no coding before plan, steps, typing, adapter) | Pass   | Spec and plan exist before code; no new step; mypy/ruff stay green; no client changes.                      |
| Dependency budget                                                          | Pass   | `tests/unit/test_dependency_budget.py` stays unchanged.                                                     |

No violations; Complexity Tracking is not required.

## Research Decisions (Phase 0)

### Filename grammar decisions

- Match the numeric form before `_SERIES` and `_AUTHOR_TITLE` so
  `1 - Title (2020)` is a series entry, not author `1`. This follows the
  spec's "always a series index" rule.
- Use `^(?P<index>\d+)(?:\s+-\s+|\.\s+)(?P<title>.+)$` and then check
  `1 <= int(index) <= 999`. The range check, not a digit limit, excludes `0`,
  `1000`, and four-digit years while allowing leading zeros such as `0001` and
  `0999`. Requiring whitespace after the separator keeps `1.5 - Title` out;
  the spec documents `N - Title` and `N. Title`, not decimal or unspaced
  variants.
- Let `2020 - ...` and `1000 - ...` fall through unchanged; they match the
  digit run but fail the 1–999 range check.
- Treat everything after the prefix, except a trailing `(Year)`, as the
  title. This is the clarification recorded in the spec; a parenthetical
  non-year or an extra dash does not become an author.
- If the numeric prefix matches but the remaining title is empty, return
  `None` instead of falling through to a form that would reinterpret the
  number as a title.

### Sibling metadata decisions

- Pair on exact `Path.stem` equality and `.epub` suffix, within the primary
  file's parent. No fuzzy or case-folded matching; a different stem is not a
  sibling.
- Count every same-stem EPUB, not only readable ones. FR-004 says "exactly one
  such EPUB"; two candidates are ambiguous even if one is malformed.
- Only consult a sibling when the primary is non-EPUB and neither its
  embedded metadata nor a readable `metadata.opf` supplied anything. Own
  metadata wins wholesale; there is no field-level merge with the sibling.
- If the sole sibling EPUB is unreadable or has no usable metadata, fall back
  to the filename. A bad sibling is not a run-level failure.
- Keep one candidate per file, as today. Sibling lookup shares metadata but
  does not group or move the sibling file.

### Ambiguity reason decision

- Add an additive `Unresolved(reason)` result to the profile contract. The
  books profile returns it only when more than one same-stem EPUB exists;
  the engine emits it as the item's `unresolvable` reason.
- Existing profiles keep returning `Classification | None`; the union is
  covariant, so no behavior or signature change is required outside books.

### Rename decisions

- When `series` is known, keep the existing
  `Author - Series #N - Title (Year)` rule.
- When `series` is absent and `series_index` is present, use
  `N - Title (Year)` with the parsed integer. This is FR-010's canonical
  form. If sibling metadata supplied an author but no series name, the
  numeric form still wins and the author stays in the record and destination;
  this is the literal spec rule and is documented as a tradeoff below.
- When both `series` and `series_index` are absent, keep the existing
  `Author - Title (Year)` or `Title (Year)` rule.

## Architecture

```text
source entry
    |
    v
BooksProfile.groups  (one candidate per book file, sidecars attached)
    |
    v
BooksProfile.classify
    |-- parse_book_name: numeric form -> series_index, title, year
    |-- embedded EPUB metadata
    |-- own metadata.opf
    |-- same-stem sibling EPUB (if no own metadata)
    |-- ambiguous pairing -> Unresolved(reason)
    v
Classification  or  Unresolved  or  None
    |
    v
cli.process -> ItemRecord (unresolvable uses the named reason)
    |
    v
BooksProfile.destination -> Books/<Author>/<Title> (Year)/
    |
    v
trovium-rename -> BooksProfile.plan_names -> NamePlan
```

### Files

- `src/trovium/profiles/books.py`: numeric grammar, sibling lookup,
  metadata-source labels, numeric rename branch.
- `src/trovium/profiles/base.py`: the additive `Unresolved` result and the
  `classify` return type.
- `src/trovium/cli.py`: handle `Unresolved` before the generic `None` reason.
- `src/trovium/profiles/__init__.py`: export `Unresolved` with the other
  profile types.
- `tests/unit/profiles/test_books.py`: grammar, rename naming, and metadata
  cases.
- `tests/integration/test_books_ingest.py`: mixed folder, ambiguity, and
  record reasons.
- `tests/integration/test_rename_pipeline.py`: ingest-to-rename for a
  numbered file.
- `docs/profiles.md` and `README.md`: document the new grammar, sibling
  behavior, and `metadata_source` values.
- `specs/006-books-behavior/contracts/books-behavior.md`: the external
  contract addendum.

## Books Design

### Filename grammar

First match wins:

1. `N - Title` / `N. Title` (new): integer 1–999, optional `(Year)`.
2. `Author - Series #N - Title (Year)`.
3. `Title (Year) - Author`.
4. `Author - Title (Year)`.
5. `Title (Author)` (year optional).
6. `Title (Year)` (author unknown).

Examples:

| Input                               | Result                                                       |
| ----------------------------------- | ------------------------------------------------------------ |
| `01 - Sample Title`                 | title `Sample Title`, index `1`, author null                 |
| `0001 - Title`                      | title `Title`, index `1`, author null                        |
| `2. Another Title (2021)`           | title `Another Title`, index `2`, year `2021`                |
| `01 - Sample Title - Sample Author` | title `Sample Title - Sample Author`, index `1`, author null |
| `01 - Sample Title (Author)`        | title `Sample Title (Author)`, index `1`, author null        |
| `2020 - A Title`                    | falls through; `unresolvable`                                |
| `1000 - A Title`                    | falls through; `unresolvable`                                |
| `0 - A Title`                       | falls through; `unresolvable`                                |
| `1.5 - Title`                       | no numeric match; `unresolvable`                             |

`BookName` keeps its existing fields; the numeric form sets `title`, `year`,
and `series_index`, and leaves `author` and `series` `None`.

### Sibling metadata

- Discovery is a sorted scan of `primary.parent` for regular files whose
  suffix is `.epub` and whose `stem` equals `primary.stem`.
- Zero siblings: filename/OPF fallback as today.
- One sibling: read it with the existing `read_epub_metadata`; use it only if
  it returns usable metadata.
- More than one sibling: return
  `Unresolved("ambiguous sibling EPUB metadata for <file>: <names>")`; the
  candidate is `unresolvable`, and the other candidates in the folder keep
  their own classifications.
- The count is of same-stem EPUB files, not readable metadata: one valid and
  one malformed EPUB is still ambiguous, while a sole malformed EPUB falls
  back to the filename.
- Precedence: own embedded EPUB metadata, then own readable `metadata.opf`,
  then the sibling EPUB, then the filename. An unreadable own OPF is treated
  as absent.
- `metadata_source` becomes `epub+sibling` when only the sibling supplies
  fields, and `epub+sibling+filename` when the filename fills at least one
  missing field. Existing values (`epub`, `opf`, `filename`, and their
  `+filename` forms) are unchanged.
- No new readers for AZW3/MOBI embedded metadata; the existing EPUB/OPF
  readers are the only metadata sources. This matches the issue's AZW3
  "filename only" premise.

### Rename

`BooksProfile._base_name` gains one branch:

```text
series and index        -> Author - Series #N - Title (Year)
index, no series        -> N - Title (Year)
author, no index        -> Author - Title (Year)
neither                 -> Title (Year)
```

The numeric form uses `_format_index`, so `01` in the source becomes `1` in
the canonical name. Sidecars keep their names. Extensions are preserved.

Known tradeoff: if sibling metadata supplies an author while the filename
supplies only the index, the filename becomes `N - Title (Year)` and does not
repeat the author. The destination still carries the author. This follows
FR-010 literally; changing it would need a spec amendment.

### Ambiguity reason

`Unresolved` is a frozen dataclass with one `reason: str` field. In
`cli.process`, an `Unresolved` result produces an `unresolvable` item with
that reason; a `None` result keeps the existing
`"<profile> name grammar not confidently matched"` message. This gives the
ambiguous-sibling case a readable, specific reason without changing any other
profile or the record envelope.

## Project Structure

### Documentation

```text
specs/006-books-behavior/
├── spec.md
├── plan.md
├── contracts/
│   └── books-behavior.md
└── tasks.md                 # /speckit.tasks, not this command
```

### Source and tests

```text
src/trovium/
├── cli.py                   # Unresolved -> ItemRecord reason
└── profiles/
    ├── __init__.py          # export Unresolved
    ├── base.py              # Unresolved result type
    └── books.py             # grammar, sibling lookup, rename branch

tests/
├── unit/
│   ├── profiles/test_books.py
│   └── test_rename.py
└── integration/
    ├── test_books_ingest.py
    └── test_rename_pipeline.py

docs/profiles.md             # profile contract + books behavior
README.md                    # books grammar summary
```

**Structure Decision**: keep the existing single-package layout. The engine
gains only the result-type branch; all media decisions stay in
`profiles/books.py`.

## Contract Changes

- New `specs/006-books-behavior/contracts/books-behavior.md` extending the
  books record schema from
  `specs/003-media-profiles-books/contracts/record-schema.md` and the naming
  contract from
  `specs/004-profile-rename/contracts/profile.md`.
- Document the two new `metadata_source` values and the `Unresolved` result.
- No envelope, disposition, exit-code, or CLI option changes.
- `trovium-ingest`, `trovium-rename`, and `trovium-run` keep their current
  interfaces.

## Risks and Mitigations

| Risk                                                                    | Mitigation                                                                                                                |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| A numeric author (`100 - Title (2020)`) now parses as a series index    | Intended by FR-001; add a unit test pinning the precedence.                                                               |
| Two same-stem EPUBs cannot be created on a case-insensitive filesystem  | Unit-test the ambiguity branch by monkeypatching the sibling scan; gate the real-filesystem integration case with a skip. |
| Sibling lookup is O(files) per candidate in a flat folder               | Same order as the existing sidecar scan; no cache, no hidden state. Document the tradeoff.                                |
| A malformed sibling EPUB could fail the run                             | `read_epub_metadata` already returns `None` on any error; fall back to the filename.                                      |
| An unreadable own `metadata.opf` accidentally allows a sibling override | Treat an unreadable own OPF as absent, matching the current fallback; test it.                                            |
| Rename drops the author for an author-plus-index record                 | Literal FR-010; documented tradeoff; destination and record still carry the author.                                       |
| New profile result type ripples into every profile                      | The union is additive and covariant; only books returns `Unresolved`; mypy checks the rest.                               |

## Implementation Sequence

1. Add `Unresolved` to `profiles/base.py`, export it, and handle it in
   `cli.process` with a unit/integration test.
2. Add `_SERIES_INDEX` to `books.py` with the precedence and title rules;
   replace the obsolete `test_filename_numeric_prefix_is_unresolvable` and add
   the boundary cases.
3. Add sibling discovery and `metadata_source` handling; add unit tests for
   one sibling, missing fields, malformed sibling, own-OPF precedence, and
   ambiguity.
4. Add the numeric rename branch in `_base_name`; add unit and
   ingest-to-rename integration tests.
5. Update `docs/profiles.md`, `README.md`, and the new contract addendum.
6. Run the full `scripts/check.sh`, then generate tasks and acceptance blocks
   in the next command.

## Testing Strategy

- **Unit**: parser precedence and boundaries; title content after the prefix;
  numeric rename; sibling metadata source labels; ambiguity result; own-OPF
  precedence; malformed sibling fallback.
- **Integration**: disk ingest of the mixed EPUB/AZW3 folder; numbered files
  with and without a year; ambiguous pairing with a readable reason; ingest
  record piped into rename.
- **Contract**: books `details` shape, new `metadata_source` values, and the
  `unresolvable` reason; existing video/books record tests remain green.
- **Regression**: video tests, the #41 bare-dash case, existing EPUB/OPF
  precedence, and rename safety/collision tests.
- **Acceptance**: SC-001 through SC-004 as `accept` blocks in `tasks.md`;
  SC-005 is the full suite. The case-sensitive ambiguity block may skip on a
  filesystem that cannot hold two same-stem EPUBs; the unit test still proves
  the branch.

## Post-Design Constitution Check

Re-checked after the design above: no new dependency, no gate or projection
change, no new pipeline step, tests cover every behavior, and the record
contract stays additive. Pass.
