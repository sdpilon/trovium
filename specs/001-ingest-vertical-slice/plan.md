# Implementation Plan: Ingest Vertical Slice

**Branch**: `001-ingest-vertical-slice` | **Date**: 2026-10-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-ingest-vertical-slice/spec.md`

## Summary

Build the `trovium-ingest` single-purpose CLI: takes candidates from either a
qBittorrent client (via the project's one download-client adapter) or a local
filesystem directory (`--source`, the primary case), classifies each candidate
as movie / TV / unresolvable using only names present in the candidate itself,
places resolvable items into the library (folder structure derived, original
file names preserved), and emits a stable machine-readable JSON run record.
Idempotent by construction: no stored state other than the library and the
client. Implementation is Python ≥3.13, typed, exercised through `uv`.

## Technical Context

**Language/Version**: Python ≥3.13 with static typing (mypy strict on public surfaces), managed by `uv`

**Primary Dependencies**: `httpx` (qBittorrent WebUI API v2 client in the adapter); `pytest` (tests). Special-purpose discloser: no title-guessing libraries — classification is a minimal hand-rolled matcher (see research.md)

**Storage**: N/A — no database, no ledger, no hidden state (constitution XXV). The library and the download client are the only state; configuration arrives per run via CLI options and environment

**Testing**: `pytest` (unit, contract, integration), registered in the canonical `scripts/check.sh` quality gate

**Target Platform**: macOS and Linux (the pipeline operators' terminals); no GUI

**Project Type**: CLI (single-purpose command; console script `trovium-ingest`)

**Performance Goals**: A run over dozens of candidates completes in under a minute (SC-001); placement is local filesystem work, no network except the client adapter in client mode

**Constraints**: Offline-capable after `uv sync`; must run read-then-commit to keep FR-010 (client marked handled only after placement fully succeeds); secrets only via environment (constitution I); inspect-only mode makes zero mutations (FR-006)

**Scale/Scope**: One CLI step + one adapter module; dozens-to-hundreds of candidates per run; file counts per candidate unbounded (nested release trees)

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

| Principle                                  | Status  | Notes                                                                                         |
| ------------------------------------------ | ------- | --------------------------------------------------------------------------------------------- |
| I. No Secrets                              | ✅ Pass | Client credentials only from environment; never logged or in the emitted record (FR-012)      |
| II. Branch First                           | ✅ Pass | Work is on `001-ingest-vertical-slice`, cut from `main`                                       |
| III. Conventional Commits                  | ✅ Pass | Commits will use `feat:`/`docs:` with ≤72-char subjects                                       |
| IV. Provable Enforcement                   | ✅ Pass | No new gate introduced by this feature                                                        |
| V. One Policy Many Boundaries              | ✅ Pass | Enforced policy unchanged                                                                     |
| VI. Fail Closed                            | ✅ Pass | Unreadable/ambiguous inputs become named failures in the record (SC-003), never silent passes |
| VII. Secret Rotation                       | ✅ Pass | N/A — no credentials handled beyond env-read passthrough                                      |
| VIII/IX/XV. Immutable docs/policy/tracking | ✅ Pass | Spec/plan produced by the specify/plan flow only                                              |
| X. Worktree Safety                         | ✅ Pass | Scripts target explicit paths                                                                 |
| XI./XIII. Rebase & Pre-PR verification     | ✅ Pass | `scripts/check.sh` green before PR                                                            |
| XII. Changed Files Scoped                  | ✅ Pass | This feature only adds new modules; no pre-existing debt touched                              |
| XIV. Fail Loudly                           | ✅ Pass | Per-item named reasons; run-level failure exits non-success                                   |
| XVI./XVII. Regressions & coverage          | ✅ Pass | Every behavior ships with pytest coverage (XXVII)                                             |
| XVIII. Single Chokepoint                   | ✅ Pass | All client I/O via `adapters/qbittorrent.py`; all library-writing via the placement module    |
| XIX. Out Of Scope Boundary                 | ✅ Pass | Renaming, subtitles, profiles, notifications, other clients — owned by future steps/specs     |
| XX. Projection Not Dependency              | ✅ Pass | All required tooling is in-repo                                                               |
| XXI. Codeowners                            | ✅ Pass | Spec dir changes follow governance (already reviewed through this flow)                       |
| XXII. Stop Hook Discipline                 | ✅ Pass | Green local run required to finish                                                            |
| XXIII. Spec Is Boundary                    | ✅ Pass | Success criteria land as executable acceptance checks in tasks/implementation phase           |
| XXIV. No Coding Before Spec                | ✅ Pass | Spec agreed through clarify sessions before this plan                                         |
| XXV. Unix single-purpose steps             | ✅ Pass | One CLI, text/JSON streams, re-runnable, no hidden state                                      |
| XXVI. Typed Python through uv              | ✅ Pass | Developed/tested via `uv`; same command local and CI                                          |
| XXVII. One client adapter                  | ✅ Pass | qBittorrent only, confined to the adapter module                                              |

## Project Structure

### Documentation (this feature)

```text
specs/001-ingest-vertical-slice/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI contract, run-record JSON schema)
└── tasks.md             # Phase 2 output (/speckit.tasks — not created here)
```

### Source Code (repository root)

```text
src/trovium/
├── __init__.py          # exists
├── py.typed             # exists
├── cli.py               # argv parsing, misuse refusal, exit codes
├── sources.py           # candidate enumeration: client + filesystem source
├── classify.py          # movie/TV/unresolvable classification from names
├── library.py           # destination resolution + already-handled check
├── placement.py         # move/copy/hardlink execution (single chokepoint for writes)
├── record.py            # RunSummary model + JSON emission (compact/pretty)
└── adapters/
    ├── __init__.py
    └── qbittorrent.py   # the single qBittorrent adapter (WebUI API v2)

tests/
├── unit/                # classify, destination resolution, misuse refusal
├── contract/            # run-record JSON schema stability, CLI contract
└── integration/         # end-to-end: disk source, fixture client, idempotence, dry-run
```

**Structure Decision**: Single project (existing `src/trovium` layout); the
ingest command is the first step binary in what becomes a family of
single-purpose CLIs under one package. All library mutations go through
`placement.py`, all client I/O through `adapters/qbittorrent.py` —
constitution XVIII chokepoints.

## Complexity Tracking

_No constitution violations — table intentionally empty._

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --------- | ---------- | ------------------------------------ |
