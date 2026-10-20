# Release tooling

`build_bundle.py` produces the self-contained release bundle used by
`install.sh`. A bundle contains the trovium wheel, its runtime wheelhouse, a
manifest with SHA-256 digests, and optionally pinned uv and CPython toolchains.

Local test bundle (host toolchain fallback):

```sh
uv run python tools/release/build_bundle.py --fast --version 0.1.0 --out dist
```

Production bundle for a specific platform:

```sh
uv python install 3.13
python_dir="$(dirname "$(dirname "$(uv python find --managed-python --resolve-links 3.13)")")"
uv run python tools/release/build_bundle.py \
  --version 0.1.0 \
  --platform linux-x86_64 \
  --uv "$(command -v uv)" \
  --python "$python_dir" \
  --out dist
```

The builder writes:

- `trovium-<version>-<platform>.tar.gz` and its `.sha256`
- `trovium-latest-<platform>.tar.gz` and its `.sha256`
- `VERSION`

The release workflow runs this builder on Linux x86_64 and aarch64 runners and
uploads the assets to the tag's GitHub release.
