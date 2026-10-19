# Feature Specification: Ingest Vertical Slice

**Feature Branch**: `001-ingest-vertical-slice`

**Created**: 2026-10-17

**Status**: Draft

**Input**: User description: "the `ingest` vertical slice"

## Clarifications

### Session 2026-10-17

- Q: Which options should the ingest command accept on the command line when it is run? → A: Explicit full flag set: `--client-url`, `--category {movie|tv|all}`, `--library-root <path>`, `--dry-run`, `--post-ingest {keep|pause|delete}`, `--on-fail {stop|continue}`, `--json`; client URL/credentials may also come from environment variables.
- Q: When placing an ingested item into the library, should the step move its files out of the download location or copy them and leave the originals? → A: Per-run option `--mode {move|copy|hardlink}`, default `move`.
- Q: What should the ingest command emit on standard output after a run — and in what format? → A: Stable machine-readable JSON on stdout by default; `--json {compact|pretty}` selects the formatting of that same data.
- Q: When a torrent has already been ingested and then removed from the download client, how should the step recognize that its media is already handled on a later run? → A: Convention-based — the step resolves the candidate's destination and treats an existing matching library item as already handled, with no extra stored state.
- Q: What should `--on-fail {stop|continue}` default to when the option is not given? → A: `continue` — a failed item is reported with a named reason and the run proceeds to other items.
- Q: Should 2026 ingest also accept media that already exists on disk without any download client — a local directory as the source of candidates — or is that left for a later feature? → A: In scope as a second source: `--source <path>` reads candidates from a local directory; it is mutually exclusive with `--client-url`, and client-only options do not apply. The on-disk case is the primary, most essential use case.
- Q: Given a `--source` directory, what should the step treat as one candidate to ingest? → A: Each direct child of `--source` (file or directory) is one candidate, and one candidate's contents may include arbitrarily nested media files that travel together as one item.
- Q: Where does the renaming boundary sit for this step — does ingest name files and folders as it places them, or does it place things with original names and defer all renaming to a later step? → A: Ingest preserves original filenames and only decides the folder structure (show/season/movie folders); file renaming is entirely another step's concern, to be handled with care around seeding (`move|copy|hardlink` interplay, files actively being seeded).

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Ingest media already on disk (Priority: P1)

A user has media files sitting on disk — a downloads directory, an external
drive, a hand-gathered folder of files — with no download client in the
picture. They run the ingest step with `--source <path>`; the step reads the
media candidates from that location, classifies each as a movie or a TV
episode/season, places it into the library in its proper destination, and
emits a machine-readable summary of the run.

**Why this priority**: The user identified on-disk media without a client as
the most essential case and a direct personal need; it also exercises the
same classification and placement core the client source reuses.

**Independent Test**: Can be fully tested by pointing `--source` at a known
directory of media files and verifying the resulting library layout plus the
emitted summary — with no client involved at all.

**Acceptance Scenarios**:

1. **Given** a source directory containing a demonstrably complete media item
   (a movie release or a TV season), **When** ingest runs with `--source`,
   **Then** the item is placed in the library under the correct target folder
   with its file(s) intact and the summary lists it as ingested.
2. **Given** the source directory also contains non-media or unresolvable
   content, **When** ingest runs, **Then** those candidates are left
   untouched and reported as unresolvable or rejected with a reason.
3. **Given** ingest runs again with no changes to the source or library,
   **When** the second run finishes, **Then** no items are duplicated, moved,
   or reprocessed, and the summary reports handling nothing new.
4. **Given** `--source` is supplied together with `--client-url` (or a
   client-only option such as `--post-ingest`), **When** ingest starts,
   **Then** the run is refused as a misuse with an explicit named error
   before any work happens.

---

### User Story 2 - Ingest completed downloads from qBittorrent (Priority: P2)

A user runs the ingest step after downloads have finished in their qBittorrent
client. The step connects to the client, identifies completed downloads that
are media, and moves or copies each into the user's library in its proper
destination (per-show or per-movie folder), then emits a structured summary
of what it did so the next pipeline step (or the user) can inspect the outcome.

**Why this priority**: Carries the proven disk-source core (classification,
placement, idempotency) into the unattended central workflow — the value the
project's ingest headline builds on — once the simpler source is proven.

