# Feature Specification: Pipeline Runner

**Feature Branch**: `005-pipeline-runner`

**Created**: 2026-10-22

**Status**: Complete

**Input**: User description: "one command that runs the steps in order, so the
pipeline can be scheduled without manual piping."

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Run ingest and rename in one command (Priority: P1)

A user configures one source, profile, and library root, then runs
`trovium-run`. The step ingests the candidates, renames the placed files when
it is safe, and prints one combined JSON record.

**Why this priority**: It is the operational unit a cron job or systemd timer
can invoke; the individual steps remain independently runnable.

**Independent Test**: Point `--source` at the books fixture and run
`trovium-run --profile books`. Verify the combined record has both sections and
the files are renamed.

**Acceptance Scenarios**:

1. **Given** a books source and a move-mode run, **When** `trovium-run` runs,
   **Then** the files are ingested and renamed and the record contains
   `ingest` and `rename`.
2. **Given** a movie and TV source, **When** `trovium-run` runs, **Then** both
   are ingested and the video files are renamed.
3. **Given** a run from the shared config, **When** `trovium-run --config`
   runs, **Then** the configured profile, source, and library root are used.

---

### User Story 2 - Dry-run and safe composition (Priority: P1)

A user can inspect a run without changing anything. Copy/hardlink runs place
files but skip rename by default, because the rename step would refuse them
unless `--allow-unsafe` is given.

**Why this priority**: A runner must not silently break the safety rules of
the steps it composes.

**Independent Test**: Run `--dry-run` and verify nothing changed and rename is
not planned. Run a copy-mode source and verify ingest happened while rename was
skipped with a reason.

**Acceptance Scenarios**:

1. **Given** `--dry-run`, **When** the runner runs, **Then** no file is
   placed or renamed, and `rename` is null with a `rename_skipped` reason.
2. **Given** a copy/hardlink source, **When** the runner runs without
   `--allow-unsafe`, **Then** ingest places the files and rename is skipped
   with a reason.
3. **Given** `--allow-unsafe`, **When** the runner runs a copy-mode source,
   **Then** rename is attempted and the rename record reports any collision.
4. **Given** an unreachable client, **When** the runner runs, **Then** it
   exits 3 and does not attempt rename.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: `trovium-run` MUST accept the same source, profile, config, mode,
  dry-run, on-fail, and JSON options as `trovium-ingest`.
- **FR-002**: It MUST run ingest through the existing ingest engine and must
  not duplicate classification, placement, or client logic.
- **FR-003**: It MUST run rename through the existing rename engine when the
  ingest record's mode is `move` and the run is not a dry-run.
- **FR-004**: It MUST skip rename, with a reason in the combined record, when
  `--skip-rename` is set, the run is a dry-run, or the mode is copy/hardlink
  without `--allow-unsafe`.
- **FR-005**: `--allow-unsafe` MUST be passed through to rename.
- **FR-006**: The combined record MUST be JSON on stdout:
  `{source: "run", dry_run, profile, library_root, ingest, rename,
rename_skipped}`. `ingest` is the existing ingest record; `rename` is the
  existing rename record or null.
- **FR-007**: Exit codes MUST be `0` for a completed run (per-item outcomes are
  in the records), `2` for misuse, and `3` for a run-level client failure.
- **FR-008**: A run-level ingest failure MUST NOT attempt rename.
- **FR-009**: The runner MUST not add a runtime dependency or a second
  implementation of a step.
- **FR-010**: The combined record MUST contain no credential values.
- **FR-011**: The runner MUST be registered as `trovium-run` and included in
  the deployment command set.

### Key Entities

- **Pipeline run**: one ingest record plus one optional rename record, under a
  single `source: "run"` envelope.
- **Rename skip reason**: why the second step did not run (`dry-run`,
  `--skip-rename`, unsafe mode, or an ingest failure).

## Success Criteria _(mandatory)_

- **SC-001**: A books source is ingested and renamed in one command; the
  combined record contains both sections.
- **SC-002**: A movie/TV source is ingested and renamed in one command.
- **SC-003**: `--dry-run` changes nothing and clearly skips rename.
- **SC-004**: A copy-mode run places files and skips rename with a reason
  unless `--allow-unsafe` is given.
- **SC-005**: An unreachable client exits 3 and does not attempt rename.
- **SC-006**: The deployed command set includes `trovium-run`.

## Out of Scope

- Installing or managing a scheduler (cron/systemd) in this slice.
- Multiple sources, libraries, or profiles in one run.
- Parallel runs, retries, notifications, or a queue.
- Changing the ingest or rename contracts.

## Assumptions

- The configured source, profile, and library root describe one pipeline.
- The runner is the scheduling unit; the scheduler itself is external.
- A dry-run cannot plan rename because the files are not placed yet.
