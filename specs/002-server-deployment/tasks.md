# Tasks: Server Deployment

**Input**: Design documents from `/specs/002-server-deployment/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included per constitutions XVII/XXIII — every behavior ships with automated coverage, and every success criterion lands as an executable `accept` block. Test tasks are written first and made to fail before implementing.

**Organization**: Tasks are grouped by user story so each increment is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (`US1`, `US2`, `US3`)
- Include exact file paths in descriptions

## Path Conventions

- Single project: `src/trovium/`, `tests/`, `tools/`, and `install.sh` at repository root
- Feature documents: `specs/002-server-deployment/`
- Runtime paths follow `contracts/config-schema.md` and `data-model.md`

### Inline notes for required constraints (quoted from data-model.md / contracts/)

- Deployment report `status` is exactly `ok`, `noop`, `degraded`, `not_installed`, or `error`; `error` is required when status is `error`, and every top-level key is present with `null` where absent (`contracts/report-schema.md`).
- Exit codes are exactly `0` success, `1` internal check not current, `2` misuse, `3` preflight, `4` bundle, `5` install, `6` lock, `7` config (`contracts/cli.md`).
- Config defaults and enums are exactly: `[source] mode` `disk|client`; `[ingest] category` `movie|tv|all`, `mode` `move|copy|hardlink`, `post_ingest` `keep|pause|delete`, `on_fail` `stop|continue`, `json` `compact|pretty`; `[meta] schema_version = 1`; config mode `0600` (`contracts/config-schema.md`).
- Precedence is exactly: explicit CLI > environment > config file > built-in default (`contracts/cli.md`, `data-model.md`).
- Deployment record fields and invariants: `schema_version`, `version`, `previous_version`, `config_path`, `tool_dir`, `bin_dir`, `uv_path`, `python_path`, `commands`, `wheel_cache`, `wheel_sha256`, `bundle_platform`, `last_self_check`, `last_operation`; atomic write, mode `0600`, state dir `0700`, `fcntl.flock` (`data-model.md`).
- Bundle manifest: `schema_version`, `version`, `platform`, `python_version`, `uv_version`, `files`; every digest verified; wheel `METADATA` version equals manifest version; relative paths only (`contracts/bundle.md`).
- No credential value may appear in arguments, config, record, report, or logs. Credentials come only from the environment variables named in config (`contracts/config-schema.md`, constitution I).
- Deployment, upgrade, status, and uninstall never write to the media library, source, or client data; only read-only path validation is allowed (`spec.md` FR-018, SC-005).
- One server, one media library; no scheduling, containers, or multi-server fleet behavior (`spec.md` Clarifications, Out of Scope).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the package, test, and release-tooling skeleton before core modules.

- [x] T001 Run `uv sync` and `scripts/check.sh` to confirm the baseline is green before any change (constitution XIII/XXVI)
- [x] T002 [P] Register `trovium-deploy = "trovium.deploy.cli:main"` in `[project.scripts]` in `pyproject.toml`; update `tests/unit/test_dependency_budget.py` to assert both console scripts and that `[project].dependencies` is exactly `["httpx>=0.27"]`
- [x] T003 [P] Create `src/trovium/deploy/__init__.py`, empty modules `src/trovium/deploy/{cli,installer,bundle,paths,report,selfcheck,state,uv}.py`, and test directories `tests/unit/deploy/`, `tests/contract/deploy/`, `tests/integration/deploy/`, `tests/fixtures/deploy/`
- [ ] T004 [P] Create `tools/release/toolchain.lock.json` with the pinned `uv` and CPython 3.13 artifact versions and SHA-256 digests per release platform, and `tools/release/README.md` documenting the lock format and refresh procedure
- [x] T005 [P] Create `install.sh` at repository root with a Bash 3.2+ shebang, `set -euo pipefail`, usage/options parsing, platform normalization, a `json_error` helper, and shellcheck-clean structure; `json_error` MUST emit the full schema in `contracts/report-schema.md`, not a reduced bootstrap-only shape; do not implement the install flow yet
- [ ] T006 [P] Create `tests/fixtures/deploy/fake_uv.sh` and a skeleton `tests/fixtures/deploy/accept_lib.sh` for temporary XDG homes, bundle caching, and fake uv behavior; make both executable and shellcheck-clean

**Checkpoint**: package entry point, fixture skeleton, and release-tooling lock exist

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Typed core modules every user story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T007 [P] Implement `src/trovium/config.py`: `configparser` schema, `[meta] schema_version = 1`, `[library] root`, `[source] mode/path/client_url/client_username_env/client_password_env`, `[ingest] category/mode/post_ingest/on_fail/json`; enforce enums, URL without userinfo, unknown-key preservation, mode `0600`, parent `0700`, backup-before-migration, and the CLI > environment > config > default precedence contract
- [x] T008 [P] Add unit tests in `tests/unit/deploy/test_config.py` for every key/default/enum, missing explicit `--config`, invalid syntax, userinfo rejection, permission tightening, migration backup, newer-schema warning, and secret-free parsing; assert any migration backup is `config.ini.bak.<timestamp>` with mode 0600 and contains no credential value
- [x] T009 [P] Implement `src/trovium/deploy/report.py`: typed `DeploymentAction`, `DeploymentCheck`, `DeploymentError`, `DeploymentReport`; stable top-level keys with `null`; `schema_version`, `operation`, `status`, `version`, `previous_version`, `config_path`, `install_root`, `bin_dir`, `commands`, `actions`, `checks`, `next_steps`, `error`, `finished_at`; JSON stdout and human stderr; compact/pretty formatting; redaction hook
- [x] T010 [P] Add contract tests in `tests/contract/deploy/test_report.py` asserting every required key, the status/exit-code mapping, `error` required for `error`, state precedence (`error` > `degraded` > `noop` > `ok`), stable nulls, and no secret values
- [x] T011 [P] Implement `src/trovium/deploy/state.py`: `DeploymentRecord` fields exactly as `data-model.md`, `SelfCheckResult`, `LastOperation`; read/validate/write; temp-file + fsync + `os.replace`; mode `0600`; state dir `0700`; `fcntl.flock` lock with a non-blocking attempt and named lock error
- [x] T012 [P] Add unit tests in `tests/unit/deploy/test_state.py` for field validation, absolute paths, atomic replacement, permissions, corrupt records, and lock contention
- [x] T013 [P] Implement `src/trovium/deploy/paths.py`: XDG config/state/data/cache/bin paths with `TROVIUM_*` overrides, platform normalization (`linux-x86_64`, `linux-aarch64`, `darwin-*`), permission checks, and a `/dev/tty` prompt helper that never reads prompts from a piped stdin; detect glibc vs musl (`platform.libc_ver()` and `/lib/ld-musl-*`) and refuse musl with `unsupported_platform` unless the release toolchain has been verified there
- [x] T014 [P] Add unit tests in `tests/unit/deploy/test_paths.py` for every XDG override, unsupported platform, glibc/musl/unknown-libc detection, unwritable path, prompt-vs-no-TTY behavior, and two distinct HOME/XDG roots producing disjoint config/state/data/cache/bin paths
- [x] T015 [P] Implement `src/trovium/deploy/bundle.py`: parse `manifest.json`, verify every listed SHA-256 before use, reject absolute/traversal paths, check platform/version/Python >=3.13, read wheel `METADATA` and `entry_points.txt`, safely extract the Python tarball with `filter="data"`, and expose the wheelhouse, uv, and Python paths
- [x] T016 [P] Add unit tests in `tests/unit/deploy/test_bundle.py` with valid/corrupt manifests, wrong platform/version, traversal paths, missing files, bad wheel metadata, and unsafe Python tarballs
- [x] T017 [P] Implement `src/trovium/deploy/uv.py` as the only uv subprocess boundary: `tool install/uninstall` with `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `--python`, `--no-index`, `--find-links`, `--force`; typed result/error mapping; no secret environment values in argv or logs
- [x] T018 [P] Add unit tests in `tests/unit/deploy/test_uv.py` using `tests/fixtures/deploy/fake_uv.sh` for success, non-zero exit, timeout, missing binary, and exact command/environment construction
- [x] T019 [P] Implement `src/trovium/deploy/selfcheck.py`: discover every `console_scripts` entry from the wheel, run each command with `--help` in a sanitized environment (`HOME`, `PATH`, `LC_ALL=C`, no credential vars) with a short timeout, and return per-command results
- [x] T020 [P] Add unit tests in `tests/unit/deploy/test_selfcheck.py` for multiple entry points, non-zero exit, timeout, traceback-bearing output, and missing executable
- [x] T021 [P] Implement the `trovium-deploy` CLI skeleton in `src/trovium/deploy/cli.py`: argparse subcommands `install`, `check`, `status`, `uninstall`; `--json {compact,pretty}`; exit-code mapping `0/1/2/3/4/5/6/7`; emit the JSON error report on every failure path; keep `install` orchestration stubbed for US1
- [x] T022 [P] Implement `tools/release/build_bundle.py`: build the wheel, hashed wheelhouse from the runtime lock, platform bundle directory, manifest, `VERSION`, tarball, `.sha256`, and latest aliases; support `--local`/`--fast` mode for tests using the host uv/Python and a cached wheelhouse; stage a temporary source tree for `--version` overrides
- [x] T023 [P] Add unit tests in `tools/release/`-adjacent `tests/unit/deploy/test_release_builder.py` for manifest digests, version staging, tar layout, checksum sidecars, and refusal of missing wheel dependencies
- [x] T024 [P] Add `tests/conftest.py` isolation so every test sets `HOME`, `TROVIUM_CONFIG_FILE`, `TROVIUM_STATE_HOME`, `TROVIUM_DATA_HOME`, `TROVIUM_CACHE_HOME`, and `TROVIUM_BIN_DIR` to temporary paths
- [ ] T025 [P] Complete `tests/fixtures/deploy/accept_lib.sh`: `accept_init` creates an isolated temp home/library/source and exports all `TROVIUM_*` paths; `accept_bundle [version]` builds or reuses a cached local test bundle with the host toolchain; `accept_broken_bundle` echoes the broken-bundle fixture path; `accept_inventory` hashes media state; also create `tests/fixtures/deploy/broken-bundle.tar.gz` and its `.sha256` for rollback acceptance; ensure functions are safe to source from `bash -e` accept blocks

