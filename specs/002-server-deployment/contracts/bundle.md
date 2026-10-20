# Release Bundle Contract: Server Deployment

**Feature**: `002-server-deployment` | **Date**: 2026-10-19

A release bundle is the only installation source. Online and offline installs
use the same layout, verification, and self-check path.

## Artifact naming

| Artifact                                     | Purpose                              |
| -------------------------------------------- | ------------------------------------ |
| `VERSION`                                    | Plain-text latest version            |
| `install.sh`                                 | Bootstrap script                     |
| `install.sh.sha256`                          | Integrity sidecar for the bootstrap  |
| `trovium-<version>-<platform>.tar.gz`        | Versioned bundle                     |
| `trovium-<version>-<platform>.tar.gz.sha256` | Versioned bundle checksum            |
| `trovium-latest-<platform>.tar.gz`           | Alias uploaded to the latest release |
| `trovium-latest-<platform>.tar.gz.sha256`    | Alias checksum                       |

Platforms: `linux-x86_64`, `linux-aarch64` (release targets);
`darwin-x86_64`, `darwin-aarch64` (development/local bundles). Linux bundles use
static musl `uv` and CPython builds so one artifact works on both glibc and musl
hosts; the wheelhouse is pure Python.

## Tarball layout

The tarball contains one top-level directory:

```text
trovium-<version>-<platform>/
├── manifest.json
├── install.sh
├── wheelhouse/
│   ├── trovium-<version>-py3-none-any.whl
│   ├── anyio-<version>-py3-none-any.whl
│   ├── certifi-<version>-py3-none-any.whl
│   ├── h11-<version>-py3-none-any.whl
│   ├── httpcore-<version>-py3-none-any.whl
│   ├── httpx-<version>-py3-none-any.whl
│   ├── idna-<version>-py3-none-any.whl
│   └── typing_extensions-<version>-py3-none-any.whl
├── toolchain/
│   ├── uv-<uv-version>
│   └── python-<python-version>.tar.gz
└── LICENSES/
    ├── LICENSE
    ├── uv-LICENSE
    └── python-LICENSE
```

The exact dependency set is the resolved `uv.lock` runtime set; the example
above reflects the current project. The wheelhouse must contain every runtime
dependency so `uv tool install --no-index --find-links` resolves without
network access.

## Manifest

`manifest.json`:

```json
{
  "schema_version": 1,
  "version": "0.1.0",
  "platform": "linux-x86_64",
  "python_version": "3.13.5",
  "uv_version": "0.12.19",
  "files": {
    "install.sh": "sha256:...",
    "wheelhouse/anyio-4.15.1-py3-none-any.whl": "sha256:...",
    "wheelhouse/trovium-0.1.0-py3-none-any.whl": "sha256:...",
    "toolchain/uv-0.12.19": "sha256:...",
    "toolchain/python-3.13.5.tar.gz": "sha256:...",
    "LICENSES/LICENSE": "sha256:..."
  }
}
```

Rules:

- `files` lists every regular file except `manifest.json` itself.
- Paths are relative, use `/`, do not contain `..`, and do not escape the bundle.
- `version` must equal the version in the trovium wheel's `METADATA`.
- `platform` must equal the normalized host platform.
- `python_version` must satisfy `>=3.13`.
- `uv_version` must match the bundled binary name.
- Digests are lowercase `sha256:` hex strings.

## Integrity layers

1. **Outer tarball**: the bootstrap downloads or reads the `.sha256` sidecar and
   verifies the tarball before extracting it. A local tarball without a sidecar
   requires `--sha256`. Extracted directories are accepted only by the deploy
   CLI and rely on manifest verification. Sidecars may contain a bare hex digest
   or standard `sha256sum` output; the bootstrap reads the first token.
2. **Manifest entries**: `trovium-deploy` verifies every listed file before
   extracting the Python tarball or running any executable.
3. **Wheel metadata**: the deployed wheel's version and console-script list are
   checked against the manifest and self-check.
