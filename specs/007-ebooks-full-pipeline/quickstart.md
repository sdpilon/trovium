# Quickstart: Ebooks Through the Full Pipeline

**Feature**: `007-ebooks-full-pipeline` | **Date**: 2026-10-29

Runnable validation scenarios. References: [spec.md](spec.md),
[plan.md](plan.md), [data-model.md](data-model.md),
[contracts/config-cli.md](contracts/config-cli.md),
[contracts/record-schema.md](contracts/record-schema.md).

Run in order; each scenario states its starting state. Re-run the shared setup
before entering part-way through.

## Prerequisites

- `uv`, Python 3.13+, `jq`.
- Linux for the live client scenario (`tools/qbt-live-rig/`); macOS is fine for
  the disk scenarios and the automated suite.

## Shared setup

```sh
tmp=$(mktemp -d)
mkdir -p "$tmp/home" "$tmp/library" "$tmp/source" "$tmp/config" "$tmp/bin"

export HOME="$tmp/home"
export TROVIUM_BIN_DIR="$tmp/bin"
export TROVIUM_CONFIG_FILE="$tmp/config/config.ini"
export TROVIUM_STATE_HOME="$tmp/state"
export TROVIUM_DATA_HOME="$tmp/data"
export TROVIUM_CACHE_HOME="$tmp/cache"
export PATH="$TROVIUM_BIN_DIR:$PATH"

uv run python tools/release/build_bundle.py --local --version 0.2.0 --out "$tmp/dist"
bundle=$(ls "$tmp/dist"/trovium-0.2.0-*.tar.gz | head -1)
```

## Scenario 1: install for ebooks (SC-001)

**Setup**: shared setup; no config exists.

```sh
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$tmp/library" --source "$tmp/source" \
  --profile books --json pretty > "$tmp/install.json"
```

**Expected**:

- Exit 0; `jq -r .status "$tmp/install.json"` is `ok`.
- Config contains `[ingest] profile = books` and `mode = auto`.
- Reinstalling without `--profile` retains the existing books profile.
- Reinstalling with `--profile video` retains books and warns that the supplied
  profile was not applied (existing config wins).

Also verify the refusal:

```sh
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$tmp/other" --source "$tmp/source" --profile nope
```

**Expected**: exit 7, reason names the registered profiles, and no config is
written.

## Scenario 2: disk books move and rename (SC-002, SC-003)

**Setup**: a disk-source config with the books profile.

```sh
mkdir -p "$tmp/source/Jane Doe - Some Book (2020)"
printf 'epub' > "$tmp/source/Jane Doe - Some Book (2020)/Some.Book.epub"
```

```sh
uv run trovium-run --config "$TROVIUM_CONFIG_FILE" --json compact > "$tmp/run1.json"
jq -r '.ingest.items[0].actions[0].op' "$tmp/run1.json"      # move
jq -r '.rename.items[0].disposition' "$tmp/run1.json"       # renamed
ls "$tmp/library/Books/Jane Doe/Some Book (2020)/"          # canonical name
```

**Expected**: the file lands under `Books/Jane Doe/Some Book (2020)/` with the
canonical filename, and the action is `move` because the source is on disk.

Rerun:

```sh
uv run trovium-run --config "$TROVIUM_CONFIG_FILE" --json compact > "$tmp/run2.json"
jq -r '.ingest.items[0].disposition' "$tmp/run2.json"       # already_handled
find "$tmp/library" -type f | wc -l                         # unchanged
```

**Expected**: a second run adds nothing and reports `already_handled`.

## Scenario 3: client folder torrent, hardlink, sidecars, rename (SC-002)

**Setup**: Linux host, `tools/qbt-live-rig/` set up, a torrent containing
`Some.Book.epub`, `metadata.opf`, and `cover.jpg`, and a client-source config
with `profile = books` and `mode = auto`.

```sh
jq -r '.ingest.items[0].actions[].op' "$tmp/client-run.json"   # hardlink, hardlink, hardlink
stat -c '%i' "$torrent_file" "$library_file"                   # same inode
jq -r '.rename.items[0].disposition' "$tmp/client-run.json"    # renamed
ls "$tmp/library/Books/<Author>/<Title> (Year)/"               # epub + sidecars
```

**Expected**:

- The EPUB and both sidecars are placed.
- The placed files are hardlinks (same inode as the torrent files) because the
  library and download directory share a filesystem.
- The EPUB is renamed canonically; sidecars keep their names.
- The client still seeds; the record has no `setLocation`, `pause`, or `delete`
  action for the item.
- A second run reports `already_handled` and adds nothing.

Cross-filesystem variant (Linux): point `library.root` at a directory on a
different filesystem, for example `/dev/shm/trovium-library`.

**Expected**: actions are `copy`, the reason says `hardlink unavailable…;
copied instead`, and the torrent keeps seeding.

## Scenario 4: refusals (SC-004)

- A folder torrent in explicit `--mode move` still fails with
  `multi-file torrent cannot be ingested with --mode move…` and nothing is
  placed.
- A torrent holding two distinct EPUBs is `unresolvable`; the reason names both
  files; nothing is placed and the client is untouched.

The automated proofs:

```sh
uv run pytest tests/integration/test_client_ingest.py -k ebook
uv run pytest tests/unit/test_placement.py tests/unit/test_library.py -k auto
```

## Scenario 5: the gate

```sh
scripts/check.sh
```

**Expected**: green, including the new mode, content-identity, rename, and
install tests.
