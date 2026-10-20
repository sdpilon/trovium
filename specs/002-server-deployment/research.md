# Research: Server Deployment

**Feature**: `002-server-deployment` | **Date**: 2026-10-19

All technical unknowns from the plan's Technical Context are resolved below.
No `NEEDS CLARIFICATION` items remain.

## Decisions

### D1. Native, per-user installation through a private uv tool environment

**Decision**: Install trovium with `uv tool install` into
`${XDG_DATA_HOME:-~/.local/share}/trovium/tools`, linking console scripts into
`${TROVIUM_BIN_DIR:-~/.local/bin}`. The installer never escalates privileges and
never writes to system locations.

**Rationale**: `uv` is already the project's canonical toolchain, supports
user-scoped tool installs and managed Python, and needs no new runtime
dependency. A private tool directory keeps trovium's environment isolated from
any developer checkout or another uv tool. The deployment record stores the
exact directories so status and uninstall do not guess.

**Alternatives considered**:

- `pipx`: another tool to bootstrap and depend on; no advantage over uv.
- System packages or `/usr/local`: requires root and violates the user-scoped
  default.
- Container image: explicitly out of scope; adds a runtime dependency and a
  different operational model.
- Editable install from a checkout: not a server install and would couple the
  server to a repository checkout.

### D2. A thin Bash bootstrap plus a typed Python deployment CLI

**Decision**: Ship `install.sh` as a small Bash 3.2+ bootstrap. It detects the
platform, resolves a local or remote bundle, verifies checksums, extracts it,
and invokes `trovium-deploy install` from the bundle's wheel using the bundled
`uv` and Python. All lifecycle logic lives in typed Python under
`src/trovium/deploy/`.

**Rationale**: A clean server may have neither Python 3.13 nor uv, so a shell
entry point is unavoidable. Keeping the shell layer minimal limits untested
logic and lets the substantive behavior use mypy, pytest, and the project's
normal error model. The bootstrap runs the bundle's `trovium-deploy` through an
ephemeral `uv run` environment, so the installer never executes from the tool
environment it is about to replace. The `trovium-deploy` console script is also
installed for status and uninstall. The bootstrap can run status and uninstall
from a bundle when the installed command is missing or broken.

**Alternatives considered**:

- Pure shell installer: difficult to test, hard to keep typed and consistent,
  and would duplicate config/report logic.
- Python zipapp only: still requires a Python runtime, so it does not solve the
  clean-server bootstrap.
- `curl | sh` only: works for online installs but cannot satisfy offline
  installation or checksum verification of a local bundle.
- `pip install` from PyPI: online-only and does not give an offline bundle
  path.

### D3. Self-contained platform bundles with a wheelhouse, uv, and CPython

**Decision**: A release bundle is a platform-specific `.tar.gz` containing:

- `manifest.json` with version, platform, pinned tool versions, and SHA-256
  digests for every listed file;
- `wheelhouse/` with the trovium wheel and every runtime dependency wheel;
- `toolchain/uv-<version>` (static Linux musl build on Linux);
- `toolchain/python-<version>.tar.gz` (static CPython standalone);
- `install.sh` and third-party license notices.

The outer tarball has a detached `.sha256` sidecar. The bootstrap verifies the
sidecar before extracting or executing any bundled tool; the deploy CLI then
verifies every manifest entry before using the wheelhouse, uv, or Python. A
locally extracted directory is accepted only by the already-running deploy CLI,
which verifies the manifest before use.

**Rationale**: The same artifact works online and offline, and a clean server
needs no preinstalled Python or uv. A wheelhouse plus `uv tool install
--no-index --find-links` was validated locally; it installs trovium and its
dependencies with no network. Bundling CPython is required because `uv` cannot
build a tool environment from a runtime that is not present, and a clean
offline server has no Python. The Python tarball is unpacked into a private,
versioned toolchain directory so installed environments do not reference a
deleted temporary bundle.

**Alternatives considered**:

