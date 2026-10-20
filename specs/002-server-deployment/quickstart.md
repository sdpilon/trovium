# Quickstart: Server Deployment

**Feature**: `002-server-deployment` | **Date**: 2026-10-19

Runnable validation scenarios proving the deployment path end-to-end. References:
[spec.md](spec.md), [contracts/cli.md](contracts/cli.md),
[contracts/config-schema.md](contracts/config-schema.md),
[contracts/report-schema.md](contracts/report-schema.md),
[contracts/bundle.md](contracts/bundle.md), [data-model.md](data-model.md).

The scenarios run in order and share `$tmp`. Each scenario states its starting
state; re-run the shared setup before entering part-way through.

## Prerequisites

- `uv` and a Python 3.13+ interpreter for development.
- `jq` for inspecting JSON reports.
- Linux is the release target. The same commands run on macOS with a local
  bundle for development; `stat -c` examples use GNU stat.

## Shared setup

```sh
tmp=$(mktemp -d)
mkdir -p "$tmp/home" "$tmp/library" "$tmp/source/Show.S01" "$tmp/config" "$tmp/bin"
printf 'episode' > "$tmp/source/Show.S01/Show.S01E01.mkv"

export HOME="$tmp/home"
export TROVIUM_BIN_DIR="$tmp/bin"
export TROVIUM_CONFIG_FILE="$tmp/config/config.ini"
export TROVIUM_STATE_HOME="$tmp/state"
export TROVIUM_DATA_HOME="$tmp/data"
export TROVIUM_CACHE_HOME="$tmp/cache"
export PATH="$TROVIUM_BIN_DIR:$PATH"

uv run python tools/release/build_bundle.py \
  --local --version 0.1.0 --out "$tmp/dist"
bundle=$(ls "$tmp/dist"/trovium-0.1.0-*.tar.gz | head -1)
```

## Scenario 1: install from a local bundle without root (Story P1)

**Setup**: shared setup; no config or installation exists.

```sh
bash install.sh --bundle "$bundle" \
  --non-interactive --library-root "$tmp/library" --source "$tmp/source" \
  --json pretty > "$tmp/install.json"
```

**Expected**:

- Exit 0.
- `jq -r .status "$tmp/install.json"` is `ok`.
- `jq -r .version "$tmp/install.json"` is `0.1.0`.
- `jq -r .config_path "$tmp/install.json"` is `$tmp/config/config.ini`.
- `TROVIUM_BIN_DIR/trovium-ingest --help` exits 0.
- `TROVIUM_BIN_DIR/trovium-deploy --help` exits 0.
- Config exists, contains `[library] root = $tmp/library` and
  `[source] mode = disk` with `path = $tmp/source`, and has mode 600.
- `stat -c '%a' "$tmp/config/config.ini"` prints `600`.
- The JSON report has no credential-like value.

## Scenario 1b: online install from a local release fixture (Story P1, SC-001)

**Setup**: shared setup; a fresh tree and a local release directory that mirrors
the versioned asset path.

```sh
mkdir -p "$tmp/case1b/home" "$tmp/case1b/library" "$tmp/case1b/bin" \
  "$tmp/case1b/config" "$tmp/release/download/v0.1.0" \
  "$tmp/release/releases/latest/download"
cp "$bundle" "$tmp/release/download/v0.1.0/$(basename "$bundle")"
cp "$bundle.sha256" "$tmp/release/download/v0.1.0/$(basename "$bundle").sha256"
printf '0.1.0\n' > "$tmp/release/releases/latest/download/VERSION"
python3 -m http.server 8765 --directory "$tmp/release" >/dev/null 2>&1 &
http_pid=$!
trap 'kill "$http_pid" 2>/dev/null || true' EXIT
sleep 1

HOME="$tmp/case1b/home" \
TROVIUM_BIN_DIR="$tmp/case1b/bin" \
TROVIUM_CONFIG_FILE="$tmp/case1b/config/config.ini" \
TROVIUM_STATE_HOME="$tmp/case1b/state" \
TROVIUM_DATA_HOME="$tmp/case1b/data" \
TROVIUM_CACHE_HOME="$tmp/case1b/cache" \
bash install.sh --release-base-url http://127.0.0.1:8765 --version 0.1.0 \
  --non-interactive --library-root "$tmp/case1b/library" --source "$tmp/source" \
  --json compact > "$tmp/case1b/install.json"

mkdir -p "$tmp/case1c/home" "$tmp/case1c/library" "$tmp/case1c/bin" \
  "$tmp/case1c/config"
HOME="$tmp/case1c/home" \
TROVIUM_BIN_DIR="$tmp/case1c/bin" \
TROVIUM_CONFIG_FILE="$tmp/case1c/config/config.ini" \
TROVIUM_STATE_HOME="$tmp/case1c/state" \
TROVIUM_DATA_HOME="$tmp/case1c/data" \
TROVIUM_CACHE_HOME="$tmp/case1c/cache" \
bash install.sh --release-base-url http://127.0.0.1:8765 \
  --non-interactive --library-root "$tmp/case1c/library" \
  --source "$tmp/source" --json compact > "$tmp/case1c/install.json"
jq -e '.version == "0.1.0"' "$tmp/case1c/install.json" >/dev/null
kill "$http_pid"
```