**Independent Test**: Can be fully tested by pointing the step at a client
instance with a known set of completed (and, as a control, incomplete)
downloads and verifying the library layout afterwards plus the emitted
summary.

**Acceptance Scenarios**:

1. **Given** qBittorrent holds a completed, seeded media download, **When**
   ingest runs, **Then** the item is placed in the library under the correct
   target folder with its file(s) intact, is marked handled in the client, and
   the summary lists it as ingested.
2. **Given** a download is actively downloading or incomplete, **When** ingest
   runs, **Then** the item is left untouched, not classed as an error, and the
   summary states it was skipped as not yet complete.
3. **Given** ingest runs twice with no new completed downloads in between,
   **When** the second run finishes, **Then** no items are duplicated, moved,
   or reprocessed, and the summary reports handling nothing new.
4. **Given** the client is unreachable or credentials are wrong, **When**
   ingest runs, **Then** the run fails with an explicit error naming the cause
   and exits non-success; nothing is partially ingested silently.

---

### User Story 3 - Filter which candidates are ingested (Priority: P3)

A user wants to limit a run — e.g. only movies, only one specific candidate,
or everything — and passes that intent to the ingest step. The step processes
only matching candidates from whichever source the run declared, and reports
the declared scope in its summary.

**Why this priority**: Users need control over a run before trusting it
unattended; it refines Story 1 without changing its core.

**Independent Test**: Can be tested by running ingest with different scope
selections against a fixture source (client or directory) containing several
candidates of different kinds and verifying exactly the selected items were
touched.

**Acceptance Scenarios**:

1. **Given** candidates of both a movie and a TV episode exist, **When** ingest
   runs scoped to one category, **Then** only items of that category are
   ingested and the other is left untouched.
2. **Given** no candidates match the selector, **When** ingest runs,
   **Then** it succeeds, reports an empty result clearly, and touches nothing.

---

### User Story 4 - Plan without changing anything (Priority: P4)

A user wants to see what ingest _would_ do before letting it do it. The step
can be run in an inspect-only mode that emits precisely the actions it would
take, while making no changes to the source or the library.

**Why this priority**: Builds trust and supports dry-run verification in
automation, but delivers value only after Stories 1–2 work.

**Independent Test**: Can be tested by running the step in inspect-only mode
against a fixture source (client or directory) with candidates and verifying
the emitted plan is exact and both the source and library are unchanged.

**Acceptance Scenarios**:

1. **Given** candidates exist in the declared source, **When** ingest runs in
   inspect-only mode, **Then** it emits a per-item action plan and neither the
   source (client or directory) nor the library is modified.
2. **Given** the same state, **When** ingest runs in inspect-only mode and then
   for real, **Then** the executed outcome matches the previously emitted plan
   item-for-item.

---

### Edge Cases

- What happens when a media name cannot be confidently parsed (ambiguous or
  unlabeled title)? The item is not guessed at: it is skipped and surfaced in
  the summary as unresolved for the user to handle.
- What happens when the target library location already contains an identical
  file? The placement degrades to a verified no-op and the item is reported
  as `already_handled` — never re-copied, never silently replaced; in move
  mode the now-redundant source file is removed and this removal is
  reported. A same-name different-content collision is never overwritten by
  default: it is reported as an error naming the conflicting path; replacing
  deliberately is always a caller-opt-in decision taken in a later step,
  not this step's default.
- What happens when a candidate (download or source entry) is not a media item
  (a release containing extras, samples, or unrelated files)? Non-media
  content is not ingested; the summary says why.
- What happens when a download is finished but another client-side state (still
  seeding with post-ingest removal policy unset) makes handling ambiguous? The
  step's client-facing behavior is explicit in its summary rather than assumed.
- What happens when the destination path is unwritable or on a volume that is
  unavailable? The run fails for that item with a named reason, continues or
  stops per the declared failure behavior, and never claims success for the
  item.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The ingest step MUST obtain its candidates through one declared
  source in a run: the download client via the project's single client adapter,
  acquiring completed downloads (`--client-url`), or media already on the
  local filesystem (`--source <path>`), treating the latter as the primary,
  essential case. The two sources are mutually exclusive in one run.
