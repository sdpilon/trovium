# Feature Specification: Media Profiles and Books

**Feature Branch**: `003-media-profiles-books`

**Created**: 2026-10-21

**Status**: Complete

**Input**: User description: "trovium should support arbitrary media types
through profiles. Books are the second profile, and a developer should be able
to add another profile without changing the ingest engine."

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Ingest ebooks from a directory (Priority: P1)

A user has ebooks in a downloads directory. They run the ingest step with
`--profile books` and a library root. Each ebook is classified as a book,
placed under an author and title folder, and reported in the JSON run record.
Original filenames are preserved.

**Why this priority**: It is the first non-video media type and the real test
of whether the profile boundary works.

**Independent Test**: Point `--profile books --source` at a fixture directory
containing an EPUB with embedded metadata, a filename-only PDF, a multi-book
folder, and an ambiguous file. Verify the destinations, record fields, and a
no-op second run.

**Acceptance Scenarios**:

1. **Given** an EPUB with title and creator metadata, **When** ingest runs,
   **Then** the book lands under `Books/<Author>/<Title> (Year)/` and the
   record reports `metadata_source: "epub"`.
2. **Given** a PDF whose name is `Author - Title (Year).pdf`, **When** ingest
   runs, **Then** it lands under the same layout using the filename grammar.
3. **Given** a name the grammar cannot resolve confidently, **When** ingest
   runs, **Then** the item is `unresolvable` with a readable reason and
   nothing is moved.
4. **Given** a successful first run, **When** the same run repeats, **Then**
   no files are duplicated and the item is `already_handled`.

---

### User Story 2 - Existing video ingest is unchanged (Priority: P1)

A user who already runs `trovium-ingest` for movies and TV keeps the same
options, destinations, dispositions, and record fields.

**Why this priority**: The profile refactor must not regress the shipped
behavior.

**Independent Test**: Run the existing video unit, contract, and integration
suites. Verify `--category movie|tv|all`, `Movies/`, `TV/`, dry-run parity, and
the record's `kind` values are unchanged.

**Acceptance Scenarios**:

1. **Given** the video fixtures, **When** ingest runs without `--profile`,
   **Then** behavior and destinations are identical to the previous release,
   with only the additive `declared.profile` record field.
2. **Given** `--category tv`, **When** ingest runs, **Then** only TV items are
   ingested and movie items are reported out of scope.

---

### User Story 3 - Add a profile without engine changes (Priority: P2)

A developer wants to support a new file type, for example Linux distribution
images. They write a profile module that says which files belong to a
candidate, how to classify them, and where they belong, then register it. The
ingest engine, placement, conflict handling, and record envelope stay
untouched.

**Why this priority**: It is the project's core promise and prevents every new
media type from becoming a new application.

**Independent Test**: A test-only `distros` profile classifies
`ubuntu-24.04.1-live-server-amd64.iso` and places it under
`Distros/Ubuntu/24.04.1/amd64/` through the same engine functions used by the
shipped profiles.

**Acceptance Scenarios**:

1. **Given** a registered `distros` profile, **When** the engine ingests an
   ISO source, **Then** it places the file by the profile's layout with no
   engine branch for distros.
2. **Given** an unregistered profile name, **When** the CLI runs, **Then** it
   refuses as misuse and lists the available profiles.

---

### Edge Cases

- An EPUB is missing, malformed, or has no OPF metadata: fall back to the
  filename grammar; never abort the whole run.
- A book file has a title but no author: place it under `Books/Unknown/`.
- A book has no year: omit the parenthesized year.
- A folder contains one book plus `cover.jpg` and `metadata.opf`: the sidecars
  travel with the book. A folder with several books yields one candidate per
  book and ignores unattributable sidecars.
- The same book exists in two formats: both files may coexist in the same
  destination folder; they are distinct files, not duplicates.
- A client torrent contains several books: it is one candidate in this slice;
  multi-book torrents are a documented limitation.
- A profile name is valid but the requested category is not one of its
  categories: refuse as misuse and name the allowed values.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The ingest engine MUST delegate profile-specific decisions to a
  `Profile` implementation: file membership, incidental files, candidate
  grouping, classification, and destination resolution.
