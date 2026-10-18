# Research: Ingest Vertical Slice

**Feature**: `001-ingest-vertical-slice` | **Date**: 2026-10-17

Phase 0 output: each unknown from the plan's Technical Context resolved with a
decision, rationale, and alternatives considered.

## D1. Media title classification approach

**Decision**: Minimal hand-rolled classification matcher, in-repo, strictly
typed, with the rule "resolve or report unresolvable — never guess".

**Rationale**: The spec (FR-002, Assumptions) requires classification to be
based only on the candidate's own torrent/display name and file layout, and
explicitly forbids guessing at ambiguous titles (Edge Cases). Industry
guessers such as `guessit` are heavyweight regex-machine libraries whose whole
purpose is to guess aggressively — the exact failure mode the spec rejects —
and their table-driven internals are hostile to the strict-typing goal
(constitution XXVI). A small matcher with tests covers the release-name
grammar that matters (S01E02, season packs, year+quality movie names) and
treats everything it cannot resolve confidently as classification
`unresolvable`, which is a first-class disposition this feature already owns.

**Alternatives considered**:

- `guessit` library: most capable parser in the domain, but over-guesses,
  adds transitive dependencies (rebulk), Python 3.13 support is not
  versioned-clean, and it never returns "unresolvable" — contradicting FR-002.
- `python-namejure`/PTN-style single-file parsers: same over-guessing trait,
  unmaintained.
- External services (TMDb, TVDB): explicitly out of scope per Assumptions
  (this slice looks up nothing beyond the candidate's own names).

## D2. qBittorrent integration design

**Decision**: Implement the adapter against the qBittorrent **WebUI API v2**
(`/api/v2/auth/login`, `torrents/info`, `torrents/setLocation`,
`torrents/pause`, `torrents/delete`) over HTTPS-friendly HTTP transport, using
`httpx`, session-cookie login, base URL + username + password from environment
variables or `--client-url` (URL) and env (credentials).

**Rationale**: WebUI API v2 is qBittorrent's stable, documented interface and
the standard integration surface; every capability this spec needs exists in
it. `httpx` is typed, actively maintained, and Python 3.13-ready. All calls
are confined to `adapters/qbittorrent.py` per constitutions XVIII/XXVII —
ingest code speaks only to the adapter's narrow interface
(candidates-in, disposition-out).

**Alternatives considered**:

- Direct qBt RPC APIs beyond WebUI v2: unofficial/fragile.
- Custom stream-level parsing of torrent metadata: unnecessary — the client
  already exposes names, categories, and save paths via `torrents/info`.
- Choosing qBittorrent's built-in "Run after complete" script hooks instead of
  a separate step: rejected — it hides the step inside the client and defeats
  single-purpose composability (XXV).
- Malformed/unparseable client responses fail the run closed with a named
  cause (constitution VI); the adapter never synthesizes candidate rows to
  keep going.

## D3. CLI argument parsing

**Decision**: Python standard library `argparse`; the command is
`trovium-ingest` with exactly the option set fixed by FR-012.

**Rationale**: One command, eight options, strong typing requirements but no
subcommands or plugins — argparse covers this with zero dependencies and full
static typing support. Exit-code contract and misuse refusal (`--source` +
`--client-url`/`--post-ingest`) are implemented in `cli.py` and covered by the
CLI contract (see contracts/cli.md).

**Alternatives considered**: `typer`/`click` — nice ergonomics for richer
CLIs; rejected to keep the dependency surface minimal for the first slice.

## D4. Run-record emission

**Decision**: Standard library `json`; stable schema documented in
`contracts/record-schema.md`; machine-readable JSON on stdout by default;
`--json {compact|pretty}` selects formatting; human-facing asides (if any)
go to stderr only.

**Rationale**: FR-007 fixes the contract; keeping both formats the same data
with different formatting means the schema is defined once and contract tests
pin it. No credential or absolute secret-bearing path is ever emitted
(constitution I).

**Alternatives considered**: emitting human text by default (rejected in
clarify — pipeline composition prefers machine-readable stdout).

## D5. File placement operations

**Decision**: Implement `move|copy|hardlink` with `os`/`shutil` primitives:
move = `shutil.move` (rename when same filesystem; copy+delete fallback across
volumes), copy = `shutil.copy2` preserving mtimes, hardlink = `os.link` with
cross-filesystem fallback to copy. Sameness checks read file sizes + content
hashes; hashing is content-based (e.g., BLAKE2b via `hashlib`) so
already-handled detection is byte-accurate.

**Rationale**: Direct syscalls give control over FR-003 semantics (renames
preserve names; seeding-safe outcomes) and FR-004 ("does not overwrite
blindly"). Same-volume vs cross-volume behavior follows the file's device id
(`st_dev`), matching the placement matrix in data-model.md.

**Alternatives considered**: higher-level sync libraries (rsync, pyc
wrappers) — rejected: unnecessary abstraction for file-tree placement and they
obscure per-item disposition reporting.

## D6. Ordering/staging of the future renaming step

**Decision**: Deferred (per the user's session signal). The binary boundary
is fixed and enforced here: ingest never renames files and its emitted record
carries per-item classification and placement paths — sufficient for a
downstream rename stage keyed off the record, while remaining workable even
if that step is later designed to read the library independently.

**Rationale**: The user asked for a full-pipeline look and deferred the
ingest→rename contract decision. Nothing in ingest's design is invalidated by
either outcome because placement paths + classification travel in the record
either way.

**Alternatives considered**: deciding now — postponed deliberately.
