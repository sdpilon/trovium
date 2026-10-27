# Feature Specification: Books Series Prefixes and Sibling Metadata

**Feature Branch**: `006-books-behavior`

**Created**: 2026-10-26

**Status**: Complete

**Input**: Issue #42, split from #41. The parser defect is fixed separately;
this spec covers two behavior decisions for the books profile.

## Clarifications

### Session 2026-10-26

- Q: Should `N - Title` be treated as a series index? → A: Yes: an integer
  1–999, optional trailing year; the record author is null and the destination
  uses `Unknown`.
- Q: Which `metadata_source` value should a sibling EPUB use? → A:
  `epub+sibling` (with `+filename` when the filename fills a missing field).
- Q: Does a file's own metadata beat a sibling EPUB? → A: Yes; embedded
  metadata or its own `metadata.opf` wins.
- Q: When a file is named with a series number but no series name, how should
  `trovium-rename` name it? → A: Reuse the recognized form `N - Title (Year)`
  with the parsed integer; for example `1 - Sample Title.azw3`.
- Q: When one non-EPUB file matches more than one same-stem sibling EPUB,
  which records should become `unresolvable`? → A: Only the affected non-EPUB
  candidate; other files in the folder still resolve.
- Q: Does the `N - Title` form take an author from the filename, or is
  everything after the number part of the title? → A: Everything after the
  number is the title; only a trailing `(Year)` is special and the author is
  null.

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
4. **Given** `1000 - A Title.azw3`, **Then** the integer is outside 1–999, so it
   is not a series index and the name stays `unresolvable`.
5. **Given** `01 - Sample Title - Sample Author.azw3`, **Then** the title is
   `Sample Title - Sample Author`, the series index is `1`, and the author is
   null.

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
   non-EPUB candidate with more than one matching EPUB is `unresolvable` with a
   readable reason; the EPUBs keep their own metadata and the profile does not
   guess which EPUB belongs to which file.
4. **Given** a non-EPUB file with its own `metadata.opf`, **Then** the OPF wins
   over a sibling EPUB.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The filename grammar MUST recognize `N - Title` and `N. Title`
  as a series-index form when `N` is an integer from 1 to 999. This form is
  always a series index; it is not rejected for lacking a series name. An
  integer outside 1–999 falls through to the other documented forms.
- **FR-002**: That form MUST set `series_index`, leave `series` and `author`
  null, and accept an optional trailing `(Year)`. Only that trailing year is
  special; any other text after the prefix is part of the title.
- **FR-003**: A missing author MUST use the existing `Unknown` destination
  segment: `Books/Unknown/<Title> (Year)/`.
- **FR-004**: For a non-EPUB candidate without its own embedded metadata or
  `metadata.opf`, the profile MUST use a same-stem sibling EPUB's metadata when
  exactly one such EPUB exists.
- **FR-005**: The record MUST name the sibling EPUB as the metadata source with
  `metadata_source: "epub+sibling"`; when the filename also supplies a missing
  field, use `"epub+sibling+filename"`.
- **FR-006**: Ambiguous sibling pairing MUST make only the affected non-EPUB
  candidate `unresolvable` (or a named per-item error); other candidates in
  the folder keep their own classifications. The profile never guesses which
  EPUB belongs to which file.
- **FR-007**: Existing documented filename forms, the #41 ambiguous-name
  behavior, and EPUB/OPF precedence MUST remain unchanged.
- **FR-008**: The change MUST NOT add a runtime dependency.
- **FR-009**: A candidate's own embedded metadata or same-folder `metadata.opf`
  MUST take precedence over a sibling EPUB. When either is usable, the
  sibling is not consulted; this is not a field-level merge.
- **FR-010**: When a file is classified by the `N - Title` form and no series
  name is known, rename MUST use the canonical `N - Title (Year)` form with
  the parsed integer, omitting the year when it is absent. If metadata also
  supplies an author, the numeric form still wins for the filename; the
  author remains in the record and the destination.

### Key Entities

- **Series-index filename**: A leading integer plus a hyphen or period
  separator, an optional trailing year, and a title; no author or series name
  is implied, and any other text after the prefix belongs to the title.
- **Sibling format**: Two book files in one folder with the same filename stem
  and different extensions, at least one of which is an EPUB with metadata.
- **Metadata source**: The record field that says which input supplied the
  title, author, year, and series fields. The sibling EPUB case uses
  `epub+sibling`, or `epub+sibling+filename` when the filename fills a missing
  field.

## Success Criteria _(mandatory)_

- **SC-001**: `01 - Sample Title.azw3` lands under
  `Books/Unknown/Sample Title/` with `series_index=1`, and rename names it
  `1 - Sample Title.azw3`.
- **SC-002**: The mixed EPUB/AZW3 folder places both formats under
  `Books/Sample Author/Sample Title (2020)/`.
- **SC-003**: A non-EPUB candidate with more than one same-stem sibling EPUB is
  `unresolvable` with a readable reason, is not placed by guess, and does not
  make the EPUBs unresolvable.
- **SC-004**: The record names the metadata source for both formats, using
  `epub+sibling` for the AZW3.
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
- A file's own embedded metadata or `metadata.opf` wins over a sibling EPUB.
- Sibling stems match case-sensitively; a different case is a different stem.
