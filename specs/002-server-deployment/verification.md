# Verification Record: Server Deployment

Recorded 2026-10-20 on macOS 14.7.6 aarch64 (uv 0.12.19, Python 3.13),
driving the shipped `install.sh`, `trovium-deploy`, and `trovium-ingest`
commands. Linux release targets were not available on this host; see
[Not independently verified](#not-independently-verified).

## Automated evidence

| Check                                                                                      | Result                            |
| ------------------------------------------------------------------------------------------ | --------------------------------- |
| `scripts/check.sh` (ruff, format, mypy strict, pytest, prettier, markdownlint, shellcheck) | pass                              |
| `pytest`                                                                                   | 241 passed                        |
| `.specify/gates/verify.sh --boundary agent --accept 002-server-deployment`                 | all 11 SC accept blocks pass      |
| `pytest tests/integration/deploy/test_install_local.py -k matrix`                          | 7 passed (5 positive, 2 negative) |

## Quickstart scenarios

An independent agent with no prior context executed `quickstart.md` end to end
against the working tree. After the fixes below, the full sequence was re-run
by the author and passed.

| Scenario                  | Result | Notes                                                                             |
| ------------------------- | ------ | --------------------------------------------------------------------------------- |
| Shared setup              | PASS   | Local `--local` bundle: 8 wheels, `.sha256` sidecar, no `toolchain/`              |
| 1 — local install         | PASS   | `ok`, 0.1.0, config 0600, both commands run                                       |
| 1b — online pinned/latest | PASS   | `degraded` only for the expected `command_path` warning; both versions 0.1.0      |
| 2 — identical re-run      | PASS   | `noop`, empty actions, config unchanged, 1 s                                      |
| 3 — status read-only      | PASS   | No file changes; `installed_commands`/`self_check` pass; <1 s                     |
| 4 — config-file install   | PASS   | Canonical config copied from the supplied file; supplied file unchanged           |
| 5 — offline install       | PASS   | `UV_OFFLINE=1` with dead proxies; also passes with a cold uv cache                |
| 6 — upgrade               | PASS   | `upgrade`, 0.1.0 → 0.2.0, config byte-identical                                   |
| 7 — failed upgrade        | PASS   | Exit 5, `self_check_failed`, failure names `trovium-broken`, active version 0.2.0 |
| 8 — secrets               | PASS   | No credential values in report, stderr, or config; env names only                 |
| 9 — ingest config         | PASS   | Config supplies library/source/enums; CLI override reflected                      |
| 10 — bundle refusal       | PASS   | Exit 4, `bundle_integrity`, named wheel, no state changes                         |
| 11 — uninstall/purge      | PASS   | Commands removed, config and library/source unchanged; purge removes config only  |

Measured local timings: install 2 s (Scenario 1), no-op 1 s, status <1 s,
uninstall <1 s. The SC-001 clean-runner 5-minute target was not measured on a
Linux runner.

## Fixes made after the independent pass

1. **Failure reports dropped the active version.** `trovium-deploy` now
   enriches a CLI-side error report from the deployment record, so a failed
   upgrade reports `version`/`config_path`/`bin_dir` of the still-active
   installation. Bootstrap failures keep the all-null shape.
2. **Uninstall left older wheel caches.** It now removes the whole
   `<state>/trovium/cache` and staging roots, not only the active version's
   directory, and a regression test covers 0.1.0 → 0.2.0 → uninstall.
3. **Quickstart Scenarios 4 and 5 had an incomplete `PATH`.** Their per-case
   `TROVIUM_BIN_DIR` was not on `PATH`, so they correctly reported `degraded`;
   both blocks now export the matching `PATH`.
4. Scenario 11 now inventories the library **and** source with a real media
   file instead of an empty library, so the check is meaningful.
5. Scenario 7's heading says "leaves the previous version active"; the
   post-promotion rollback path is exercised by
   `tests/integration/deploy/test_rollback.py`.
6. A failed CLI start (for example, a wheel corrupt beyond repair) now emits
   the full JSON report with `bundle_invalid` instead of exiting silently.

## Not independently verified

- **Linux glibc x86_64/aarch64 release bundles**, including the bundled uv and
  CPython toolchain and the locked toolchain download. No Linux host or
  container runtime was available here.
- **musl refusal** and a genuine unsupported-platform refusal on a supported
  host. The unit tests cover the policy; the manual pass could not produce the
  host condition without faking `platform.machine()`.
- **SC-001 clean-runner timing**: the 5-minute target is not measurable from a
  local macOS fixture.
- **Locked-bundle license artifacts**: `write_locked_licenses` is unit-tested
  with stubbed responses; the real `uv-LICENSE`/`python-LICENSE` files were not
  produced because they require a Linux `--locked` build.

## Bound task status

The quickstart execution tasks (T041, T061, T078, T084, T116) are satisfied by
the runs above. T085, T086, T087, T088, and T117 stay open where they require a
Linux runner, a real release artifact, or a commit decision.