**Checkpoint**: config, report, state, paths, bundle, uv, selfcheck, CLI skeleton, and release builder are typed, tested, and green

---

## Phase 3: User Story 1 - Install on a clean server with one command (Priority: P1) 🎯 MVP

**Goal**: One documented command installs every shipped console script from a verified local/remote bundle, creates the config, runs the self-check, records state, and reports the result.

**Independent Test**: From a clean temp HOME, run `install.sh --bundle <local bundle> --non-interactive --library-root <dir> --source <dir>`; verify both commands run, the config exists with mode 0600, status is `ok` or `degraded`, and no root-owned paths were created.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation.**

- [ ] T026 [P] [US1] Contract test in `tests/contract/deploy/test_install_cli.py`: `install.sh` and `trovium-deploy install` options, required `--bundle`, misuse exit 2, local bundle success, report schema, `--json` compact/pretty parity, and no credential values; include an early bootstrap failure (missing prerequisite or unsupported platform) and assert it emits the full report schema; cover commands-present/no-record refusal, `--force` takeover, and direct install from the active tool dir being refused with `install_failed`
- [ ] T027 [P] [US1] Integration test in `tests/integration/deploy/test_install_local.py`: install a locally built bundle into a temp HOME, verify private tool dirs, both console scripts, config mode 0600, source/library values, record fields, and a passing self-check; include a supported/unsupported preflight matrix (`-k matrix`) for SC-002; a second identical install returns `noop` with empty actions and an unchanged config (US1 acceptance 5); add `tests/integration/deploy/test_online_release.py` with a local HTTP fixture that serves `releases/latest/download/VERSION` and the versioned asset under `download/v0.1.0/`; run once without `--version` (default latest) and once with `--version 0.1.0`, asserting both installs produce the same version/config/self-check result (SC-001 online path); a missing or non-executable recorded command with an unchanged version/config forces repair rather than `noop`; cover `--force` adopting an unmanaged installation and the report warning that rollback is unavailable; cover direct install from the active tool dir leaving the installation unchanged; a two-user case installs under two separate HOME/XDG/bin roots and asserts neither install, upgrade, nor uninstall changes the other's commands, config, or state; run the matrix over at least five clean positive cases (disk source, client config, config-file non-interactive, offline bundle, and a second clean HOME/XDG) plus unsupported-platform and missing-prerequisite negative cases, and record pass/fail counts; keep local/matrix/no-op/repair cases in `test_install_local.py`, online and pinned/latest cases in `test_online_release.py`, and `--force`, direct-install, and two-user cases in `test_isolation.py`
- [x] T028 [P] [US1] Unit test in `tests/unit/deploy/test_config_install.py`: generated config includes `[library]`, `[source] mode=disk|client`, `[ingest]` defaults, `schema_version = 1`, and is not written outside the selected path
- [ ] T029 [P] [US1] Integration test in `tests/integration/deploy/test_install_selfcheck.py`: a staged entry point whose `--help` fails prevents promotion, names the command in the report, and leaves the active installation unchanged

