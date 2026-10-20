# Implementation Plan: Server Deployment

**Branch**: `002-server-deployment` | **Date**: 2026-10-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-server-deployment/spec.md`

## Summary

Deliver a one-command, per-user installation for trovium on a single server and
media library. A small Bash bootstrap resolves a self-contained release bundle
(checksum-verified wheelhouse, pinned `uv`, pinned CPython), then hands control
to a typed `trovium-deploy` CLI. That CLI installs the wheel as a private uv
tool, creates or validates one INI configuration file, runs a non-destructive
self-check over every shipped console script, records deployment state, and
emits a machine-readable run report. Re-running the same install command
upgrades; identical re-runs use a small version index, the installed
`trovium-deploy check`, and a verified bundle cache to finish without
re-downloading. `trovium-deploy status` and `trovium-deploy uninstall` cover the
rest of the lifecycle, with `install.sh --status` and `install.sh --uninstall` as
bootstrap fallbacks when the installed command is missing or broken. Offline
installation uses the same bundle path, `trovium-ingest` gains optional
configuration-file defaults, and scheduling, containers, and multi-server fleet
management remain out of scope.

## Technical Context

**Language/Version**: Python 3.13 (typed, mypy strict) for all deployment logic;
Bash 3.2+ for the thin `install.sh` bootstrap.

**Primary Dependencies**:

- **Runtime (unchanged, exactly one package)**: `httpx`. No new Python runtime
  dependency is introduced; deployment and configuration code uses only the
  standard library (`argparse`, `configparser`, `json`, `hashlib`, `subprocess`,
  `tarfile`, `zipfile`, `urllib`, `fcntl`, `shutil`, `tempfile`, `datetime`).
- **Bundled tools, not Python dependencies**: pinned `uv` binary and pinned
  static CPython 3.13 standalone, shipped inside the release bundle so a clean
  server needs neither preinstalled.
- **Build/release tooling only**: `uv build`, an ephemeral seeded virtual
  environment with `pip download` for the wheelhouse, and the release bundle
  builder. These are not installed on target servers as project dependencies.

**Storage**:

- Configuration: `${XDG_CONFIG_HOME:-~/.config}/trovium/config.ini` (mode 0600).
- Deployment state: `${XDG_STATE_HOME:-~/.local/state}/trovium/deployment.json`,
  a lock file, and a cached wheelhouse for rollback.
- Toolchain and tool environment: `${XDG_DATA_HOME:-~/.local/share}/trovium/`
  (private `uv`, private CPython, `uv` tool directory).
- Bundle cache: `${XDG_CACHE_HOME:-~/.cache}/trovium/bundles/<version>/`.
- Commands: `${TROVIUM_BIN_DIR:-~/.local/bin}`.
- No database, no daemon, no hidden service state.

**Testing**: `pytest` unit, contract, and integration layers; a real
`uv tool install` integration test against a locally built bundle in isolated
temporary XDG directories; `shellcheck` on `install.sh`; the canonical
`scripts/check.sh` gate runs all of it.

**Target Platform**: Linux x86_64 and aarch64 (primary, release artifacts);
macOS aarch64/x86_64 for development and local bundle tests. Windows is out of
scope.

**Project Type**: CLI plus installer/release tooling in the existing single
Python project.

**Performance Goals**: clean-server install under 5 minutes with a normal
network (SC-001); identical re-run under 30 seconds using a local bundle, the
cached bundle, or the installed `check` fast path (SC-003); status under
5 seconds (SC-012); uninstall under 2 minutes (SC-009); no deployment operation
writes to the media library (SC-005).

**Constraints**: one runtime dependency (`httpx`); no administrative
privileges; fully self-contained offline bundle; secrets only from the
environment or a protected file; no scheduling, services, containers, or
multi-server orchestration; no OS, storage, or client provisioning.

**Scale/Scope**: one server, one media library, and every console script
exported by the installed wheel (currently `trovium-ingest` plus
`trovium-deploy`). Tens of candidates per pipeline run are irrelevant to the
deployment; deployment acts on one tool environment, one config file, and one
state record.

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

| Principle                                  | Status | Notes                                                                                                                     |
| ------------------------------------------ | ------ | ------------------------------------------------------------------------------------------------------------------------- |
| I. No Secrets                              | Pass   | Config stores credential environment-variable names, never values; reports redact; config is 0600; no secret CLI options. |
| II. Branch First                           | Pass   | Work stays on `002-server-deployment`, cut from `main`.                                                                   |
| III. Conventional Commits                  | Pass   | Commits use `feat:`/`docs:`/`test:` with subjects at most 72 characters.                                                  |
| IV. Provable Enforcement                   | Pass   | No new gate class; bundle verification, self-check, and rollback ship with failing-canary tests.                          |
| V. One Policy Many Boundaries              | Pass   | The gates policy is unchanged; the release workflow is a separate publication boundary.                                   |
| VI. Fail Closed                            | Pass   | Checksum, manifest, platform, config, and self-check failures stop before activation and name a cause.                    |
| VII. Secret Rotation                       | Pass   | The feature never receives credentials; it only stores references and validates presence.                                 |
| VIII/IX/XV. Immutable docs/policy/tracking | Pass   | Specs and plans come from the flow; the deployment record is written only by the deployment tooling.                      |
| X. Worktree Safety                         | Pass   | All installer paths are explicit; no git operations and no repository mutation.                                           |
| XI./XIII. Rebase & pre-PR verification     | Pass   | `scripts/check.sh` must be green before the PR; release workflow runs the same gate.                                      |
| XII. Changed Files Scoped                  | Pass   | New modules and tooling only; the ingest CLI change is additive and covered by tests.                                     |
| XIV. Fail Loudly                           | Pass   | Every failure exits non-success and emits a named error report with a remedy.                                             |
| XVI./XVII. Regressions & coverage          | Pass   | New behavior is covered at unit, contract, and integration layers; the ingest config change has regression tests.         |
| XVIII. Single Chokepoint                   | Pass   | `deploy/uv.py` is the only uv subprocess boundary; `config.py` is the only config reader/writer; `state.py` owns state.   |
| XIX. Out Of Scope Boundary                 | Pass   | Scheduling, multi-server orchestration, containers, OS/client provisioning, and secret management stay excluded.          |
| XX. Projection Not Dependency              | Pass   | The bundle carries its own `uv`, Python, and wheels; the installed tool works offline and does not depend on a global uv. |
| XXI. Codeowners                            | Pass   | `.github/`, `.specify/`, and specs remain under `@sdpilon`; the release workflow is reviewable.                           |
| XXII. Stop Hook Discipline                 | Pass   | The canonical check must be green before completion.                                                                      |
| XXIII. Spec Is Boundary                    | Pass   | Acceptance checks for SC-001 through SC-010 and SC-012 land in tasks.md during `/speckit.tasks`.                          |
| XXIV. No Coding Before Spec                | Pass   | Spec and clarifications are agreed; this plan precedes implementation.                                                    |
| XXV. Unix single-purpose steps             | Pass   | `trovium-deploy` is one CLI with plain-file and JSON contracts; it does not become a daemon.                              |
| XXVI. Typed Python through uv              | Pass   | All deployment logic is typed Python under `src/trovium/deploy/`; the Bash bootstrap is a thin, shellchecked launcher.    |
| XXVII. One client adapter                  | Pass   | Deployment does not contact the download client; config validation is offline and the existing adapter is untouched.      |

Post-design re-check (after Phase 1): all principles remain Pass. The bundle
carries its own uv, Python, and wheels (XX); deployment stays a single CLI with
plain-file and JSON contracts (XXV); no new runtime dependency is introduced;
the client adapter is unchanged (XXVII). No constitution violations require
justification.

## Project Structure

### Documentation (this feature)

```text
specs/002-server-deployment/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── cli.md           # install.sh, trovium-deploy, ingest --config
│   ├── config-schema.md # INI configuration schema and precedence
│   ├── report-schema.md # machine-readable deployment run report
│   └── bundle.md        # release bundle layout, manifest, checksums
└── tasks.md             # Phase 2 output (/speckit.tasks — not created here)
```

### Source Code (repository root)

```text
src/trovium/
├── __init__.py
├── py.typed
├── cli.py               # existing ingest CLI; adds --config and config fallbacks
├── config.py            # INI schema, load/validate/write, migration, precedence
├── classify.py          # existing
├── library.py           # existing
├── placement.py         # existing
├── record.py            # existing
├── sources.py           # existing
├── adapters/
│   └── qbittorrent.py   # existing
└── deploy/
    ├── __init__.py
    ├── cli.py           # trovium-deploy entry point and exit codes
    ├── installer.py     # install/upgrade/status/uninstall orchestration
    ├── bundle.py        # manifest, checksums, wheel metadata, Python tarball
    ├── paths.py         # XDG paths, platform detection, permissions, prompts
    ├── report.py        # run-report model and JSON/human emission
    ├── selfcheck.py     # console-script discovery and non-destructive checks
    ├── state.py         # deployment record, atomic writes, lock
    └── uv.py            # the only uv subprocess boundary

