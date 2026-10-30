# Implementation Plan: Ebooks Through the Full Pipeline

**Branch**: `014-ebooks-full-pipeline` | **Date**: 2026-10-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/007-ebooks-full-pipeline/spec.md`

## Summary

Make one profile cross the whole pipeline. Three changes carry it:

1. **Adaptive mode default** — a new `auto` placement mode resolves per item:
   disk or non-seeding sources move; seeding torrents hardlink when the source
   and destination share a filesystem and copy when they do not. Installer and
   CLI default to `auto`.
2. **Install profile selection** — `trovium-deploy install --profile` and
   `install.sh --profile` write `[ingest] profile`; unknown names are refused.
3. **Client ebooks end to end** — a folder torrent expands through the books
   profile (book + sidecars), `trovium-run` renames copy/hardlink placements
   without an override, and a rerun detects the renamed library file by
   content instead of by name.

## Technical Context

**Language/Version**: Python 3.13 (uv-managed).

**Primary Dependencies**: standard library only; runtime dependencies stay at
`httpx` (unchanged).

**Storage**: INI config, JSON records, plain files. No database, no hidden
state.

**Testing**: pytest (`tests/unit`, `tests/contract`, `tests/integration`),
`scripts/check.sh` as the canonical gate.

**Target Platform**: Linux servers (x86_64, aarch64) and macOS for development.

**Project Type**: collection of single-purpose CLI tools.

**Performance Goals**: no whole-library scans. Destination lookups touch one
candidate directory and compare sizes before digests.

**Constraints**: one active profile per config (schema 1); no new runtime
dependency; existing video behavior stays covered.

**Scale/Scope**: one candidate at a time; book and episode directories hold a
handful of files.

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

| Principle                      | Check                                                                                     |
| ------------------------------ | ----------------------------------------------------------------------------------------- |
| I. No Secrets                  | Config stores env var names, not credentials; unchanged.                                  |
| II. Branch First               | Work stays on `014-ebooks-full-pipeline`.                                                 |
| III. Conventional Commits      | Commit/PR text follows the gate rules.                                                    |
| IV. Provable Enforcement       | Canaries and `scripts/check.sh` stay the proof; no gate weakening.                        |
| V. One Policy Many Boundaries  | No policy change.                                                                         |
| VIII/IX. Protected files       | No protected path is edited.                                                              |
| XII. Changed Files Scoped      | Stage explicit paths only.                                                                |
| XIII. Pre-PR Verification      | Full gate before the PR.                                                                  |
| XVII. Coverage                 | Each FR gets a unit or integration test.                                                  |
| XVIII. Single Chokepoint       | Mode resolution and content identity live in the ingest engine, not in profiles or steps. |
| XIX. Out of Scope              | No indexer, metadata, or multi-profile work.                                              |
| XXV. Unix single-purpose steps | `auto` is resolved inside the ingest step; records stay the interface; reruns are safe.   |
| XXVI. Typed Python             | mypy strict stays green; ruff and pytest via uv.                                          |
| XXVII. One client adapter      | Adapter untouched; only `ClientState` is read.                                            |

**Result**: no violations, no Complexity Tracking entries.

### Post-design re-check

The design keeps the gate results. Content identity keeps reruns safe (XXV)
without a lookup table; mode resolution stays inside the ingest engine
(XVIII); rename's gate removal is compensated by content identity and the
relocated-item skip. No new runtime dependency (XXVI), and the client adapter
is untouched (XXVII).

## Project Structure

### Documentation (this feature)

```text
specs/007-ebooks-full-pipeline/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── config-cli.md
│   └── record-schema.md
├── spec.md
└── tasks.md          # /speckit.tasks output
```

### Source Code (repository root)

```text
src/trovium/
├── record.py          # Mode.AUTO
├── config.py          # accepts mode = auto; default for new configs
├── cli.py             # resolves the effective mode per candidate
├── placement.py       # effective_mode(), same-filesystem probe
├── library.py         # content identity for a renamed destination
├── rename.py          # drop the mode gate; keep the relocated skip
├── run.py             # stop skipping rename for copy/hardlink
├── sources.py         # unchanged contract; client candidates already carry state
└── deploy/
    ├── cli.py         # install --profile
    └── installer.py   # InstallOptions.profile -> IngestSettings

install.sh             # forwards --profile
tests/
├── unit/              # mode resolution, content identity, config defaults
├── contract/          # CLI/config/record contracts
└── integration/       # client folder torrent, rename, rerun, install
```

**Structure Decision**: the existing single-package layout is kept. The
adaptive rule belongs to the ingest engine (`placement.py` + `cli.py`), the
profile registry stays the only place that knows media types, and the deploy
package only records the operator's choice.

## Complexity Tracking

None: no constitution violations.
