# Verification Record: Server Deployment

Recorded 2026-10-20 on macOS 14.7.6 aarch64 (uv 0.12.19, Python 3.13) and in
`ubuntu:24.04` aarch64 containers, driving the shipped `install.sh`,
`trovium-deploy`, and `trovium-ingest` commands.

## Automated evidence

| Check                                                                                      | Result                            |
| ------------------------------------------------------------------------------------------ | --------------------------------- |
| `scripts/check.sh` (ruff, format, mypy strict, pytest, prettier, markdownlint, shellcheck) | pass                              |
| `pytest`                                                                                   | 243 passed                        |
| `.specify/gates/verify.sh --boundary agent --accept 002-server-deployment`                 | all 11 SC accept blocks pass      |
| `pytest tests/integration/deploy/test_install_local.py -k matrix`                          | 7 passed (5 positive, 2 negative) |
| Deployment suites on linux-aarch64 (ubuntu:24.04)                                          | 136 passed                        |

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
7. Failure reports now keep the actions already taken and, when an upgrade is
   rolled back, record the `rollback` action and its outcome.
8. Install destinations (config, state, data, bin) are validated before the
   config or toolchain is written, so an unwritable path leaves nothing behind.
9. Uninstall verifies its removals: a cache or toolchain it cannot delete now
   produces a named failure and keeps the deployment record for a retry,
   instead of reporting a partial cleanup as success.

## Linux verification (ubuntu:24.04 aarch64)

Run in Docker on the same host, against a read-only checkout:

- The deployment unit, contract, and integration suites: **136 passed** on
  linux-aarch64.
- A real `--locked` bundle (`0.9.0`) was built with the pinned uv 0.12.19 and
  CPython 3.13.16 artifacts, each SHA-256 verified before extraction. The
  bundle carries `toolchain/uv-0.12.19`, `toolchain/python-3.13.16.tar.gz`,
  `LICENSES/LICENSE`, `LICENSES/uv-LICENSE`, and `LICENSES/python-LICENSE`.
- Installed in a **clean** Ubuntu container with no host `uv` and no host
  Python 3.13, with `UV_OFFLINE=1` and dead HTTP/HTTPS/ALL proxies: status `ok`,
  version `0.9.0`, `trovium-ingest --help` exits 0, uninstall removes the
  commands and preserves the config. Bundle install took **2 s**.
- Online path from a local HTTP release fixture (latest resolution): install
  **2.5 s**, identical re-run **43 ms**, status **38 ms**, uninstall **75 ms** —
  all inside the SC-001/SC-003/SC-009/SC-012 targets.
- On `alpine:3.20` (musl), the installer refused with exit 3,
  `unsupported_platform`, the named musl remedy, and no files written.

### Toolchain note

`contracts/bundle.md` describes "static musl" uv/CPython builds. The musl
CPython build is dynamically linked to `/lib/ld-musl-aarch64.so.1` and cannot
run on the supported glibc hosts, so the lock pins **glibc** artifacts instead.
Musl hosts are still refused until that toolchain is verified. This is the only
place the implementation intentionally differs from the contract text.

## CI

`.github/workflows/deploy-linux.yml` runs on `ubuntu-24.04` and
`ubuntu-24.04-arm`: the deployment suites, the executable SC acceptance
criteria, a `--locked` bundle build, an offline install of that bundle, the
toolchain/license assertions, and the Alpine musl refusal. It complements
`gates.yml` and runs the same commands proven above.

## Not independently verified

- **linux-x86_64**: the Docker host is aarch64; x86_64 is covered by the new
  CI workflow but has not run yet.
- **SC-001 on a GitHub-hosted runner**: measured in a clean local container
  (2.5 s online); the CI job records it on a runner from now on.

## Bound task status

All implementation and acceptance tasks are closed. T085 records the container
timings above; T086 records the locked bundle, offline install, and license
artifacts; T087/T117 record the glibc and musl results. T088 records the diff
review and the commit made by the after-implement hook.
