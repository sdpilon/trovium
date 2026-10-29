# Feature Specification: Profile-Driven Rename

**Feature Branch**: `004-profile-rename`

**Created**: 2026-10-21

**Status**: Complete

**Input**: User description: "rename the files ingest placed, using the
profile's naming rules, without breaking seeding or the ingest no-op rerun."

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Rename ingested books (Priority: P1)

A user ingests ebooks with `--mode move`, then pipes the ingest record into
`trovium-rename`. Each book file is renamed to `Author - Title (Year).ext` (or
`Author - Series #N - Title (Year).ext`); sidecars keep their names. Running
the same record again is a no-op.

**Why this priority**: Books are the first non-video profile and the clearest
naming case.

**Independent Test**: Ingest the books fixture, rename the emitted record,
verify the file names, then run rename again and verify `already_handled`.

**Acceptance Scenarios**:

1. **Given** an ingest record whose book has author, title, and year, **When**
   rename runs, **Then** the file becomes `Author - Title (Year).epub`.
2. **Given** a book with a series and index, **When** rename runs, **Then**
   the file becomes `Author - Series #N - Title (Year).epub`.
3. **Given** a book with no author, **When** rename runs, **Then** the file
   becomes `Title (Year).epub`.
4. **Given** a second run of the same record, **When** rename runs, **Then**
   the disposition is `already_handled` and no file changes.

---

### User Story 2 - Rename ingested video (Priority: P2)

A user ingests movies or TV with `--mode move`, then pipes the record into
rename. A single-file movie becomes `Title (Year).ext`; a TV episode becomes
`Show - S01E01.ext` (or `Show - S01E01-E02.ext` for a multi-episode file).
Files that cannot be named safely are reported as `skipped` with a reason.

**Why this priority**: It completes the first pipeline for the original video
slice.

**Independent Test**: Ingest a movie and a TV season, rename the record, and
verify the file names and the skipped multi-file cases.

**Acceptance Scenarios**:

1. **Given** a single-file movie with a year, **When** rename runs, **Then**
   the file becomes `Title (Year).ext`.
2. **Given** a TV episode file with an `SxxEyy` marker, **When** rename runs,
   **Then** the file becomes `Show - S01E01.ext`.
3. **Given** a movie folder with more than one media file, **When** rename
   runs, **Then** the item is `skipped` and no file changes.

---

### User Story 3 - Rename is safe and inspectable (Priority: P1)

A user can run rename with `--dry-run` to see the exact plan before changing
anything. Copy and hardlink ingests are renamed by default (feature 007);
renaming their library copy is safe because ingest recognizes the renamed file
by content on the next run. A client-relocated torrent is still refused,
because renaming the library file the client tracks breaks seeding; an
explicit `--allow-unsafe` override exists for a user who has stopped seeding
and removed the source.

**Why this priority**: Renaming files the client is seeding silently breaks the
pipeline's guarantees.

**Independent Test**: Run a dry-run, compare it with the real run, and verify
that a copy-mode record is renamed while a `setLocation` item is skipped.

**Acceptance Scenarios**:

1. **Given** a dry-run, **When** the same record is renamed for real, **Then**
   the actions match field-for-field and the files are renamed.
2. **Given** a copy/hardlink ingest record, **When** rename runs, **Then** the
   placed file is renamed and a later ingest recognizes it by content.
3. **Given** a client item whose record contains a `setLocation` action,
   **When** rename runs without `--allow-unsafe`, **Then** that item is
   `skipped` with a seeding reason.
4. **Given** a target name that already exists with different content,
   **When** rename runs, **Then** the item is `error`, no file is overwritten,
   and no partial rename is left behind.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: Rename MUST read an ingest record from stdin, or from
  `--record PATH` when supplied.
- **FR-002**: Rename MUST use the record's `declared.profile` to resolve a
  registered profile and MUST refuse an unknown or missing profile as misuse.
- **FR-003**: Each profile MUST provide `plan_names(classification, files)`
  returning one `NamePlan` per file: a target name, or `None` with a reason.
- **FR-004**: Books MUST be named `Author - Title (Year).ext`, or
  `Author - Series #N - Title (Year).ext` when series and index are present.
  A missing author omits the author segment; a missing year omits the year.
- **FR-005**: Video movies MUST be named `Title (Year).ext` when the
  destination holds exactly one media file. TV files MUST be named
  `Show - S01E01.ext`, extending to `-E02` for additional episodes parsed from
  the file name.
- **FR-006**: Non-member sidecars MUST keep their names.
- **FR-007**: `--dry-run` MUST emit the full plan and change nothing; the real
  run MUST produce the same actions.
- **FR-008**: Rename MUST be idempotent: a second run of the same record
  reports `already_handled` and changes nothing.
- **FR-009**: Rename MUST NOT overwrite an existing target. A collision marks
  the item `error`; no file in that item is renamed.
- **FR-010**: Rename MUST rename copy/hardlink records. It MUST skip a client
  item whose `client_actions` contains `setLocation` unless `--allow-unsafe` is
  given.
- **FR-011**: The rename record MUST echo `declared.profile`,
  `declared.library_root`, and `declared.mode`, and MUST include per-item
  `kind`, `title`, `details`, `destination`, `disposition`, `reason`, and
  `actions` so a rename record can itself be renamed again.
- **FR-012**: Malformed JSON, a missing `declared` object, non-object items,
  and an invalid target name (a name containing a path separator) MUST be
  misuse or an item error, never a partial rename.
- **FR-013**: Rename MUST use one action kind, `rename`, in the record.
- **FR-014**: Rename MUST stop after the first `error` when `--on-fail stop`
  is set; the default is `continue`.

### Key Entities

- **NamePlan**: One source file, its target name or `None`, and an optional
  reason.
- **Rename item**: One ingest item's rename outcome: `renamed`,
  `already_handled`, `skipped`, or `error`, with actions.
- **Rename record**: The JSON emitted by rename; the same shape as an ingest
  record for `declared`, `kind`, `title`, `details`, and `destination`, plus
  rename-specific dispositions.

## Success Criteria _(mandatory)_

- **SC-001**: An ingested books record renames every book to the documented
  pattern and preserves sidecar names.
- **SC-002**: An ingested movie and TV record rename to the documented video
  patterns; unsafe multi-file movies are `skipped`.
- **SC-003**: A dry-run plan matches the real run field-for-field.
- **SC-004**: A second rename of the same record is a no-op.
- **SC-005**: A copy/hardlink record is renamed without an override, and a
  `setLocation` client item is still skipped with a seeding reason.
- **SC-006**: A target collision leaves every file in that item untouched and
  is reported as `error`.

## Out of Scope

- Quality, codec, edition, or release-group tokens in names.
- Multi-file movies and TV files without an episode marker.
- Renaming outside a record's listed destinations, or scanning a library.
- Deleting duplicate files or reconciling content.
- A user-defined naming template or a rename DSL.

## Assumptions

- The record's destinations are absolute and already point at the library
  folders ingest created.
- Copy/hardlink renaming is safe because ingest compares destination content;
  only client-relocated items need `--allow-unsafe` after seeding stops.
- Naming is deterministic from the record's classification; rename does not
  call the classifier again.
