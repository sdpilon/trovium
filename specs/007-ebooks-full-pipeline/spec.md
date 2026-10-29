# Feature Specification: Ebooks Through the Full Pipeline

**Feature Branch**: `014-ebooks-full-pipeline`

**Created**: 2026-10-29

**Status**: Draft

**Input**: Make the books profile run the full pipeline: select the profile at install, ingest folder-shaped ebook torrents from qBittorrent, and rename the placed EPUBs end to end.

## Clarifications

### Session 2026-10-29

- Q: What are the default ingest modes? → A: Hardlink when a seeding torrent's source and destination share a filesystem; move for non-torrent or non-seeding sources; copy when a seeding source sits on another filesystem.
- Q: Does the adaptive default apply to every profile or only books? → A: Every profile and new installation; explicit modes keep their current behavior.

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Install a server for ebooks (Priority: P1)

An operator installs trovium on a server and selects the books profile. The
generated configuration already targets ebooks, so `trovium-run` needs no
per-invocation flags and the first downloaded book is handled as a book, not as
a video.

**Why this priority**: Without install-time selection the only way to run the
books pipeline on a server is to hand-edit `config.ini`, which makes the
supported path undiscoverable and untested.

**Independent Test**: Install non-interactively with the books profile, inspect
the generated config, and run the pipeline with no profile flag.

**Acceptance Scenarios**:

1. **Given** a fresh installation, **When** the operator installs with the
   books profile, **Then** the generated config records the books profile and
   the adaptive ingest default.
2. **Given** the same installation, **When** `trovium-run` runs without
   `--profile`, **Then** the record names the books profile and the pipeline
   classifies the input with the books grammar.
3. **Given** an installation request naming an unregistered profile, **Then**
   the install is refused with the list of registered profiles and no config is
   written.
4. **Given** no profile is requested, **Then** the install still produces the
   video profile with the existing defaults.

---

### User Story 2 - Download an ebook and find it named (Priority: P1)

A completed ebook torrent is a folder holding one EPUB, a `metadata.opf`, and a
cover image. One `trovium-run` places the book and its sidecars under
`Books/<Author>/<Title> (Year)/`, renames the EPUB to the canonical name, and
leaves the torrent seeding.

**Why this priority**: This is the full pipeline the feature exists to prove:
download client in, canonical library file out, in one command.

**Independent Test**: Drive the pipeline against a stubbed client and a
folder-shaped torrent, then inspect the library tree and the client calls.

**Acceptance Scenarios**:

1. **Given** a completed folder torrent with one EPUB and its sidecars,
   **When** `trovium-run` runs from a client-source config, **Then** the EPUB
   and every sidecar are placed under the book's destination and the EPUB is
   renamed to `<Author> - <Title> (Year).epub`.
2. **Given** the same run, **Then** the placed files are hardlinks when the
   torrent's files and the library share a filesystem, and copies when they do
   not; the torrent keeps seeding either way, and the client is not told to
   relocate, pause, or delete it.
3. **Given** the source EPUB carries embedded metadata, **Then** the embedded
   title, author, year, and series win over the filename, as the books profile
   already specifies.
4. **Given** a single-file EPUB torrent, **When** the pipeline runs in the
   adaptive default, **Then** the file is placed and renamed while the torrent
   keeps seeding. A move-mode single-file torrent is placed and the client
   relocated; rename stays skipped with its seeding reason.

---

### User Story 3 - Rerun without duplicates (Priority: P1)

The operator runs the pipeline again, for example from cron, while the torrent
still exists. Nothing is copied twice and nothing is renamed again.

**Why this priority**: The pipeline is meant to be run repeatedly. A second run
that duplicates a renamed book would make the default deployment unsafe.

**Independent Test**: Run the pipeline twice against the same source and
compare the library tree and the second record.

**Acceptance Scenarios**:

1. **Given** a book already placed and renamed, **When** the pipeline runs
   again, **Then** the item is reported as already handled and no new file is
   written.
2. **Given** the same rerun, **Then** the already canonical file is not renamed
   again and no collision is reported.

---

### User Story 4 - Refuse ambiguous shapes instead of guessing (Priority: P2)

A torrent that holds more than one distinct book cannot be split safely. The
pipeline says so and leaves the files and the client untouched.

**Why this priority**: Ebook torrents can hold a whole series; silently placing
the first book would put the wrong content in the library.

**Independent Test**: Drive the pipeline with a two-EPUB torrent and inspect the
record.

**Acceptance Scenarios**:

1. **Given** a completed torrent with two distinct EPUBs, **Then** the item is
   unresolvable with a reason naming the files, and nothing is placed.
2. **Given** a folder torrent in move mode, **Then** the existing refusal stays
   actionable and nothing is placed.

### Edge Cases

- A sidecar folder holds a cover image with an unusual name: sidecars are the
  ones the books profile already recognizes; unknown files are not carried.
- The destination already holds a file with the canonical name but different
  content: the existing collision error applies; nothing is overwritten.