- **FR-002**: The ingest step MUST classify each candidate as a movie, a TV
  episode/season, or unresolvable, using only the candidate's own name(s) and
  file layout (torrent metadata in client mode; entry/file names in disk mode)
  rather than any external lookup service (scope of this slice).
- **FR-003**: The ingest step MUST place each classified, resolvable item into
  its library destination as flat, readable files (directories a person can
  navigate), preserving complete and playable media content. File names of the
  placed media MUST be preserved exactly as ingested — renaming is not this
  step's concern and out-of-place file changes could break verified seeding —
  but destination _folder_ names (per show/season/movie) are derived by this
  step per the declared library layout. Placement uses the declared `--mode`:
  with `move` (the default) the files are relocated out of the download
  location; with `copy` or `hardlink` the original download files remain in
  place (a hardlink shares storage only when the source and destination are on
  the same filesystem, otherwise behaving as copy). **Client-mode exception**:
  with `--mode move`, a **folder torrent** (the client reports a `root_path`
  directory, including one holding a single video plus sidecars) is refused as
  a per-item error recommending `--mode copy` or `--mode hardlink`; the client
  expects `<save_path>/<torrent name>/` and the flat layout would break
  seeding. An already-handled folder torrent is a no-op with source removal
  suppressed. The refusal is evaluated after classification and category
  scope.
- **FR-004**: The ingest step MUST NOT double-handle media it has already
  ingested, whether the candidate is still present in the declared source (the
  client or the source directory) or no longer is. Recognition is
  convention-based and stateless: on each run the step
  resolves the candidate's library destination by the same rules it would use
  to place it, and an existing matching item in the library determines the
  already-handled disposition — no ledger or stored state is consulted or
  maintained.
- **FR-005**: The ingest step MUST support limiting a run by category (movies
  only, TV only, or all).
- **FR-006**: The ingest step MUST run without making any change to the
  declared source (the download client in client mode, the source directory
  in disk mode) or to the library when invoked in its inspect-only mode
  (`--dry-run`), and MUST emit exactly the actions it would otherwise take.
- **FR-007**: The ingest step MUST emit a stable, machine-readable summary on
  standard output after every run — per-item disposition using exactly the
  canonical enum `ingested`, `already_handled`, `not_yet_complete`,
  `unresolvable`, `rejected_out_of_scope`, `error` (with `reason` required
  whenever `error` is used), plus counts — as machine-readable JSON by default,
  with the `--json {compact|pretty}` option selecting the formatting of that
  same data (contracts/record-schema.md is authoritative).
- **FR-008**: The ingest step MUST fail with an explicit named error when the
  client is unreachable or credentials are invalid and MUST NOT report any
  success in that run.
- **FR-009**: The ingest step MUST be re-runnable at any time with no hidden
  state: all decisions it makes on a run derive from the declared source's
  state (the download client in client mode, the source directory in disk
  mode), the library contents, and any explicitly declared run options — never
  from memory between runs.
- **FR-010**: The ingest step MUST NOT mark a download as handled in the
  client unless its library placement for that item has fully succeeded.
- **FR-011**: All handling of qBittorrent must be confined to the single
  qBittorrent adapter; if a different client is added later, ingest itself
  must not change.
- **FR-012**: The ingest step MUST accept its per-run configuration through an
  explicit command-line option set: `--client-url`, `--category {movie|tv|all}`
  (default `all`, satisfying FR-005), `--library-root <path>` (declaring the
  library destination), `--dry-run` (enabling the inspect-only mode of FR-006),
  `--post-ingest {keep|pause|delete}` (declaring the client-side policy;
  default `keep`), `--mode {move|copy|hardlink}` (declaring placement
  semantics; default `move`), `--on-fail {stop|continue}` (declaring
  per-item failure behavior; default `continue` — a failed item is reported
  with a named reason and the run proceeds), and `--json {compact|pretty}`
  (declaring the formatting of the machine-readable summary emitted by FR-007).
  The client URL and credentials MUST also be readable from environment
  variables, and credentials MUST never be placed on the command line or in
  the emitted summary.