### Implementation for User Story 1

- [x] T030 [US1] Complete `install.sh`: parse bootstrap/mode options, detect platform and musl, resolve a local tarball or the versioned/latest release asset, verify the `.sha256` before extraction, extract to a temp dir, and invoke the bundle's `trovium-deploy install` through `uv run --no-project --python <bundle python> --no-index --find-links <wheelhouse> --with <wheel>`; refuse musl with `unsupported_platform` unless the release toolchain has been verified there
- [x] T031 [US1] Implement private toolchain preparation in `src/trovium/deploy/installer.py` + `src/trovium/deploy/uv.py`: copy the pinned uv to `<data>/toolchain/uv-<version>`, extract the Python tarball to `<data>/toolchain/python-<version>/`, verify `bin/python3` >=3.13, and use those exact paths for `uv tool install`
- [x] T032 [US1] Implement config creation in `src/trovium/deploy/installer.py`: interactive prompts for library root and optional source mode, non-interactive flags/env, default `[ingest]` values, mode 0600, parent 0700, and preserve/validate an existing config
- [x] T033 [US1] Wire `src/trovium/deploy/selfcheck.py` into the install flow: stage, run all entry points, promote only after pass, write `last_self_check` to the record, and fail with `self_check_failed` naming the command
- [x] T034 [US1] Implement `install()` in `src/trovium/deploy/installer.py`: preflight platform/arch/paths/config, verify bundle, install into a staging tool dir, self-check, promote, write config, write record, emit report; implement the basic same-version/config no-op: read the record, compare the requested version and effective config, verify every recorded command exists in `bin_dir` and is executable, emit `status: "noop"` with empty actions, and skip staging. If any command is missing, continue to staging/repair instead of reporting noop. Leave the `check` fast path and bundle-cache optimization to US2.
- [x] T035 [US1] Implement the minimal `status` flow in `src/trovium/deploy/installer.py` + `src/trovium/deploy/cli.py`: read the record/config, verify command presence, report version/config/last self-check, and exit 0/3 per `contracts/cli.md`
- [x] T036 [US1] Implement PATH detection/remedy in `src/trovium/deploy/paths.py` + the install report: if `<bin_dir>` is not on `PATH`, add a `command_path` warning with the exact line to add; never edit shell startup files
- [x] T037 [US1] Wire all install failures through `src/trovium/deploy/report.py`: preflight (`3`), bundle (`4`), install/self-check (`5`), lock (`6`), config (`7`); always emit a JSON error report and a human stderr line with a remedy; include failures that occur before the Python CLI starts
- [x] T038 [US1] Add `.github/workflows/release.yml`: tag-driven `v*` workflow. Before building, set up the same gate tooling as `.github/workflows/gates.yml` (checkout, uv, Node, jq, shellcheck, Prettier, markdownlint) and run `UV_FROZEN=1 bash scripts/check.sh`. Build Linux x86_64/aarch64 bundles, upload `VERSION`, `install.sh`, versioned/latest assets and `.sha256` sidecars. Grant `contents: write` only to the release job.
- [x] T039 [US1] Wire `tools/release/build_bundle.py` into the release workflow: download pinned uv/CPython from `tools/release/toolchain.lock.json`, verify published checksums, build the hashed wheelhouse, write the manifest, and produce reproducible tarballs
- [x] T040 [US1] Document the one-command install, local bundle, generated config, status, and PATH remedy in `README.md`; link to `specs/002-server-deployment/contracts/`
- [ ] T041 [US1] Execute `specs/002-server-deployment/quickstart.md` Scenarios 1, 1b, 2, and 3 against the implementation; record the observed results and fix red paths before continuing
- [x] T042 [US1] Run `scripts/check.sh` and confirm the US1 slice is green across ruff, mypy, pytest, Prettier, markdownlint, and shellcheck