- Online-only `uv tool install` from PyPI: fails offline and gives no
  reproducible artifact set.
- Bundle only the trovium wheel: `uv` would still need `httpx` and its
  dependencies, and offline resolution would fail.
- Bundle a prebuilt virtual environment: opaque, platform-specific, harder to
  verify, and duplicates uv's environment management.
- Require Python on the server: violates FR-001 and the no-preinstalled-runtime
  requirement.
- Use the system `uv` only: not present on a clean server and not reproducible.

### D4. INI configuration through the standard library

**Decision**: Use a single INI file at
`${XDG_CONFIG_HOME:-~/.config}/trovium/config.ini`, parsed and written with
`configparser` (`interpolation=None`). It carries a `[meta] schema_version`,
`[library]`, `[source]`, and `[ingest]` sections. Credentials are represented by
environment-variable names, never values.

**Rationale**: INI is human-editable, supports sections and comments, and
`configparser` provides reading and writing in the standard library. TOML would
need a third-party writer (the runtime budget is exactly `httpx`); JSON is less
comfortable for hand editing; YAML would add a dependency. The file is created
with mode 0600 so a user who adds a secret later still has an owner-only file.

**Alternatives considered**:

- TOML with `tomllib`: read-only in the standard library, so migration and
  updates would need a custom writer.
- JSON: valid but poor for comments and hand editing.
- `.env`: flat and awkward for enums, sections, and validation.
- YAML: requires a new runtime dependency.

### D5. One JSON deployment record plus an advisory lock

**Decision**: Store deployment state in
`${XDG_STATE_HOME:-~/.local/state}/trovium/deployment.json`, written atomically
(temp file, fsync, `os.replace`, mode 0600). Serialize deployment operations
with `fcntl.flock` on `deploy.lock` in the same directory. A concurrent
operation either waits briefly or exits with a named lock error.

**Rationale**: The record is inspectable, has no database dependency, and is the
single source of truth for status, upgrade, and uninstall. Atomic replacement
avoids half-written state. The lock prevents two installs from interleaving
staging and promotion. The spec allows waiting or a clear failure; a short
non-blocking attempt followed by a named failure keeps unattended runs from
hanging indefinitely.

**Alternatives considered**:

- SQLite: hidden state, extra complexity, and unnecessary for one record.
- Environment variables only: not durable across sessions.
- A file written without locking: two upgrades can corrupt each other.
- Relying on uv's own lock: uv does not coordinate the surrounding config,
  self-check, and record updates.

### D6. Stage, self-check, then promote; cache the previous wheel for rollback

**Decision**: Install the requested version into a staging tool directory with
`uv tool install --no-index --find-links <wheelhouse> --force`. Discover every
`console_scripts` entry point from the wheel, run each one with `--help` in a
sanitized environment, and only then install the same wheel into the active
private tool directory. If the active self-check fails, reinstall the cached
previous wheel and report the rollback. Successful installs cache their wheel
and wheelhouse under the state directory.

**Rationale**: The spec requires the previous working version to remain active
or be restored when a new version fails (FR-013, FR-022). Staging gives a
non-destructive check before the active environment changes; the cached
previous wheel makes restoration possible without network access. The
self-check uses `--help`, which is non-destructive and does not require config
or client access. Because install and upgrade run from the bundle's ephemeral
environment, promotion never replaces the running installer process. A same
version and effective config short-circuits before staging; the `check` fast
path and bundle cache are optimizations layered on top.

**Alternatives considered**:

- In-place `uv tool install --force`: a failed self-check would leave the user
  without a working version.
- Symlink swap of the whole tool environment: depends on uv layout details and
  breaks console-script links unless carefully rebuilt.
- Trust the new version without a self-check: violates FR-005/FR-013.
- Re-download the previous version during rollback: fails offline.

### D7. A stable JSON run report on stdout, a human summary on stderr

