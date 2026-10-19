# Tasks: Ingest Vertical Slice

**Input**: Design documents from `/specs/001-ingest-vertical-slice/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included per constitutions XVII/XXIII — every behavior ships with automated coverage and success criteria land as executable acceptance checks. Test tasks are written first and made to fail before implementing.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- Single project: `src/trovium/` and `tests/` at repository root (per plan.md)

### Inline notes for required constraints (quoted from data-model.md / contracts/)

- Disposition values are exactly: `ingested`, `already_handled`, `not_yet_complete`, `unresolvable`, `rejected_out_of_scope`, `error` (reason required when `error`) — typed enum in `record.py`.
- Run record field names and enums are pinned by `contracts/record-schema.md`; CLI options/exit codes by `contracts/cli.md`.
- FR-003 constraint quoted: "File names of the placed media MUST be preserved exactly as ingested … destination _folder_ names … are derived by this step".
- FR-010 constraint quoted: "MUST NOT mark a download as handled in the client unless its library placement for that item has fully succeeded".
- Classification writes no guesses: rule "resolve or report unresolvable — never guess" (FR-002).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project readiness for the new step

- [x] T001 Run `uv sync` and `scripts/check.sh` to confirm the baseline is green before any change (constitution XIII, XXVI)
- [x] T002 [P] Register the console script entry point `trovium-ingest = "trovium.cli:main"` in `pyproject.toml` under `[project.scripts]`, and add `httpx` to `[project].dependencies` (the only runtime dependency — no CLI/file/parse/log libraries, per research.md D8); run `uv lock`/`uv sync` and confirm no other runtime package entered the lock
- [x] T003 [P] Create the package layout from plan.md: `src/trovium/adapters/__init__.py`, empty modules `src/trovium/sources.py`, `src/trovium/classify.py`, `src/trovium/library.py`, `src/trovium/placement.py`, `src/trovium/record.py`, `src/trovium/cli.py`, and test dirs `tests/unit/`, `tests/contract/`, `tests/integration/`

**Checkpoint**: environment and `trovium-ingest` entry point exist

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core modules every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 [P] Implement typed record models in `src/trovium/record.py`: `Disposition` enum with exactly the values `ingested`, `already_handled`, `not_yet_complete`, `unresolvable`, `rejected_out_of_scope`, `error` (`reason` required whenever `error` is used — data-model.md + contracts/record-schema.md), `ItemRecord` (name, disposition, reason nullable, kind nullable, title nullable, destination nullable, actions list), `RunSummary` (source enum, dry_run flag, declared {library_root, category, mode, post_ingest, on_fail}, items list, counts derived and MUST equal items per contracts/record-schema.md), plus `emit(summary, style)` producing compact/pretty JSON to stdout — no credential values may ever appear (constitution I, FR-007, FR-012)
- [x] T005 [P] Implement the classification matcher in `src/trovium/classify.py`: from a candidate name and its nested file names classify movie (title + year/quality grammar), tv (series title + `S01E02`-style or season-pack markers), or `unresolvable`; ambiguous input MUST resolve to `unresolvable`, never guessed (FR-002, data-model.md Classification rules)
- [x] T006 Implement destination resolution and already-handled detection in `src/trovium/library.py`: derive the library destination from `--library-root` plus the layout convention (movies root / tv root with show and season subfolders), quoting FR-003: "destination _folder_ names … are derived by this step" while file names are preserved; expose `resolve_destination(classification, library_root)` and `existing_item_matches(destination, candidate_files)` used for the
      convention-based `already_handled` rule (FR-004 — matches on identity, no
      ledger): identity by (kind, title, season, file-name set) first; within
      equal identity, size-equal then BLAKE2b content-hash equal, with the hash
      computed only when sizes are equal (data-model.md hash-scope section)
- [x] T007 Implement placement operations in `src/trovium/placement.py`: `move` (rename on same filesystem; copy+delete fallback across volumes), `copy` (`shutil.copy2`, originals remain), `hardlink` (`os.link`, falling back to copy across volumes per FR-003; outcomes per data-model.md Behavior matrix rows 1–8); sameness detection follows the pinned conflict-outcome policy — no overwrite, no silent replace (never overrides the matrix); per-item result becomes a Disposition with named reason on failure; a destination on an unwritable/unavailable volume yields disposition `error` with the named IOError cause, consumed by `--on-fail {stop|continue}` (matrix row-4 sibling); a read failure on a candidate's source files (e.g. permission denied) likewise yields a per-item `error` with the named cause under `--on-fail`, leaving nothing half-placed and recording no success for that item
- [x] T008 Implement the CLI in `src/trovium/cli.py`: exactly the option set, defaults, and env variables of `contracts/cli.md` (`--client-url` default from `TROVIUM_CLIENT_URL`, credentials from `TROVIUM_CLIENT_USERNAME`/`TROVIUM_CLIENT_PASSWORD` only); refuse misuse before any work: `--source` + `--client-url`, `--source` + `--post-ingest`, missing source with URL unset (exit 2 with a message naming the conflicting option); exit 0 run completed / 2 misuse / 3 client unreachable-or-auth-invalid (FR-008)

**Checkpoint**: record/classification/destination/placement/cli cores compile; contract tests can target them; user stories now add sources and wiring

---

## Phase 3: User Story 1 - Ingest media already on disk (Priority: P1) 🎯 MVP

**Goal**: `--source <path>` ingests on-disk media into the library end-to-end, idempotently

**Independent Test**: Point `--source` at a fixture directory and `--library-root` at an empty dir; run; verify placement, record dispositions, and a second run reporting `already_handled` with nothing changed — no client involved

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T009 [P] [US1] Contract test in tests/contract/test_cli_contract.py: misuse refusals (exit 2, named option, stdout empty) including a non-directory or unreadable `--library-root` and a missing/non-directory/unreadable `--source`, exit-code mapping, `--json` compact/pretty emit the same data shape per contracts/record-schema.md
- [x] T010 [P] [US1] Integration test in tests/integration/test_disk_ingest.py covering Story 1 acceptance ids 1–3: media placed with original filenames, non-media child reported `rejected_out_of_scope` with reason, unresolvable child reported `unresolvable`, re-run is a no-op reporting `already_handled` (SC-002), counts reconcile, and no credentials in output (constitution I)

### Implementation for User Story 1

- [x] T011 [US1] Implement disk-source candidate enumeration in `src/trovium/sources.py`: each direct child entry of `--source` (file or directory) is exactly one candidate; a candidate's contents may include arbitrarily nested media files that travel together as one item (FR-013); candidates get `completion_state: complete`, `client_state: none`
- [x] T012 [US1] Wire the disk-mode run flow in `src/trovium/cli.py`: sources → classify → library → placement → record, emitting `source: "disk"`, category filtering deferred to US3 (accept `all`), and item dispositions flowing through `--on-fail {stop|continue}` semantics (default `continue` runs on after a named per-item error); note that disk-sourced candidates carry `client_state: none` and `completion_state: complete` so the Candidate shape stays uniform across sources even though those fields are client-relevant only

**Checkpoint**: `uv run trovium-ingest --source … --library-root …` performs the full disk journey; `scripts/check.sh` green

---

## Phase 4: User Story 2 - Ingest completed downloads from qBittorrent (Priority: P2)

**Goal**: Client mode ingests completed downloads via the single qBittorrent adapter

**Independent Test**: With a fixture qBittorrent WebUI (stubbed transport in tests, real instance for manual validation), completed/incomplete/mixed sets produce the spec'd dispositions

### Tests for User Story 2

- [x] T013 [P] [US2] Integration test in tests/integration/test_client_ingest.py with a fixture HTTP transport: completed seeded torrent → `ingested` (and FR-010 quoted constraint invoked: handled-marking happens only after placement fully succeeded), incomplete → `not_yet_complete` non-error, unreachable endpoint → exit 3 named error with nothing placed (FR-008), invalid credentials → exit 3, credentials invisible in record/stderr; malformed/unparseable client responses (missing name, completion state, or save path) → exit 3 with named cause, no items ingested, no success in the record — fail closed per constitution VI (tests/contract coverage via a stubbed transport returning broken payloads)

### Implementation for User Story 2

- [x] T014 [US2] Implement the single qBittorrent adapter in `src/trovium/adapters/qbittorrent.py` (constitutions XVIII/XXVII: the only client-I/O code): login (`/api/v2/auth/login`, session cookie), list candidates (`torrents/info`), and policy operations `torrents/setLocation`, `torrents/pause`, `torrents/delete` for `--post-ingest {keep|pause|delete}`; expose a narrow interface (candidates-in, disposition-out) — ingest code elsewhere must not know qBittorrent details; malformed or unparseable API responses fail the run closed with a named cause rather than being skipped or synthesized into candidates (constitution VI)
- [x] T015 [US2] Wire client mode into `src/trovium/cli.py`: `--client-url` + env credentials → adapter candidates (complete vs not yet complete), same classify/library/placement flow as disk mode, `--post-ingest` applied only after successful `ingested` placement (FR-010), `not_yet_complete` skipped without error (Story 2 id 2)

**Checkpoint**: Stories 1 and 2 both functional independently; `scripts/check.sh` green

---

## Phase 5: User Story 3 - Filter which candidates are ingested (Priority: P3)

**Goal**: `--category {movie,tv,all}` limits a run to a class in both sources

**Independent Test**: With a mixed movie/TV fixture (disk or client), scoped runs touch exactly the selected items and the other is left untouched (Story 3 ids 1–2)

### Tests for User Story 3

- [x] T016 [P] [US3] Unit tests in tests/unit/test_category_filter.py: scoping by class after classification, no-match runs succeed clearly and touch nothing with an empty `items` and reconciled counts (Story 3 id 2)

### Implementation for User Story 3

- [x] T017 [US3] Apply the category filter in the run flow in `src/trovium/cli.py` for both sources: post-classification scoping so a filtered item is untouched — except that `unresolvable` candidates remain visible as `unresolvable` in the record under any scope selection, `declared.category` is included in the record, empty result is a clean success (exit 0)

**Checkpoint**: Filtering works in both modes; previously passing stories still green

---

## Phase 6: User Story 4 - Plan without changing anything (Priority: P4)

**Goal**: `--dry-run` emits the exact action plan with zero mutations

**Independent Test**: Run `--dry-run` over a fixture state, hash-snapshot client + library, re-run without `--dry-run`, compare record + snapshots (SC-005, Story 4 ids 1–2)

### Tests for User Story 4

- [x] T018 [P] [US4] Contract test in tests/contract/test_dry_run.py: `dry_run: true` record contains a full per-item `actions` plan; plan parity invariant — the real run executed right after produces the same actions field-for-field (SC-005); both the declared source (directory contents in disk mode; client state via the stubbed transport in client mode) and the library are unchanged under dry-run (Story 4 id 1)

### Implementation for User Story 4

- [x] T019 [US4] Implement dry-run wiring in `src/trovium/cli.py` + `src/trovium/placement.py`: plan path computes dispositions/actions without touching the declared source (no filesystem writes anywhere under `--source` in disk mode; no `setLocation`/`pause`/`delete` in client mode) and without touching the library, when `dry_run` is set; record carries the same schema with `dry_run: true` (FR-006)

**Checkpoint**: All four user stories functional independently

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Completeness and cross-story verification

- [x] T020 [P] Update `README.md` development section: document the `trovium-ingest` command, its options table (extract from `specs/001-ingest-vertical-slice/contracts/cli.md`), and the disk-source/client-mode examples
- [x] T021 Execute `specs/001-ingest-vertical-slice/quickstart.md` scenarios 1–5 as the executable acceptance checks for SC-001–SC-005 and record results in the session; fix anything red before continuing
- [x] T022 Run the full canonical gate `scripts/check.sh` and confirm green across ruff, mypy, pytest, and the markdown/file linters (constitution XXII, XXVI), including a timing observation for SC-001: a disk-source run over a fixture of 50 candidates (≈1000 files) must complete in under a minute on the run machine; record the observed duration next to the other scenario outcomes
- [x] T023 [P] Add `tests/unit/test_dependency_budget.py` asserting `pyproject.toml`'s `[project].dependencies` equals exactly `["httpx"]` (research.md D8), so an accidental runtime dependency fails CI

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately
- **Foundational (Phase 2)**: depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: depends on Foundational
- **US2 (Phase 4)**: depends on Foundational; reuses the US1 run flow but is independently testable
- **US3 (Phase 5)**: depends on US1+US2 (filtering applies across both modes)
- **US4 (Phase 6)**: depends on US1+US2 (plan parity is verified against both flows)
- **Polish (Phase 7)**: depends on all desired stories complete

### User Story internal order

- Tests first (T009/T010, T013, T016, T018) — must fail before implementation
- Models before services before wiring: record/classify → library/placement → cli
- Story complete at each Checkpoint; commit after each logical group (`feat(ingest): ...`)

### Parallel Opportunities

- T002, T003 (Phase 1) — different files
- T004, T005 (Phase 2) — different files
- T009, T010 (Phase 3) — different test files
- T013 (Phase 4), T016 (Phase 5), T018 (Phase 6) — different files, all once stories' foundations exist
- T020, T023 (Phase 7) — different files (README vs unit test)
- With multiple developers: US1 and US2 work can proceed in parallel after Phase 2, since both only wire existing foundational cores

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational)
2. Complete Phase 3 (US1 disk mode)
3. **STOP and VALIDATE**: `uv run trovium-ingest --source … --library-root …` + `scripts/check.sh`
4. This alone delivers the spec's P1 story end-to-end — the essential, direct-need case

### Incremental Delivery

- Add US2 (client mode) → re-run gate → demo
- Add US3 (filtering) → re-run gate
- Add US4 (dry-run) → re-run gate
- Each story adds value without breaking the previous ones; quickstart.md scenarios map 1:1 to SC-001–SC-005 executable acceptance checks (constitution XXIII)

### Parallel Team Strategy

- After Phase 2: Dev A → US1; Dev B → US2 (adapter + client stub tests are independent of disk wiring)
- US3/US4 converge on the shared run flow in `cli.py` — schedule sequentially or pair on it

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Verify tests fail before implementing
- Commit after each task or logical group with Conventional Commits subjects (constitution III)
- Stop at any checkpoint to validate the story independently
- Avoid vague tasks and cross-story file conflicts — `cli.py`, `record.py` are shared wires; coordinate edits there sequentially

---

## Phase 8: Convergence

**Purpose**: Close the gaps found by `/speckit.converge` between the implemented
code and `spec.md` / `plan.md` / `data-model.md`. Ordered by severity.

- [x] T024 Address client operations by torrent hash: add the torrent `hash` to
      `ClientEntry` and pass `hashes=<hash>` (not `"all"`) for `setLocation`,
      `pause`, and `delete` in `src/trovium/adapters/qbittorrent.py`, so
      post-ingest policy and relocation affect only the ingested torrent; add
      adapter/integration assertions that exactly the target hash is sent per
      FR-010 and FR-011 (contradicts)
- [x] T025 Remove the now-redundant source files in `move` mode when the
      destination already holds identical content, and report the removal in the
      item's `reason`, per the pinned conflict policy in `data-model.md` Behavior
      matrix row 2; extend `tests/unit/test_placement.py` accordingly (partial)
- [x] T026 Refuse an explicitly supplied `--post-ingest` when combined with
      `--source` even at its default value: make the parser default `None`,
      resolve `keep` only in client mode, and refuse whenever the option was
      given, per FR-013 and contracts/cli.md; add a contract test for
      `--source --post-ingest keep` (contradicts)
- [x] T027 Record client-facing operations in the run record for ingested
      client-mode items — `setLocation`, `pause`, and `delete` — so the summary
      makes client behavior explicit per FR-007, SC-004, and the client-state
      edge case; keep the record schema backward-compatible (additive field) and
      cover it in contract tests (missing)
- [x] T028 Add a client-mode dry-run parity contract test: the `--dry-run`
      record's `actions` must equal the subsequent real run's `actions`
      field-for-field, extending SC-005 coverage beyond disk mode (partial)
- [x] T029 Review the unused `warn()` helper in `src/trovium/record.py`:
      either remove it or justify its retention in research decision D7
      (unrequested)

---

## Phase 9: Convergence

**Purpose**: Close the two remaining gaps found by the second `/speckit.converge` pass.

- [x] T030 Represent the planned removal of a redundant source in the
      placement plan for `move` mode with identical library content, so an
      inspect-only run exposes it: introduce an `op: "delete"` action (with
      `from`/`to`/`bytes` semantics), update `plan_placement`/`apply_placement` in
      `src/trovium/placement.py`, document the added action op in
      `contracts/record-schema.md`, and extend `tests/contract/test_dry_run.py` to
      assert dedup-path plan parity per SC-005, FR-006, and data-model.md Behavior
      matrix row 2 (partial)
- [x] T031 Document malformed/unparseable client responses as an exit-code 3
      run-level failure in `contracts/cli.md` completion-side behaviors, matching
      the implemented fail-closed behavior (constitution VI) and T013
      (partial)

---

## Phase 10: Convergence

**Purpose**: Reconcile the specification and quickstart with behavior added in
response to the live qBittorrent review.

- [x] T032 Amend `spec.md` FR-003 (and the Assumptions if needed) to record the
      client-mode `--mode move` exception now implemented and documented in
      `contracts/cli.md` and `data-model.md`: folder torrents are refused with a
      per-item error recommending `--mode copy`/`--mode hardlink`, an
      already-handled folder torrent is a no-op with removals suppressed, and the
      refusal runs after classification/scope (partial)
- [x] T033 Extend `quickstart.md` Scenario 5 with the live-verified checks:
      a folder torrent under `--mode move` is refused with guidance, and
      `--mode move --post-ingest pause` pauses before relocation (record order
      `pause` then `setLocation`) (partial)