**Checkpoint**: US1 is a working MVP from a local bundle; online release packaging is wired but may not have a published release yet

---

## Phase 4: User Story 2 - Install unattended and repeatably (Priority: P2)

**Goal**: Fully non-interactive install from flags/env/config, identical re-runs are fast no-ops, offline bundles work, and integrity/concurrency failures are explicit.

**Independent Test**: Run the fully specified command with no terminal; verify success and a JSON run report. Re-run and verify `noop` under 30 seconds. Repeat with `UV_OFFLINE=1` and a local bundle.

### Tests for User Story 2

- [ ] T043 [P] [US2] Contract test in `tests/contract/deploy/test_unattended.py`: no-TTY behavior, `--non-interactive` missing-input list, config-file install, CLI > env > config precedence, and prompt fallback via `/dev/tty`
- [ ] T044 [P] [US2] Integration test in `tests/integration/deploy/test_repeatable.py`: focus on the US2 fast path and cache — `trovium-deploy check --version` avoids the bundle download, bundle-cache reuse works, and the no-op completes under 30 seconds; the baseline same-version no-op is covered by T027
- [ ] T045 [P] [US2] Integration test in `tests/integration/deploy/test_offline.py`: local bundle install with `UV_OFFLINE=1` and unreachable proxies, no network lookup, self-check and status pass
- [ ] T046 [P] [US2] Contract test in `tests/contract/deploy/test_bundle_refusal.py`: tampered wheel, bad outer checksum, wrong platform, wrong version, and traversal path all exit 4 with `bundle_integrity`/`bundle_invalid` and change nothing
- [ ] T047 [P] [US2] Contract test in `tests/contract/deploy/test_lock.py`: concurrent install/upgrade attempts serialize or one exits 6 with a named lock error and no mixed-version state; two distinct user roots use separate locks and do not block or alter each other
- [ ] T048 [P] [US2] Unit test in `tests/unit/deploy/test_ingest_config.py`: ingest config fallbacks for library/source/client URL, enums, CLI overrides, missing explicit config, and credential env names
- [ ] T049 [P] [US2] Contract test in `tests/contract/deploy/test_run_report.py`: unattended install report includes ordered actions, outcomes, version, config path, no prompts, and redacted secrets

### Implementation for User Story 2

- [x] T050 [US2] Implement non-interactive mode in `src/trovium/deploy/cli.py`/`installer.py`: detect TTY, open `/dev/tty` only for interactive prompts, fail before changes with a complete missing-input list when non-interactive, and reject mode options on `--status`/`--uninstall`
- [x] T051 [US2] Implement config-file input in `src/trovium/deploy/installer.py`/`config.py`: read an explicit `--config` source, copy it to the canonical path only when absent, preserve an existing canonical config, report ignored conflicting CLI values, and migrate with backup
- [x] T052 [US2] Implement the `check` fast path in `src/trovium/deploy/installer.py`/`cli.py`: compare installed version/config/commands with `--version`, emit the standard no-op report when current, exit 1 without stdout when stale
- [x] T053 [US2] Implement `VERSION` resolution and the verified bundle cache in `install.sh`/`src/trovium/deploy/paths.py`: fetch `releases/latest/download/VERSION`, use `trovium-deploy check` before downloading, cache at `<cache>/trovium/bundles/<version>/<platform>.tar.gz`, and reverify the sidecar on reuse
- [x] T054 [US2] Implement the offline install path in `src/trovium/deploy/uv.py`/`installer.py`: always use `--no-index --find-links <wheelhouse>` with the private Python, never contact an index, and fail with `install_failed` if the wheelhouse is incomplete
- [x] T055 [US2] Implement lock acquisition in `src/trovium/deploy/state.py`/`installer.py`: non-blocking `fcntl.flock`, wait briefly, then exit 6 with the lock path and remedy; release on every exit path
- [x] T056 [US2] Implement install-side integrity handling in `src/trovium/deploy/bundle.py`/`installer.py`: outer checksum, manifest entries, wheel metadata, cross-platform refusal, and no executable use before verification; report the exact failing path
- [x] T057 [US2] Complete the unattended run report in `src/trovium/deploy/installer.py`: actions for verify/resolve/cache/stage/self-check/promote/config/record, `next_steps`, and `degraded` for non-fatal path/credential warnings
- [x] T058 [US2] Implement `trovium-ingest --config` in `src/trovium/cli.py`: load the shared config, apply precedence, resolve `[source]` mode/path/client_url, keep existing flags authoritative, and preserve existing exit codes/misuse rules
- [x] T059 [US2] Add regression tests in `tests/contract/test_cli_contract.py` and `tests/integration/test_disk_ingest.py` proving existing ingest flag behavior is unchanged when no config exists
- [x] T060 [US2] Document non-interactive install, config-file reuse, offline installation, and config precedence in `README.md` and `docs/` if present
- [ ] T061 [US2] Execute `specs/002-server-deployment/quickstart.md` Scenarios 4, 5, and 9; record results and fix red paths
- [x] T062 [US2] Run `scripts/check.sh` and confirm the US2 slice is green