**Decision**: Every `install`, `status`, and `uninstall` invocation emits one
JSON report to stdout, matching `contracts/report-schema.md`, and a short
human-readable summary to stderr. Errors also produce a JSON report with a
named `error` object, a remedy, and a non-zero exit code. Secrets and
credential values never appear in either stream.

**Rationale**: This follows the project's Unix-contract style and the existing
`trovium-ingest` record. Automation can consume stdout without parsing prose,
while an operator sees a concise summary. Emitting a report on failure satisfies
FR-017 and FR-023 without inventing a second logging format. Failures in the
bootstrap before the Python CLI starts emit the same full report schema with
null or empty path/list fields and a populated error object, so the contract
holds end to end.

**Alternatives considered**:

- Human-only output: not machine-readable.
- Log files: hidden state and an extra artifact to rotate.
- JSON on stderr: would conflate diagnostics and records.

### D8. Bundle resolution, version probing, and a verified bundle cache

**Decision**: The bootstrap defaults to
`https://github.com/sdpilon/trovium/releases`. Each release publishes:

- a plain-text `VERSION` asset containing the current version;
- `trovium-<version>-<platform>.tar.gz` and its `.sha256`;
- `trovium-latest-<platform>.tar.gz` and its `.sha256` aliases.

For a specific version the bootstrap uses the versioned asset. For the default
latest it reads `releases/latest/download/VERSION`, then uses the versioned
asset. Before downloading the bundle, if no config-changing mode options were
supplied and an installed `trovium-deploy` is available, the bootstrap runs
`trovium-deploy check --version <resolved version>`; when the installation is
already current, that command emits the standard no-op report and exits 0.
Downloaded bundles are cached under
`${XDG_CACHE_HOME:-~/.cache}/trovium/bundles/<version>/` with their sidecars and
reused only after checksum verification. A local `--bundle` bypasses the
network but still requires integrity data.

**Rationale**: The `VERSION` asset makes the online `latest` path cheap without
JSON parsing, and the installed `check` command makes an identical re-run fast
(SC-003) instead of downloading a large bundle every time. The cache makes
repeat installs and offline reinstalls practical while preserving the "latest
stable" default. GitHub's `releases/latest/download/<asset>` redirect is stable
and needs no API call. Versioned asset names keep pinned installs reproducible.

**Alternatives considered**:

- Always download the bundle: correct but wasteful and can miss SC-003 on slower
  links.
- GitHub Releases API: extra API surface, rate limits, and JSON parsing in the
  bootstrap.
- A custom release index service: unnecessary infrastructure.
- Reusing `latest` forever from cache: would silently stop seeing new releases.
- PyPI only: no offline bundle and no pinned toolchain.

### D9. Configuration is shared with the ingest step

**Decision**: Add a `--config PATH` option to `trovium-ingest` and make
configuration values the fallback for run options. Precedence is:
explicit CLI option > environment variable > config file > built-in default.
An explicitly supplied `--config` that is missing is an error; the default
config path is optional. The deployment installer writes the same schema and
records its path.

**Rationale**: A configuration file is only useful if the pipeline reads it.
This keeps `trovium-ingest` usable with flags as before while letting a server
operator set the library root, source, placement mode, and defaults once.
Credentials remain environment-only. The change is additive and covered by
regression tests for the existing flag behavior.

**Alternatives considered**:

- Deployment-only config: the file would not affect pipeline runs, which would
  surprise users.
- A wrapper script that translates config to flags: another surface to test and
  document.
- Environment-only configuration: the user explicitly prioritized config files.

### D10. Secrets stay out of arguments, files, and reports

**Decision**: No credential value is accepted as a command-line option. The
config stores only the names of environment variables that hold the username
and password. The installer and status check presence as a boolean and redact
anything that looks like userinfo in a URL. The config file and state record are
created 0600; an existing config's permissions are tightened to 0600 when the
installer touches it.

**Rationale**: This satisfies constitution I and FR-011 while keeping unattended
installs practical: automation exports the credential variables before running
the installer. Storing references rather than values also means rotating a
credential does not require editing config.