- **FR-002**: The engine MUST own sources, placement, conflict handling,
  idempotency, client actions, and the record envelope, and MUST NOT branch on
  a built-in media type.
- **FR-003**: The video profile MUST preserve the existing CLI defaults,
  destinations, dispositions, and record field values.
- **FR-004**: The books profile MUST ingest `.epub`, `.pdf`, `.mobi`, `.azw`,
  `.azw3`, `.fb2`, and `.djvu` files from the disk source.
- **FR-005**: Books grouping MUST yield one candidate per book file, except
  that a folder holding exactly one book file also carries its recognized
  sidecars (`cover.*`, `metadata.opf`, `*.nfo`).
- **FR-006**: Books classification MUST prefer EPUB OPF metadata (title,
  creator, date, Calibre series and series index), then a `metadata.opf`
  sidecar, then a conservative filename grammar. The record MUST name the
  source that won.
- **FR-007**: A book whose title cannot be resolved confidently MUST be
  `unresolvable`; the profile MUST NOT guess.
- **FR-008**: Books destination MUST be
  `Books/<Author>/<Title> (Year)/`, using `Unknown` when the author is absent
  and omitting the year when it is absent. Original filenames are preserved.
- **FR-009**: The run record MUST add `declared.profile` and an optional
  per-item `details` object. Existing video fields and values MUST remain
  compatible.
- **FR-010**: The CLI MUST accept `--profile`; the default MUST remain
  `video`. Category choices MUST come from the selected profile.
- **FR-011**: Configuration MUST accept `[ingest] profile`, defaulting to
  `video`, and MUST validate `[ingest] category` against that profile.
- **FR-012**: A new profile MUST be addable by implementing the profile
  contract in one module and registering it; no engine change. A test-only
  `distros` profile MUST prove this.
- **FR-013**: Books client mode is disk-first; one torrent is one candidate.
  Multi-book torrents are a documented limitation in this slice.
- **FR-014**: EPUB metadata parsing MUST read only the archive's metadata,
  cap the bytes read, resolve no external entities, and fall back to the
  filename on any parse failure. It MUST NOT modify the book.

### Key Entities

- **Profile**: A media-type module. Owns membership, grouping, classification,
  destination, and (later) naming. Built-ins: `video`, `books`.
- **Candidate group**: One candidate's display name and the files that travel
  with it. Video yields one group per source entry; books yield one per book.
- **Classification**: The profile name, a profile-defined kind, a title, and
  a details map (year, author, series, season, episodes, metadata source).
- **Book**: A single ebook file, optionally with sidecars, classified by
  embedded metadata or its filename.

## Success Criteria _(mandatory)_

- **SC-001**: All existing video tests pass, and video destinations and record
  `kind` values are unchanged.
- **SC-002**: A fixture directory of EPUB and PDF books is ingested to the
  documented layout with original filenames preserved.
- **SC-003**: EPUB metadata wins over a misleading filename, and the record
  reports which source was used.
- **SC-004**: Ambiguous book names are `unresolvable` with a reason, and a
  second run is a no-op.
- **SC-005**: The `distros` fixture ingests an ISO through the engine with no
  engine changes.
- **SC-006**: A malformed EPUB falls back to the filename and does not abort
  the run.

## Out of Scope

- Comics (`.cbz`/`.cbr`) and audiobooks (`.m4b`/`.mp3`) as separate profiles.
- File renaming; that is the next pipeline step.
- External metadata services or network lookups.
- Downloading or browsing distro images; that is a future pipeline step.
- A user-defined rule DSL, plugin discovery, or sandboxing.
- Multi-book client torrents and client-mode books beyond one book per torrent.

## Assumptions

- The library root is shared across profiles; `Books/` is a subdirectory,
  consistent with `Movies/` and `TV/`.
- EPUB OPF metadata is trusted as the primary source; a missing or malformed
  archive is a normal fallback case, not a run-level failure.
- The books filename grammar is intentionally conservative; unrecognized
  names are surfaced rather than guessed.
- The `distros` profile is a test fixture and documentation example, not a
  shipped profile in this feature.