**Checkpoint**: unattended, repeatable, offline, integrity-safe installation works independently of upgrade/uninstall

---

## Phase 5: User Story 3 - Upgrade and remove without losing configuration or media (Priority: P3)

**Goal**: Upgrade/downgrade through the same install command, roll back a failed upgrade, and uninstall while preserving config/media by default.

**Independent Test**: Install 0.1.0, customize config, upgrade to 0.2.0, verify config is byte-identical and the new version is active. Force a failed upgrade and verify 0.2.0 remains active. Uninstall and verify commands are gone while config and a sampled media tree are unchanged; repeat with `--purge`.

### Tests for User Story 3

- [ ] T063 [P] [US3] Contract test in `tests/contract/deploy/test_upgrade.py`: upgrade operation/version fields, config preservation, same-command upgrade, downgrade by pinned bundle, and no partial activation on self-check failure
- [ ] T064 [P] [US3] Integration test in `tests/integration/deploy/test_upgrade.py`: 0.1.0 → 0.2.0 upgrade with a customized config, byte-identical config, new commands, preserved media inventory, and a `-k media_integrity` case covering install/upgrade/downgrade/uninstall inventories (SC-005)
- [ ] T065 [P] [US3] Contract test in `tests/contract/deploy/test_uninstall.py`: uninstall/purge/no-op statuses, config preserved by default, purge removes config only, commands/symlinks removed, media untouched; cover no-record no-op and no-record `--purge` removing only the config
- [ ] T066 [P] [US3] Integration test in `tests/integration/deploy/test_rollback.py`: a broken staged self-check leaves the previous version active or restores it from cache, the failure names the command, and `-k recovery` parametrizes at least five interruption points: (1) after bundle verification but before toolchain copy, (2) after toolchain copy but before staging install, (3) after staging install but before the staged self-check, (4) after the staged self-check but before promotion, (5) after promotion but before the record write. Each case asserts rerun convergence and no false success (SC-006).
- [ ] T067 [P] [US3] Unit test in `tests/unit/deploy/test_state.py`: cached wheel/previous-version record updates, rollback record invariants, interrupted-promotion recovery, and atomic record writes that leave a recoverable state if interrupted before `os.replace`

### Implementation for User Story 3

- [x] T068 [US3] Implement the wheel cache in `src/trovium/deploy/state.py`/`installer.py`: cache `<state>/cache/<version>/` wheelhouse and wheel with SHA-256, retain the previous version for rollback, and never overwrite a valid cache silently
- [x] T069 [US3] Implement staging/promotion/rollback in `src/trovium/deploy/installer.py`: install to staging, self-check, promote only on pass; on active self-check failure reinstall the cached previous wheel and report `rollback_failed` if restoration fails; detect execution from the active `tool_dir` and refuse with a remedy to use `install.sh`, allowing only the bootstrap's ephemeral environment to run install; when `--force` adopts an unmanaged installation, record that no previous cached wheel exists and report rollback as unavailable
- [x] T070 [US3] Implement upgrade/downgrade config handling in `src/trovium/deploy/config.py`/`installer.py`: preserve valid values, migrate known older schemas with a timestamped backup, preserve unknown keys, and warn/refuse without rewriting a newer schema; the pre-migration backup MUST be created with mode 0600
- [x] T071 [US3] Complete `status` in `src/trovium/deploy/installer.py`: active version, config path, command presence, path/credential warnings, last self-check, last operation, and read-only behavior under 5 seconds
- [x] T072 [US3] Implement uninstall in `src/trovium/deploy/installer.py`: read the record, `uv tool uninstall` with recorded tool/bin dirs, remove the state record/cache/private toolchain, preserve config/media, and report actions
- [x] T073 [US3] Implement the uninstall fallback in `src/trovium/deploy/installer.py`/`paths.py`: if the recorded uv is missing, remove only recorded bin symlinks pointing into the recorded tool dir and the recorded tool dir; refuse to touch anything else
- [x] T074 [US3] Implement `--purge`: remove the recorded config file when a record exists; when no record exists, remove only the configured/default config file (`TROVIUM_CONFIG_FILE` or the XDG default) if present. Never remove media, source, or client data. Report `purge_config` only when a file was removed.
- [x] T075 [US3] Implement `install.sh --status` and `install.sh --uninstall [--purge]`: resolve a bundle, invoke the bundle's `trovium-deploy` in an ephemeral uv environment, and keep stdout JSON-only for the no-op/removal report
- [ ] T076 [US3] Verify reboot/persistence behavior in `src/trovium/deploy/paths.py`/docs: commands in the user bin dir, no daemon, no login dependency, and status remediation for a missing PATH entry
- [x] T077 [US3] Document upgrade, dirty-config handling, rollback, uninstall, and purge in `README.md`; warn that purge never touches media
- [ ] T078 [US3] Execute `specs/002-server-deployment/quickstart.md` Scenarios 6–8, 10, and 11; record results and fix red paths
- [x] T079 [US3] Run `scripts/check.sh` and confirm the US3 slice is green