**Alternatives considered**:

- Secret CLI flags: leak through process lists and shell history.
- Secrets in the config file: risks accidental commits and backups.
- A secret manager integration: explicitly out of scope.

### D11. A tag-driven release workflow builds the bundles

**Decision**: Add `.github/workflows/release.yml`, triggered by `v*` tags. It
runs the canonical quality gate, builds the wheel and a hashed wheelhouse,
downloads the pinned uv and CPython artifacts from
`tools/release/toolchain.lock.json`, builds Linux x86_64 and aarch64 bundles,
creates the GitHub release, and uploads versioned assets, `latest` aliases,
`install.sh`, and checksums. A local `tools/release/build_bundle.py` uses the
same code path for tests and offline preparation.

**Rationale**: Installation is only real if release artifacts exist. Pinning uv
and Python, hashing every file, and publishing `latest` aliases make online and
offline installs use the same verified artifact. Keeping the builder in-repo
lets contributors reproduce a bundle locally and lets tests exercise the real
layout.

**Alternatives considered**:

- Manual release assembly: easy to drift and hard to verify.
- Building bundles on the target server: defeats the clean-server promise and
  requires a toolchain.
- Publishing only source archives: the bootstrap would have to build, which
  needs Python and network.

### D12. Uninstall uses recorded paths, then falls back safely

**Decision**: `trovium-deploy uninstall` reads the deployment record, runs
`uv tool uninstall trovium` with the recorded tool and bin directories, and
removes only paths the record identifies. If the recorded uv is unavailable, it
removes the recorded bin symlinks that point into the recorded tool directory
and then removes that directory. It removes the state record, cache, and private
toolchain. Configuration remains unless `--purge` is supplied; the media library
and download paths are never touched. A missing installation is a successful
no-op. `install.sh --uninstall` resolves a bundle and runs the same engine when
the installed command is missing or broken, so removal and the no-op case do
not depend on a surviving installation.

**Rationale**: This meets FR-014 and remains reversible even if the private uv
binary is damaged or deleted. The fallback is restricted to recorded paths, so
it cannot delete an unrelated uv tool or a developer checkout. The tool
environment is removed while the uninstall process is running; this is safe on
Linux and macOS because loaded code remains mapped, and the report is written to
already-open streams. The implementation must not import tool modules after
removal.

**Alternatives considered**:

- Require uv to uninstall: a broken toolchain would strand the installation.
- `rm -rf` of guessed XDG directories: too broad and risks unrelated data.
- Delete configuration by default: violates the spec's preserve-by-default rule.

### D13. Linux is the release target; macOS is a development path

**Decision**: Publish Linux x86_64 and aarch64 bundles using static musl `uv`
and CPython standalone builds, which run on both glibc and musl hosts. Allow the
deploy CLI and the local bundle builder to run on macOS for development and
integration tests. Refuse unsupported platforms with a named error and remedy.

**Rationale**: The spec names Linux servers. Using static musl toolchain builds
avoids a glibc/musl artifact split while the wheelhouse remains pure Python.
macOS support is useful for the project's development environment and for
running the real-install integration tests, but it is not a promised deployment
target. A platform check in both the bootstrap and the deploy CLI prevents a
mismatched bundle from being installed.

**Alternatives considered**:

- Separate glibc and musl artifacts: doubles the release matrix without a
  current need.
- Promise macOS and Windows: extra release artifacts and service semantics
  outside the spec.
- Linux only in tests: would make local integration testing impossible.
- Ignore platform mismatches: risks executing an incompatible binary.

### D14. Test with a fake uv boundary and one real uv installation