**Expected**: both installs exit 0; `.status` is `ok` or `degraded`;
`.version` is `0.1.0`; the installed command runs. The pinned run uses
`--version 0.1.0`; the second run omits `--version` and exercises
`releases/latest/download/VERSION`. The production equivalent is the
`releases/latest/download` URL; this fixture exercises the same bootstrap
download, checksum, extraction, and install path. Record the clean-runner
timing separately against the 5-minute SC-001 target.

## SC-002 validation matrix

Run each case with a fresh temp HOME/XDG tree and record the result.

| #   | Case                                                    | Expected                                         |
| --- | ------------------------------------------------------- | ------------------------------------------------ |
| 1   | glibc x86_64, disk source                               | install and self-check pass                      |
| 2   | glibc x86_64, client config                             | install and self-check pass                      |
| 3   | glibc x86_64, config-file non-interactive               | install and self-check pass                      |
| 4   | glibc x86_64, offline local bundle                      | install and self-check pass                      |
| 5   | glibc aarch64, disk source (or a second clean HOME/XDG) | install and self-check pass                      |
| 6   | unsupported platform                                    | refused with `unsupported_platform` and a remedy |
| 7   | missing prerequisite                                    | refused with `missing_prerequisite` and a remedy |

Five of five positive cases passing is 100%, above the 95% target.

## Scenario 2: identical re-run is a no-op (Story P2, SC-003)

```sh
bash install.sh --bundle "$bundle" \
  --non-interactive --library-root "$tmp/library" \
  --json compact > "$tmp/install-again.json"
```

**Expected**: exit 0; `.status` is `noop`; `.previous_version` equals
`.version`; `.actions` is empty; the config is unchanged (compare a checksum
before and after).

## Scenario 3: status is read-only and fast (Story P1, SC-012)

```sh
trovium-deploy status --json pretty > "$tmp/status.json"
```

**Expected**: exit 0; `.operation` is `status`; `.version` is `0.1.0`;
`.checks` includes `installed_commands` and `self_check` with `pass`;
`.actions` is empty. A second status call produces the same installation state
and no file changes under `$tmp/config`, `$tmp/state`, or `$tmp/data`.

## Scenario 4: non-interactive install from a config file (Story P2)

**Setup**: a fresh tree with no canonical config.

```sh
mkdir -p "$tmp/case4/home" "$tmp/case4/library" "$tmp/case4/bin" "$tmp/case4/config"
cat > "$tmp/case4/supplied.ini" <<EOF
[meta]
schema_version = 1

[library]
root = $tmp/case4/library

[source]
mode = disk
path = $tmp/source

[ingest]
mode = copy
category = tv
EOF
chmod 600 "$tmp/case4/supplied.ini"

HOME="$tmp/case4/home" \
TROVIUM_BIN_DIR="$tmp/case4/bin" \
PATH="$tmp/case4/bin:$PATH" \
TROVIUM_CONFIG_FILE="$tmp/case4/config/config.ini" \
TROVIUM_STATE_HOME="$tmp/case4/state" \
TROVIUM_DATA_HOME="$tmp/case4/data" \
TROVIUM_CACHE_HOME="$tmp/case4/cache" \
bash install.sh --bundle "$bundle" --config "$tmp/case4/supplied.ini" \
  --non-interactive --json pretty > "$tmp/case4/install.json"
```