**Checkpoint**: all three user stories work independently; upgrade/uninstall preserve config and media

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final hardening and documentation that spans the stories.

- [ ] T080 [P] Security audit `src/trovium/config.py`, `src/trovium/deploy/report.py`, `install.sh`, and reports for secret leakage; add regression tests for URLs with userinfo, credential env names, and error paths
- [x] T081 [P] Re-run/update `tests/unit/test_dependency_budget.py` to prove `httpx` remains the only runtime dependency and both console scripts are registered
- [x] T082 [P] Update `README.md` with a concise install/upgrade/status/uninstall reference, offline bundle instructions, config precedence, and the single-library/no-scheduling boundary
- [x] T083 [P] Clean up dead code, naming, and error messages in `src/trovium/deploy/`, `src/trovium/config.py`, `install.sh`, and `tools/release/`; keep mypy strict clean
- [ ] T084 Execute all `specs/002-server-deployment/quickstart.md` scenarios in order on the development host; record pass/fail and timings
- [ ] T085 Run `scripts/check.sh` plus timing checks for SC-001 (install), SC-003 (no-op), SC-009 (uninstall), and SC-012 (status); record the clean-runner online install duration against the 5-minute SC-001 target. The spec-gate accept blocks run under a 30-second watchdog, so T089 is a functional check; the 5-minute metric is recorded here. Record the SC-002 matrix pass counts alongside the timings.
- [ ] T086 Verify the release bundle contains no new runtime Python dependency, includes uv/Python licenses, and that a local bundle installs with `UV_OFFLINE=1`
- [ ] T087 Perform a Linux smoke test on glibc and, if available, musl/Alpine. If musl is not verified, confirm the installer refuses it with `unsupported_platform` and document the limitation in `README.md`; do not claim live musl verification unless it was performed.
- [ ] T088 Review the diff for accidental edits to `.specify/**`, `.opencode/commands/**`, or protected files; commit only feature files and the intentional `pyproject.toml`/`README.md`/workflow changes

---

## Phase 7: Executable acceptance criteria

**Purpose**: Encode SC-001–SC-010 and SC-012 as the fenced `accept` blocks the spec-conformance gate executes. Each block uses `tests/fixtures/deploy/accept_lib.sh` to create an isolated temp home and a cached local bundle, then drives `install.sh`/`trovium-deploy` rather than internal functions. SC-011 was retired with scheduling.

- [ ] T089 SC-001: one install command creates a working installation via `install.sh`

```accept
# verifies: SC-001 — one install command creates a working installation
source tests/fixtures/deploy/accept_lib.sh
accept_init
bundle=$(accept_bundle)
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --source "$ACCEPT_SOURCE" \
  --json compact > "$ACCEPT_ROOT/install.json"
jq -e '.status == "ok" or .status == "degraded"' "$ACCEPT_ROOT/install.json" >/dev/null
jq -e '.version != null and .config_path != null and (.commands | length) >= 1' "$ACCEPT_ROOT/install.json" >/dev/null
test -x "$TROVIUM_BIN_DIR/trovium-ingest"
"$TROVIUM_BIN_DIR/trovium-ingest" --help >/dev/null
```

- [ ] T090 SC-002: first-attempt success across the supported preflight matrix via `tests/integration/deploy/test_install_local.py`

```accept
# verifies: SC-002 — supported preflight matrix succeeds and failures name a cause before changes
uv run --quiet pytest -q -p no:cacheprovider tests/integration/deploy/test_install_local.py -k matrix
```

- [ ] T091 SC-003: identical re-run is a fast no-op via `install.sh`

```accept
# verifies: SC-003 — an identical re-run makes zero changes in under 30 seconds
source tests/fixtures/deploy/accept_lib.sh
accept_init
bundle=$(accept_bundle)
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --source "$ACCEPT_SOURCE" \
  --json compact > "$ACCEPT_ROOT/first.json"
before=$(cksum "$TROVIUM_CONFIG_FILE")
start=$(date +%s)
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --json compact > "$ACCEPT_ROOT/second.json"
end=$(date +%s)
test $((end - start)) -lt 30
jq -e '.status == "noop" and (.actions | length) == 0' "$ACCEPT_ROOT/second.json" >/dev/null
test "$before" = "$(cksum "$TROVIUM_CONFIG_FILE")"
```

- [ ] T092 SC-004: unattended install emits a run report via `install.sh`

```accept
# verifies: SC-004 — unattended install completes without prompts and emits a run report
source tests/fixtures/deploy/accept_lib.sh
accept_init
bundle=$(accept_bundle)
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --source "$ACCEPT_SOURCE" \
  --json compact > "$ACCEPT_ROOT/install.json" < /dev/null
jq -e '(.status == "ok" or .status == "degraded") and (.actions | length) > 0' "$ACCEPT_ROOT/install.json" >/dev/null
jq -e '.config_path != null and .version != null' "$ACCEPT_ROOT/install.json" >/dev/null
```