**Decision**: Unit and contract tests replace the uv subprocess boundary with a
typed fake, covering command construction, failure modes, staging, rollback,
locking, and report shapes. One integration test builds a local bundle and runs
the real `uv tool install`, `uv run`, and `uv tool uninstall` in isolated
temporary XDG directories using the host Python. Offline behavior is exercised
with `--no-index --find-links` and no network-dependent resolution. Bootstrap
tests use shellcheck plus a fake download/uv environment. Every test sets
`HOME`, `TROVIUM_CONFIG_FILE`, and the XDG state/data/cache/bin overrides to
temporary paths so a developer's real config and installation cannot affect
results. A platform/preflight matrix covers supported and unsupported hosts,
writable and unwritable paths, and missing optional paths; fault injection at
five points — bundle verification to toolchain copy, toolchain copy to staging
install, staging install to staged self-check, staged self-check to promotion,
and promotion to record write — covers interrupted-run recovery.

**Rationale**: Mock-only tests would miss uv layout and console-script issues;
real-uv tests for every edge case would be slow and network-sensitive. This mix
proves the actual install path once and keeps failure-path tests deterministic.
The local spike already demonstrated the wheelhouse, private tool directory, and
`uv run` paths.

**Alternatives considered**:

- Only mocks: would not prove the tool environment works.
- Only live Linux VMs: too slow and unavailable in the normal check.
- A new test dependency for process mocking: not needed; a small typed fake is
  enough.

### D15. Prompts read from `/dev/tty`; non-interactive mode never prompts

**Decision**: When a required install input is missing, the deploy CLI prompts
only if an interactive terminal is available. It opens `/dev/tty` for prompts
when stdin is not a terminal (the `curl | bash` case). With
`--non-interactive`, or with no terminal and no `/dev/tty`, it fails before any
change with a list of missing inputs.

**Rationale**: `curl ... | bash` consumes stdin for the script, so a naive
prompt would read EOF. Opening `/dev/tty` keeps the one-command interactive
experience working while preserving deterministic unattended behavior.

**Alternatives considered**:

- Require a downloaded script for interactive installs: more steps than the
  spec's one-command goal.
- Prompt on stdin only: breaks the documented one-liner.
- Default silently: hides missing configuration and violates FR-006.

### D16. Config migration is versioned, backed up, and conservative

**Decision**: The config file has a `[meta] schema_version`. Missing or older
versions are migrated only for known keys, with a timestamped backup created
first. Unknown keys are preserved. A config newer than the installer supports is
not rewritten; the report warns and the install may proceed. An invalid config
syntax is a hard preflight failure.

**Rationale**: This satisfies the spec's preservation and backup requirements
without inventing an unbounded migration framework. Refusing to rewrite a newer
schema avoids dropping settings that a later version owns.

**Alternatives considered**:

- Overwrite with defaults: destroys user settings.
- No migration support: every schema change would require manual editing.
- Reject unknown keys: breaks forward compatibility.

## Validated locally

The following path was exercised on 2026-10-19 before writing this plan:

1. `uv build --wheel` produced `trovium-0.1.0-py3-none-any.whl`.
2. `uv export --frozen --no-dev --no-emit-project` produced a hashed
   requirements file, and `pip download --require-hashes` populated a
   wheelhouse with `httpx`, `httpcore`, `h11`, `anyio`, `certifi`, `idna`, and
   `typing_extensions`.
3. `UV_TOOL_DIR=<temp>/tools UV_TOOL_BIN_DIR=<temp>/bin uv tool install
--no-index --find-links <temp>/wheelhouse --force trovium==0.1.0` installed
   successfully, and the installed `trovium-ingest --help` ran.
4. `uv run --no-project --no-index --find-links <temp>/wheelhouse --with
<temp>/wheelhouse/trovium-0.1.0-py3-none-any.whl trovium-ingest --help`
   succeeded, proving the bootstrap's ephemeral-run path.
5. `uv tool uninstall trovium` with the same private directories removed the
   executable symlink and the tool environment.

This validates the plan's offline wheelhouse, private tool directory, and
ephemeral `uv run` assumptions. The remaining bundle-specific work is packaging
the pinned uv and CPython binaries and verifying their checksums.