4. **Self-check**: every console script is executed with `--help` before
   promotion and again after promotion.

A failure at any layer changes nothing and produces a `bundle_integrity` or
`bundle_invalid` error report.

## Bootstrap behavior

`install.sh` verifies that `tar`, a SHA-256 tool, and either `curl` or `wget`
are available. It fails with a named `missing_prerequisite` error and a remedy
when one is absent. It never uses `sudo`.

Resolution:

- `--version VERSION`: use that version. If no config-changing mode options were
  supplied and an installed `trovium-deploy` is available, try
  `trovium-deploy check --version VERSION`; a current installation emits the
  no-op report and exits 0.
- default: fetch `releases/latest/download/VERSION`, then apply the same
  installed-check fast path before downloading a bundle. If `VERSION` is
  unavailable, fall back to `trovium-latest-<platform>.tar.gz` and read the
  version from its manifest.
- `install.sh --bundle FILE.tar.gz`: verify the sidecar or `--sha256`, then
  extract. The outer checksum is the trust anchor for executing the bundled
  `uv` and deploy CLI.
- `trovium-deploy install --bundle DIR`: use an extracted bundle; the deploy CLI
  verifies every manifest entry before using the bundled uv, Python, or wheel.

Downloaded bundles are cached at
`${XDG_CACHE_HOME:-~/.cache}/trovium/bundles/<version>/<platform>.tar.gz` with
their sidecars. A cached bundle is reused only after checksum verification; a
corrupt or missing sidecar causes a fresh download. The cache is separate from
the rollback wheel cache and is left in place by uninstall so an offline
reinstall remains possible.

The bootstrap does not accept an unverified extracted directory: it would have
to execute the bundle's `uv` before the manifest could be checked. Local
directories are an internal/testing input for the already-running deploy CLI,
which verifies the manifest first.

The extracted bundle is temporary. The deploy CLI copies the pinned uv and
extracts the pinned Python into a private, persistent toolchain directory before
creating the tool environment, so the installed environment never references
the temporary path.

## Local bundle builder

`tools/release/build_bundle.py` builds a bundle for local tests and offline
preparation:

```sh
uv run python tools/release/build_bundle.py \
  --version 0.1.0 \
  --local \
  --out dist/
```

`--local` uses the host's uv and a relocatable managed Python, builds the wheel
and wheelhouse, and emits the tarball and checksum. The builder stages a
temporary source tree with the requested version substituted, so a local upgrade
bundle can be built without editing the repository. CI mode downloads the pinned
artifacts from `tools/release/toolchain.lock.json` and verifies their published
checksums before assembly.

The builder is not imported by the installed package and adds no runtime
dependency.

## Release workflow

`.github/workflows/release.yml` is triggered by `v*` tags and:

1. Runs `scripts/check.sh` before publishing.
2. Builds the wheel and hashed wheelhouse.
3. Downloads the pinned uv and CPython artifacts for each target platform and
   verifies their checksums.
4. Builds versioned bundles, `latest` aliases, checksum sidecars, and the
   `VERSION` asset.
5. Creates the GitHub release and uploads every asset, including `install.sh`.

The workflow has `contents: write` permission only for the release job; the
verification job keeps read-only permissions.

## Offline guarantees

A bundle installed with `--bundle` must succeed with outbound network access
disabled. The deploy CLI uses:

```text
uv tool install --no-index --find-links <bundle>/wheelhouse --python <private python> ...
```

The bootstrap's ephemeral deploy run uses the same `--no-index --find-links`
flags. No step contacts PyPI or GitHub when a local bundle is used.

## Version and compatibility rules

- Downgrades are supported by installing an older bundle with
  `install.sh --version` or `--bundle`.
- All console scripts in one installation come from one wheel and one version.
- A bundle whose manifest platform, wheel version, or Python version does not
  match the host is refused before any change.
- A config schema newer than the installer supports is preserved; the report
  warns rather than rewriting it.