- [ ] T093 SC-005: install/upgrade/downgrade/uninstall never modify media via `tests/integration/deploy/test_upgrade.py`

```accept
# verifies: SC-005 — no deployment operation modifies or deletes media files
uv run --quiet pytest -q -p no:cacheprovider tests/integration/deploy/test_upgrade.py -k media_integrity
```

- [ ] T094 SC-006: interrupted operations recover without false success via `tests/integration/deploy/test_rollback.py`

```accept
# verifies: SC-006 — interrupted operations recover on rerun and never report false success
uv run --quiet pytest -q -p no:cacheprovider tests/integration/deploy/test_rollback.py -k recovery
```

- [ ] T095 SC-007: secrets never appear in output via `install.sh` and `trovium-deploy status`

```accept
# verifies: SC-007 — secrets never appear in reports, config, or logs
source tests/fixtures/deploy/accept_lib.sh
accept_init
mkdir -p "$(dirname "$TROVIUM_CONFIG_FILE")"
printf '[library]\nroot = %s\n' "$ACCEPT_LIBRARY" > "$TROVIUM_CONFIG_FILE"
chmod 600 "$TROVIUM_CONFIG_FILE"
export TROVIUM_CLIENT_USERNAME=admin
export TROVIUM_CLIENT_PASSWORD=super-secret-acceptance-value
bundle=$(accept_bundle)
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --client-url http://127.0.0.1:8080 \
  --json pretty > "$ACCEPT_ROOT/install.json" 2> "$ACCEPT_ROOT/install.err"
trovium-deploy status --json pretty > "$ACCEPT_ROOT/status.json" 2>> "$ACCEPT_ROOT/install.err"
test -z "$(grep -R 'super-secret-acceptance-value' "$ACCEPT_ROOT" "$TROVIUM_CONFIG_FILE" 2>/dev/null)"
test "$(uv run --quiet python -c 'import os,sys; print(f"{os.stat(sys.argv[1]).st_mode & 0o777:o}")' "$TROVIUM_CONFIG_FILE")" = "600"
backups=$(find "$(dirname "$TROVIUM_CONFIG_FILE")" -maxdepth 1 -name 'config.ini.bak.*' -type f)
test -n "$backups"
for backup in $backups; do
  test "$(uv run --quiet python -c 'import os,sys; print(f"{os.stat(sys.argv[1]).st_mode & 0o777:o}")' "$backup")" = "600"
done
unset TROVIUM_CLIENT_USERNAME TROVIUM_CLIENT_PASSWORD
```

- [ ] T096 SC-008: upgrade preserves config and failed upgrade rolls back via `install.sh`

```accept
# verifies: SC-008 — upgrade preserves config and a failed upgrade keeps the previous version
source tests/fixtures/deploy/accept_lib.sh
accept_init
old=$(accept_bundle 0.1.0)
new=$(accept_bundle 0.2.0)
bash install.sh --bundle "$old" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --source "$ACCEPT_SOURCE" \
  --json compact > "$ACCEPT_ROOT/install.json"
printf '\n# operator note\n' >> "$TROVIUM_CONFIG_FILE"
cp "$TROVIUM_CONFIG_FILE" "$ACCEPT_ROOT/config.before"
bash install.sh --bundle "$new" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --json compact > "$ACCEPT_ROOT/upgrade.json"
jq -e '.operation == "upgrade" and .version == "0.2.0" and .previous_version == "0.1.0"' "$ACCEPT_ROOT/upgrade.json" >/dev/null
cmp "$TROVIUM_CONFIG_FILE" "$ACCEPT_ROOT/config.before"
rc=0
broken=$(accept_broken_bundle)
bash install.sh --bundle "$broken" \
  --non-interactive --library-root "$ACCEPT_LIBRARY" \
  --json compact > "$ACCEPT_ROOT/broken.json" || rc=$?
test "$rc" -ne 0
"$TROVIUM_BIN_DIR/trovium-deploy" status --json compact | jq -e '.version == "0.2.0"' >/dev/null
```

- [ ] T097 SC-009: uninstall removes commands and preserves config/media via `trovium-deploy uninstall`

```accept
# verifies: SC-009 — uninstall removes commands, preserves config/media, and purge removes config only
source tests/fixtures/deploy/accept_lib.sh
accept_init
printf 'media' > "$ACCEPT_LIBRARY/keep.me"
before=$(cksum "$ACCEPT_LIBRARY/keep.me")
bundle=$(accept_bundle)
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --source "$ACCEPT_SOURCE" \
  --json compact > "$ACCEPT_ROOT/install.json"
trovium-deploy uninstall --json compact > "$ACCEPT_ROOT/uninstall.json"
test ! -e "$TROVIUM_BIN_DIR/trovium-ingest"
test -f "$TROVIUM_CONFIG_FILE"
test "$before" = "$(cksum "$ACCEPT_LIBRARY/keep.me")"
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --source "$ACCEPT_SOURCE" \
  --json compact > "$ACCEPT_ROOT/reinstall.json"
trovium-deploy uninstall --purge --json compact > "$ACCEPT_ROOT/purge.json"
test ! -e "$TROVIUM_CONFIG_FILE"
test "$before" = "$(cksum "$ACCEPT_LIBRARY/keep.me")"
```