**Expected**: exit 0; `.status` is `ok`; the canonical config exists with the
supplied library root, source, and `mode = copy`; the supplied file is
unchanged; the report records a `write_config` action.

## Scenario 5: offline install with network disabled (Story P2, SC-010)

**Setup**: a fresh tree and the local bundle.

```sh
mkdir -p "$tmp/case5/home" "$tmp/case5/library" "$tmp/case5/bin" "$tmp/case5/config"
HOME="$tmp/case5/home" \
TROVIUM_BIN_DIR="$tmp/case5/bin" \
PATH="$tmp/case5/bin:$PATH" \
TROVIUM_CONFIG_FILE="$tmp/case5/config/config.ini" \
TROVIUM_STATE_HOME="$tmp/case5/state" \
TROVIUM_DATA_HOME="$tmp/case5/data" \
TROVIUM_CACHE_HOME="$tmp/case5/cache" \
UV_OFFLINE=1 HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 \
bash install.sh --bundle "$bundle" \
  --non-interactive --library-root "$tmp/case5/library" --source "$tmp/source" \
  --json compact > "$tmp/case5/install.json"
```

**Expected**: exit 0; `.status` is `ok`; the installed command runs. No network
request is required because the bundle contains the wheelhouse, uv, and Python.

## Scenario 6: upgrade preserves configuration (Story P3, SC-008)

**Setup**: the Scenario 1 installation has a customized config.

```sh
printf '\n# operator note\n' >> "$tmp/config/config.ini"
cp "$tmp/config/config.ini" "$tmp/config.before"

uv run python tools/release/build_bundle.py \
  --local --version 0.2.0 --out "$tmp/dist2"
bundle2=$(ls "$tmp/dist2"/trovium-0.2.0-*.tar.gz | head -1)

bash install.sh --bundle "$bundle2" \
  --non-interactive --library-root "$tmp/library" \
  --json pretty > "$tmp/upgrade.json"
```

**Expected**:

- Exit 0; `.operation` is `upgrade`; `.version` is `0.2.0`;
  `.previous_version` is `0.1.0`.
- `$tmp/config/config.ini` is byte-identical to `$tmp/config.before`.
- `trovium-ingest --help` exits 0 and reports the new version through the
  deployment record.
- The report includes `stage`, `self_check`, and `promote` actions.

## Scenario 7: failed upgrade leaves the previous version active (Story P3, SC-008)

**Setup**: use a deliberately broken local bundle fixture whose staged
`trovium-ingest --help` exits non-zero. The contract tests build this fixture;
the quickstart assumes `tests/fixtures/deploy/broken-bundle.tar.gz` and its
`.sha256` sidecar are available. The checked-in copy is built for
`darwin-aarch64` and uses version `0.2.1`; regenerate it with
`accept_broken_bundle` (see `tests/fixtures/deploy/README.md`) on another
platform, and run this scenario after Scenario 6 so `0.2.0` is active.

This fixture fails at the staged self-check, before promotion. The
post-promotion `_rollback` path is covered by
`tests/integration/deploy/test_rollback.py`, not by this scenario.

```sh
bash install.sh --bundle tests/fixtures/deploy/broken-bundle.tar.gz \
  --non-interactive --library-root "$tmp/library" \
  --json pretty > "$tmp/rollback.json"; code=$?
```

**Expected**: non-zero exit; `.status` is `error`; `.error.code` is
`self_check_failed`; `.version` remains `0.2.0`; the installed command still
works; the report names the failed command and a remedy.

## Scenario 8: secrets never appear in output (SC-007)

**Setup**: a fresh install with a client URL and a secret in the environment.