install.sh               # Bash bootstrap: resolve, verify, extract, invoke
tools/release/
├── build_bundle.py      # local/CI bundle builder
├── toolchain.lock.json  # pinned uv and CPython versions plus checksums
└── README.md

tests/
├── unit/deploy/         # config, report, state, bundle, selfcheck, paths
├── contract/deploy/     # CLI options, exit codes, report/config schemas
├── integration/deploy/  # real uv install, offline bundle, upgrade/uninstall
└── fixtures/deploy/     # broken/upgrade bundle fixtures

.github/workflows/release.yml
```

**Structure Decision**: Keep the existing single-project layout. Deployment
logic lands in a new `trovium.deploy` subpackage so pipeline steps and
deployment concerns stay separate. `trovium.config` is shared by `trovium-ingest`
and `trovium-deploy`, making configuration a single chokepoint. The Bash
bootstrap is deliberately thin: it only resolves, verifies, and extracts the
bundle, then calls the typed CLI. Release tooling stays under `tools/release/`
and is not imported by the installed package. `pyproject.toml` gains the
`trovium-deploy` console script; the dependency-budget test is extended to
assert both console scripts while keeping `httpx` as the only runtime
dependency. `README.md` gains the user-facing install, upgrade, status,
uninstall, offline, and config guidance; the feature contracts remain
authoritative for exact behavior.

## Complexity Tracking

_No constitution violations — table intentionally empty._

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --------- | ---------- | ------------------------------------ |
| —         | —          | —                                    |
