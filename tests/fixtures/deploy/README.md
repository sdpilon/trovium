# Deployment test fixtures

- `accept_lib.sh` — shared harness for the spec conformance `accept` blocks and
  the quickstart. It creates an isolated home/XDG tree, builds or reuses a local
  bundle, builds the broken bundle, and hashes the media trees.
- `fake_uv.sh` — a deterministic stand-in for the real `uv` binary, used by the
  deploy unit tests.
- `make_broken_bundle.py` — turns a verified bundle into one whose staged
  self-check fails, by adding a `trovium-broken` console script that exits 3 and
  rehashing the wheel `RECORD` and the bundle manifest.
- `broken-bundle.tar.gz` / `.sha256` — a checked-in broken bundle for
  `quickstart.md` Scenario 7, built for `darwin-aarch64`. It upgrades from
  `0.2.0` because its own version is `0.2.1`, so the install cannot short-circuit
  as a no-op.

## Rebuilding the fixtures

```sh
bash -euo pipefail -c '
source tests/fixtures/deploy/accept_lib.sh
accept_init
accept_broken_bundle
'
```

Bundles are cached under `${TROVIUM_ACCEPT_CACHE:-$TMPDIR/trovium-accept-bundles}`.
Clear that directory after changing anything under `src/` or `install.sh`: the
cache is keyed by version and platform only, so a stale bundle hides the change.
On a host other than macOS aarch64, regenerate `broken-bundle.tar.gz` with the
command above; the checked-in copy only matches the platform that built it.