- The torrent's folder contains a second book in the same format with the same
  stem: the books profile's existing sibling rules decide; the pipeline does
  not add a second rule.
- The source path is not visible on the host: the existing named error applies.
- The client reports the torrent as incomplete: the existing not-yet-complete
  disposition applies and rename does not run for it.
- A seeding torrent sits on a different filesystem from the library: it is
  copied, and the reason names the cross-filesystem fallback.
- A filesystem refuses a hardlink (permissions, unsupported filesystem): the
  item is copied with a reason and is not an error.
- A disk source is on the same filesystem as the library: it still moves,
  because move is the rule for non-torrent sources.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The install entry points (the deploy command and the release
  installer) MUST accept a profile name and MUST write it to
  `[ingest] profile` in the generated configuration. The default stays video.
- **FR-002**: An unregistered profile name MUST be refused before any config is
  written, with the registered names in the reason.
- **FR-003**: A new installation MUST default to an adaptive ingest mode for
  every profile. A disk entry, or a torrent whose files are not seeding, moves.
  A seeding torrent hardlinks when its files and the destination share a
  filesystem, and copies when they do not. Explicitly selected modes keep
  their current behavior, and the operator can still change the mode in the
  config.
- **FR-004**: In client mode, a completed torrent holding one book MUST place
  that book together with the sidecars the books profile recognizes, using the
  same classification and destination rules as a disk entry.
- **FR-005**: `trovium-run` MUST rename copy and hardlink placements without
  requiring an override flag, because the library entry is independent of the
  torrent's own path. Client-relocated (move-mode) items MUST keep the existing
  skip and its seeding reason.
- **FR-006**: Ingest MUST treat a library file as the same item when its
  content matches a source file in the destination, even when the name differs
  because a previous run renamed it. A rerun MUST report the item as already
  handled and MUST NOT place a duplicate.
- **FR-007**: Rename MUST remain non-destructive: it never overwrites an
  existing target and a same-name, different-content target stays a collision.
- **FR-008**: A torrent that yields more than one book MUST be reported as
  unresolvable, with the files named, and MUST leave both the library and the
  client unchanged.
- **FR-009**: The existing refusal for folder torrents in move mode MUST keep
  its actionable reason and MUST place nothing.
- **FR-010**: The change MUST NOT add a runtime dependency, and existing video,
  books, rename, run, and deploy behavior MUST remain covered.
- **FR-011**: When a hardlink is attempted and the filesystem refuses it, the
  item MUST be copied with a reason naming the fallback; the item is not an
  error.

### Key Entities

- **Profile selection**: The install-time choice that becomes the configured
  `[ingest]` profile; it determines classification, naming, and the mode
  default.
- **Client candidate**: One completed torrent expanded through a profile into
  the files the pipeline may place.
- **Sidecar**: A recognized companion file (`metadata.opf`, `cover.*`, `.nfo`)
  that travels with its book and keeps its own name.
- **Placement identity**: The evidence that a source file already exists in the
  destination. Content, not only the source name, survives a rename.

## Success Criteria _(mandatory)_

- **SC-001**: An installation with the books profile writes the books profile
  and the adaptive ingest default; installing without a profile still writes
  the video profile with that same adaptive default; an unknown profile is
  refused with the registered names and writes nothing.
- **SC-002**: One `trovium-run` from a client-source books config places a
  folder torrent's EPUB and sidecars, renames the EPUB to
  `<Author> - <Title> (Year).epub`, and leaves the torrent seeding; the placed
  files are hardlinks on a shared filesystem and copies across filesystems.
- **SC-003**: A second identical run reports the item as already handled, adds
  no files, and does not rename again.
- **SC-004**: A two-book torrent is unresolvable with both files named, and a
  folder torrent in move mode keeps its actionable refusal; in both cases
  nothing is placed.
- **SC-005**: The existing video, books, rename, run, and deploy suites remain
  green and no runtime dependency is added.

## Out of Scope

- Multi-profile configuration (several profiles in one install); this slice
  keeps one active profile per config.
- Indexer search, metadata providers, save/follow/monitor, and deletion; those
  are later slices.
- Splitting a multi-book torrent into several items; it is a named refusal.
- Changing the books filename grammar, series naming, or sidecar rules.
- A new download client.

## Assumptions

- Ebook torrents are commonly folders holding one book plus sidecars, and
  occasionally a single file.
- The qBittorrent adapter reports a completed torrent as seeding, so client
  items take the hardlink-or-copy branch; disk entries take move.
- Same filesystem means the source and the nearest existing destination
  ancestor share a device.
- Content identity (size plus digest) is sufficient to recognize a renamed
  library copy for rerun idempotency.
- `copy` and `hardlink` leave the torrent's own files in place, so renaming the
  library copy does not affect seeding.
- The existing `--allow-unsafe` override remains for move-mode client items and
  any manual rename the operator chooses.
- The books profile's existing metadata precedence and sidecar rules from
  specification 006 are unchanged.