```sh
export TROVIUM_CLIENT_USERNAME=admin
export TROVIUM_CLIENT_PASSWORD=super-secret-value
mkdir -p "$tmp/case8/home" "$tmp/case8/library" "$tmp/case8/bin" "$tmp/case8/config"
HOME="$tmp/case8/home" \
TROVIUM_BIN_DIR="$tmp/case8/bin" \
TROVIUM_CONFIG_FILE="$tmp/case8/config/config.ini" \
TROVIUM_STATE_HOME="$tmp/case8/state" \
TROVIUM_DATA_HOME="$tmp/case8/data" \
TROVIUM_CACHE_HOME="$tmp/case8/cache" \
bash install.sh --bundle "$bundle" \
  --non-interactive --library-root "$tmp/case8/library" \
  --client-url http://127.0.0.1:8080 --json pretty \
  > "$tmp/case8/install.json" 2> "$tmp/case8/install.err"

if grep -R 'super-secret-value' "$tmp/case8/install.json" "$tmp/case8/install.err" "$tmp/case8/config/config.ini"; then
  echo "SECRET LEAKED"; exit 1
fi
```

**Expected**: exit 0; the secret appears in none of the report, stderr, or
config. The config contains only the credential environment-variable names.

```sh
unset TROVIUM_CLIENT_USERNAME TROVIUM_CLIENT_PASSWORD
```

## Scenario 9: ingest reads the installed config (Story P2, FR-010)

```sh
trovium-ingest --config "$tmp/config/config.ini" --dry-run --json compact \
  > "$tmp/ingest.json"
```

**Expected**: exit 0; the ingest run uses the configured library root and disk
source without repeating those flags; the emitted run record contains no
credential values. CLI overrides still win:

```sh
trovium-ingest --config "$tmp/config/config.ini" \
  --library-root "$tmp/library" --mode copy --dry-run --json compact \
  > "$tmp/ingest-override.json"
```

**Expected**: the override is reflected in the run record's `declared` section.

## Scenario 10: bundle refusal changes nothing (Story P2, FR-009)

**Setup**: copy the bundle and corrupt one wheel.

```sh
mkdir -p "$tmp/case10"
tar -xzf "$bundle" -C "$tmp/case10"
bundle_dir=$(find "$tmp/case10" -mindepth 1 -maxdepth 1 -type d | head -1)
printf 'corrupt' >> "$bundle_dir"/wheelhouse/httpx-*.whl
bad="$tmp/case10/trovium-bad.tar.gz"
tar -czf "$bad" -C "$tmp/case10" "$(basename "$bundle_dir")"
sha256sum "$bad" > "$bad.sha256"
bash install.sh --bundle "$bad" --non-interactive \
  --library-root "$tmp/library" --json compact > "$tmp/case10/report.json"; code=$?
test "$code" -ne 0
```

**Expected**: non-zero exit; `.status` is `error`; `.error.code` is
`bundle_integrity`; the existing installation and config are unchanged.

## Scenario 11: uninstall preserves config and media (Story P3, SC-009)

**Setup**: the 0.2.0 installation and config are intact after the refused
upgrade.

```sh
printf 'media' > "$tmp/library/keep.me"
before=$(find "$tmp/library" "$tmp/source" -type f -exec sha256sum {} + | sort)
trovium-deploy uninstall --json pretty > "$tmp/uninstall.json"

test ! -e "$tmp/bin/trovium-ingest"
test -f "$tmp/config/config.ini"
after=$(find "$tmp/library" "$tmp/source" -type f -exec sha256sum {} + | sort)
test "$before" = "$after"
```

**Expected**: exit 0; `.status` is `ok`; config remains; commands are gone; the
media inventory (library and source) is unchanged. The installer can still run uninstall after the
installed command is gone:

```sh
bash install.sh --bundle "$bundle" --uninstall --json compact > "$tmp/noop.json"
```

**Expected**: exit 0; `.status` is `noop`; nothing is removed.

Reinstall to verify purge in isolation:

```sh
bash install.sh --bundle "$bundle" \
  --non-interactive --library-root "$tmp/library" --json compact \
  > "$tmp/reinstall.json"
trovium-deploy uninstall --purge --json compact > "$tmp/purge.json"
test ! -e "$tmp/config/config.ini"
test -d "$tmp/library"
```

**Expected** after purge: exit 0; config is removed, the library still exists,
and the report records `purge_config`.

## Final state

The installed environment is gone after Scenario 11's purge; `$tmp/library`,
`$tmp/source`, and `$tmp/case8` artifacts remain for inspection. No deployment
scenario wrote to the media library or source directory.
