# Release tooling

`build_bundle.py` produces the self-contained release bundle used by
`install.sh`. A bundle contains the trovium wheel, its runtime wheelhouse, a
manifest with SHA-256 digests, the pinned uv and CPython toolchain, and license
texts.

Local test bundle (host toolchain fallback):

```sh
uv run python tools/release/build_bundle.py --fast --version 0.1.0 --out dist
```

A local bundle has no `toolchain/` directory; `install.sh` falls back to the
host `uv` and Python 3.13 for development tests. Release bundles never rely on
the host.

Production bundle for a specific platform:

```sh
uv run python tools/release/build_bundle.py \
  --version 0.1.0 \
  --platform linux-x86_64 \
  --locked \
  --out dist
```

`--locked` reads `toolchain.lock.json`, downloads the pinned uv and CPython
artifacts for the requested platform, verifies each published SHA-256 before
extracting it, and writes their license texts into `LICENSES/`. The lock covers
the Linux targets only; local macOS bundles use the host toolchain.

The builder writes:

- `trovium-<version>-<platform>.tar.gz` and its `.sha256`
- `trovium-latest-<platform>.tar.gz` and its `.sha256`
- `VERSION`

The release workflow runs the builder with `--locked` on Linux x86_64 and
aarch64 runners and uploads the assets to the tag's GitHub release.

## Toolchain lock format

`toolchain.lock.json` has `schema_version: 1` and one section per tool
(`uv`, `python`) with:

- `version` and, for CPython, the `build` (python-build-standalone release tag)
- `release_base`, the prefix every asset name is appended to
- `assets`, keyed by bundle platform (`linux-x86_64`, `linux-aarch64`), each
  with the published artifact `name` and lowercase `sha256`

`licenses` records where the builder fetches the uv and CPython license texts.

## Refreshing the lock

1. Pick the uv release and the python-build-standalone release. Both must offer
   static musl builds for `x86_64` and `aarch64`.
2. Read the published digests from the release API:
   `gh api repos/astral-sh/uv/releases/tags/<uv-version>` and
   `gh api repos/astral-sh/python-build-standalone/releases/tags/<build>`.
3. Update `version`, `build`, `release_base`, each asset `name`, and each
   `sha256` in `toolchain.lock.json`.
4. Update the license URLs to the same tags.
5. Build one bundle per platform with `--locked` and install it on the matching
   host before publishing. Never edit a digest to make a mismatch pass.