- [ ] T098 SC-010: offline install succeeds via `install.sh`

```accept
# verifies: SC-010 — a local bundle installs with outbound network access disabled
source tests/fixtures/deploy/accept_lib.sh
accept_init
bundle=$(accept_bundle)
UV_OFFLINE=1 HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 \
  bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --source "$ACCEPT_SOURCE" \
  --json compact > "$ACCEPT_ROOT/install.json"
jq -e '.status == "ok" or .status == "degraded"' "$ACCEPT_ROOT/install.json" >/dev/null
"$TROVIUM_BIN_DIR/trovium-ingest" --help >/dev/null
```

- [ ] T099 SC-012: status is fast and read-only via `trovium-deploy status`

```accept
# verifies: SC-012 — status reports version/config/self-check in under 5 seconds without changing state
source tests/fixtures/deploy/accept_lib.sh
accept_init
bundle=$(accept_bundle)
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$ACCEPT_LIBRARY" --source "$ACCEPT_SOURCE" \
  --json compact > "$ACCEPT_ROOT/install.json"
before=$(find "$TROVIUM_STATE_HOME" "$TROVIUM_CONFIG_FILE" -type f -exec cksum {} + | sort)
start=$(date +%s)
trovium-deploy status --json compact > "$ACCEPT_ROOT/status.json"
end=$(date +%s)
test $((end - start)) -lt 5
jq -e '.operation == "status" and .version != null and .config_path != null' "$ACCEPT_ROOT/status.json" >/dev/null
jq -e '[.checks[] | select(.name == "self_check" and .status == "pass")] | length == 1' "$ACCEPT_ROOT/status.json" >/dev/null
after=$(find "$TROVIUM_STATE_HOME" "$TROVIUM_CONFIG_FILE" -type f -exec cksum {} + | sort)
test "$before" = "$after"
```

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies; start immediately.
- **Foundational (Phase 2)**: depends on Setup; blocks all user stories.
- **US1 (Phase 3)**: depends on Foundational. This is the MVP.
- **US2 (Phase 4)**: depends on US1; extends the install path with unattended, repeatable, offline, and config-file behavior.
- **US3 (Phase 5)**: depends on US1; extends the install path with upgrade/rollback/uninstall.
- **Polish (Phase 6)**: depends on US1–US3.
- **Acceptance (Phase 7)**: depends on all implementation and Polish; blocks are enforced only when `spec.md` is marked `Complete`.

### User Story Dependencies

- **US1**: independent MVP once Foundational is complete.
- **US2**: requires US1's install/config/report/self-check path; independently testable after US1.
- **US3**: requires US1's staging/install path; independently testable after US1. It can run in parallel with US2 only if file ownership is split, because both touch `installer.py` and `cli.py`.

### Within Each User Story

- Tests are written first and must fail before implementation.
- Config/state/report models precede installer wiring.
- Staging/self-check precedes promotion.
- Upgrade/rollback is implemented before uninstall claims are validated.
- Each story ends with a `scripts/check.sh` checkpoint.

### Parallel Opportunities

- Setup: T002–T006 are different files and can run in parallel.
- Foundational: config, report, state, paths, bundle, uv, selfcheck, CLI skeleton, and release builder are separate files (T007–T020); mark only the independent ones `[P]`.
- US1 tests T026–T029 are independent test files; release workflow T038 and docs T040 can run alongside the installer after the interface stabilizes.
- US2 tests T043–T049 are independent test files.
- US3 tests T063–T067 are independent test files.
- Acceptance pytest blocks T090, T093, and T094 are independent; real-install blocks T089, T091, T092, T095–T099 share the acceptance bundle cache and should run sequentially.

---

## Parallel Example: User Story 1

```bash
# Launch the independent test files together:
Task: "Contract test for install CLI in tests/contract/deploy/test_install_cli.py"
Task: "Integration test for local bundle install in tests/integration/deploy/test_install_local.py"
Task: "Unit test for generated config in tests/unit/deploy/test_config_install.py"
Task: "Unit test for self-check in tests/unit/deploy/test_selfcheck.py"
```

## Parallel Example: Foundational

```bash
# Launch independent core modules together:
Task: "Implement config in src/trovium/config.py"
Task: "Implement report in src/trovium/deploy/report.py"
Task: "Implement state in src/trovium/deploy/state.py"
Task: "Implement paths in src/trovium/deploy/paths.py"
Task: "Implement bundle in src/trovium/deploy/bundle.py"
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational.
3. Complete Phase 3: US1.
4. **STOP and VALIDATE**: install from a local bundle in a temp HOME, run both commands, check status/config.
5. The online release workflow can be completed after the local path is proven.

### Incremental Delivery

1. Setup + Foundational → typed core ready.
2. US1 → one-command install from a local/verified bundle (MVP).
3. US2 → unattended, config-file, repeatable, offline install.
4. US3 → upgrade, rollback, uninstall, purge.
5. Polish → docs, security, timing, no-regression checks.
6. Acceptance → mark `spec.md` Complete and let the spec gate execute SC blocks.

### Notes

- `[P]` tasks touch different files and have no incomplete dependencies.
- Do not claim live Linux verification from macOS-only tests; record the exercised surfaces honestly.
- Commit after each logical group; keep `scripts/check.sh` green at every checkpoint.
- Do not weaken gates or edit `.specify/gates/policy.json`.