- **FR-013**: When invoked with `--source <path>`, the ingest step MUST source
  its candidates from the filesystem, applying the same classification
  (FR-002), placement (FR-003), and idempotency (FR-004) rules as the client
  source; concepts that exist only with a client — incompletion, and the
  `--post-ingest` policy — MUST NOT apply, and combining `--source` with
  `--client-url` or `--post-ingest` MUST be refused as a misuse with an
  explicit named error before any work happens. Each direct child entry of
  `--source` (a file or a directory) is exactly one candidate, and a
  candidate's contents may include arbitrarily nested media files that move
  or copy together as one library item. A `--source` path that is missing, not
  a directory, or unreadable is refused as a misuse before any work; a read
  failure on a candidate's files during placement is a per-item `error` with a
  named cause, governed by `--on-fail`.

### Key Entities _(include if feature involves data)_

- **Candidate**: One completed download as observed in the client, or one
  direct child entry of `--source`. Attributes: name, category/volume (client
  mode), completion state (client mode; disk candidates are always complete),
  resolved classification (movie/TV/unresolvable), and its disposition this
  run.
- **Library item**: The media entity placed in the library. Attributes: kind
  (movie or episode/season), resolved title, placement path, and file(s)
  making up the item.
- **Disposition**: Outcome of one candidate in one run, using the canonical
  enum: `ingested` / `already_handled` / `not_yet_complete` / `unresolvable` /
  `rejected_out_of_scope` / `error` (reason required with `error`).
- **Run summary**: The emitted record of one run: declared scope, plan (when
  inspect-only), per-candidate dispositions, total counts, and errors.
- **Placement context**: The variables whose values jointly determine a
  placement's required behavior (the material for behavior matrices):
  `--mode` (move | copy | hardlink); client state of the item's files during
  and after ingest (seeding-active in place, seeding-active after relocation,
  removed from client, or no client involvement); client policy after ingest
  (keep | pause | delete); destination-name conflict type (identical content,
  different content with the same canonical name, or no conflict); and same-
  filesystem vs cross-filesystem placement (affects hardlink sharing and
  move-as-rename availability). Renaming is fixed as never-performed here;
  the future renaming step inherits these outcomes.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: A user can get media into a correctly organized library with a
  single ingest run — from a full download client (Story P2) or directly from
  a directory of on-disk media (Story P1) — in under a minute for a library
  of dozens of items.
- **SC-002**: Running ingest repeatedly produces no duplicates and no changes
  on the second and later runs — 100% idempotent re-runs in testing.
- **SC-003**: Every item the step does not ingest is reported with a reason
  the user can read and act on; zero items are silently skipped.
- **SC-004**: The emitted run summary is sufficient for a user (or the next
  pipeline step) to reconstruct what happened without looking at the library
  or the declared source again.
- **SC-005**: Running ingest in inspect-only mode and then for real produces
  byte-identical outcomes, verified in testing.

## Assumptions

- The sources in this vertical slice are the qBittorrent adapter and the
  local filesystem (`--source`), the latter being the primary, essential use
  case. Other download clients are out of scope and, per the constitution,
  will be absorbed into the single adapter when they arrive.
- Media title parsing in this slice uses only information available inside the
  candidate itself — the torrent name and file list in client mode, the entry
  name and nested file names in disk mode (no title-quality/edition lookup
  services). Ambiguous or unlabeled titles are surfaced as unresolvable, not
  guessed at.
- Post-ingest handling of the source item in the client (e.g. whether to pause
  or delete a seed after ingest) follows an explicit, declared policy — the
  `--post-ingest {keep|pause|delete}` option, applicable only to client-source
  runs — with `keep` (leave the torrent in place) as the default.
- The library layout convention (e.g. a movies root and a TV root with show/
  season subfolders) is declared per run through the `--library-root <path>`
  option; a minimal conventional layout is the assumed default behavior when
  that option is given its conventional value.
- Quality profiles, subtitles, notifications, and indexer/download client
  management are separate pipeline steps, not this one. **File renaming is
  also a separate step**, downstream of ingest: ingest preserves original
  file names exactly as placed (so actively-seeded files stay verifiable and
  the already-handled convention stays intact); the future renaming step owns
  canonical naming and must account for seeding and the `--mode` placement
  outcomes its input carries.
- The first slice's "user" is the person operating the pipeline at a terminal;
  no graphical interface is in scope.
