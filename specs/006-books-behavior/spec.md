# Feature Specification: Books Series Prefixes and Sibling Metadata

**Feature Branch**: `006-books-behavior`

**Created**: 2026-10-26

**Status**: Draft

**Input**: Issue #42, split from #41. The parser defect is fixed separately;
this spec covers two behavior decisions for the books profile.

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Numbered series files (Priority: P1)

A user has `01 - Sample Title.azw3` with no author or year in the filename. The
profile records it as a series entry: title `Sample Title`, series index `1`,
author unknown, year unknown, placed under `Books/Unknown/Sample Title/`.

**Why this priority**: A leading series number is a common ebook convention and
currently makes the file `unresolvable` after the #41 parser fix.

**Independent Test**: Run the books profile against the numbered files below
and verify the record details and destination.

**Acceptance Scenarios**:

1. **Given** `01 - Sample Title.azw3`, **When** ingest classifies it, **Then**
   the title is `Sample Title`, `series_index` is `1`, author and year are
   null, and the destination is `Books/Unknown/Sample Title/`.
2. **Given** `2. Another Title (2021).epub`, **Then** the series index is `2`,
   the title is `Another Title`, the year is `2021`, and the author is unknown.
3. **Given** `2020 - A Title.azw3`, **Then** the leading four-digit year is not
   treated as a series index and the name stays `unresolvable`.

---

### User Story 2 - Metadata across sibling formats (Priority: P1)

A user has one book in two formats in one folder: an EPUB with embedded
metadata and an AZW3 with only a filename. Both formats land in the same
destination, using the EPUB metadata for the AZW3.

**Why this priority**: The current per-file fallback can split one book into
two library folders, which breaks the profile's one-book-per-folder layout.

**Independent Test**: Create the mixed folder below and verify both records and
their destination.

**Acceptance Scenarios**:

1. **Given** `Sample Title - Sample Author.epub` with embedded metadata and
   `Sample Title - Sample Author.azw3` without metadata, **When** ingest runs,
   **Then** both resolve to `Books/Sample Author/Sample Title (2020)/`.
2. **Given** the same folder, **Then** the AZW3 record names the sibling EPUB
   as its metadata source.
3. **Given** a folder with two EPUBs and no unambiguous pairing, **Then** the
   unpaired formats are `unresolvable` with a readable reason; the profile does
   not guess which EPUB belongs to which file.
4. **Given** a non-EPUB file with its own `metadata.opf`, **Then** the OPF wins
   over a sibling EPUB.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The filename grammar MUST recognize `N - Title` and `N. Title`
  as a series-index form when `N` is an integer from 1 to 999.
- **FR-002**: That form MUST set `series_index`, leave `series` and `author`
  null unless the filename supplies them, and accept an optional trailing
  `(Year)`.
- **FR-003**: A missing author MUST use the existing `Unknown` destination
  segment: `Books/Unknown/<Title> (Year)/`.
- **FR-004**: For a non-EPUB candidate without its own `metadata.opf`, the
  profile MUST use a same-stem sibling EPUB's metadata when exactly one such
  EPUB exists.
- **FR-005**: The record MUST name the sibling EPUB as the metadata source,
  extending the documented `metadata_source` values.
- **FR-006**: Ambiguous sibling pairing MUST produce `unresolvable` (or a named
  per-item error), never a silent guess.
- **FR-007**: Existing documented filename forms, the #41 ambiguous-name
  behavior, and EPUB/OPF precedence MUST remain unchanged.
- **FR-008**: The change MUST NOT add a runtime dependency.

### Key Entities

- **Series-index filename**: A leading integer plus a hyphen or period
  separator, an optional trailing year, and a title; no author or series name
  is implied.
- **Sibling format**: Two book files in one folder with the same filename stem
  and different extensions, at least one of which is an EPUB with metadata.
- **Metadata source**: The record field that says which input supplied the
  title, author, year, and series fields; the sibling EPUB case needs a new
  documented value.

## Success Criteria _(mandatory)_

- **SC-001**: `01 - Sample Title.azw3` lands under
  `Books/Unknown/Sample Title/` with `series_index=1`.
- **SC-002**: The mixed EPUB/AZW3 folder places both formats under
  `Books/Sample Author/Sample Title (2020)/`.
- **SC-003**: Ambiguous sibling pairing is `unresolvable` with a readable
  reason and does not place either format by guess.
- **SC-004**: The record names the metadata source for both formats.
- **SC-005**: Existing books, video, and rename tests remain green.

## Out of Scope

- Grouping multiple different books in one folder beyond same-stem sibling
  formats.
- Inferring a series _name_ from a filename; only the numeric index is parsed.
- Changing video or music profiles.
- Reverting the #41 parser fix.

## Assumptions

- A leading integer 1–999 followed by a hyphen or period separator is a series
  index.
- Formats of one book share the same filename stem; a different stem is not
  paired automatically.
- A same-folder `metadata.opf` stays authoritative for its file.

## Open Questions

- Should `N - Title` always be a series index, or stay `unresolvable` when no
  series name is available?
- Should the sibling source be a new `epub+sibling` value, or reuse the
  existing `epub+filename` label?
- Should a sibling EPUB be ignored when the non-EPUB file has its own embedded
  metadata? (Recommendation: own metadata wins.)
