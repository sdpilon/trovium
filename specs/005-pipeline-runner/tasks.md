# Tasks: Pipeline Runner

**Feature**: `005-pipeline-runner` | **Plan**: [plan.md](plan.md) |
**Spec**: [spec.md](spec.md)

## Phase 1: Reusable ingest run

- [x] T001 Extract `cli.run_resolved` and use it from `cli.main` without
      changing behavior.
- [x] T002 Add tests that the extracted function returns the same records.

## Phase 2: Runner

- [x] T003 Add `src/trovium/run.py` with the combined record and skip reasons.
- [x] T004 Add the `trovium-run` console script.
- [x] T005 Wire `--skip-rename` and `--allow-unsafe`; map client failures to
      exit 3 and never rename after a failure.
- [x] T006 Add unit tests for the record shape and each skip reason.

## Phase 3: Integration and deployment

- [x] T007 Add integration tests for books, video, dry-run, and copy mode.
- [x] T008 Update the deployment command-list tests for `trovium-run` and
      rebuild the local bundle cache.
- [x] T009 Update the README, deployment notes, and CLI contract.

## Phase 4: Verification

- [x] T010 Run `scripts/check.sh` green.
- [x] T011 Mark the spec Complete and run the acceptance blocks.

```accept
# verifies: SC-001 — books ingest and rename in one command
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export PYTHONDONTWRITEBYTECODE=1
uv run --quiet python tests/fixtures/books/make_source.py "$tmp"
mkdir -p "$tmp/library"
uv run --quiet trovium-run --profile books --source "$tmp/source" \
  --library-root "$tmp/library" --json compact > "$tmp/run.json"
jq -e '.source == "run" and .ingest.counts.ingested == 4 and .rename.counts.error == 0' "$tmp/run.json" >/dev/null
test -f "$tmp/library/Books/Jane Doe/Embedded Title (2020)/Jane Doe - Embedded Title (2020).epub"
test -f "$tmp/library/Books/Folder Author/Solo Book (2018)/Folder Author - Solo Book (2018).epub"
```

```accept
# verifies: SC-002 — movie and TV ingest and rename in one command
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$tmp/source/Movie.Production.2024.1080p" "$tmp/source/Show.Name.S01" "$tmp/library"
printf x > "$tmp/source/Movie.Production.2024.1080p/Movie.Production.2024.1080p.mkv"
printf a > "$tmp/source/Show.Name.S01/Show.Name.S01E01.mkv"
printf b > "$tmp/source/Show.Name.S01/Show.Name.S01E02.mkv"
uv run --quiet trovium-run --source "$tmp/source" --library-root "$tmp/library" \
  --json compact > "$tmp/run.json"
jq -e '.ingest.counts.ingested == 2 and .rename.counts.error == 0' "$tmp/run.json" >/dev/null
test -f "$tmp/library/Movies/Movie Production (2024)/Movie Production (2024).mkv"
test -f "$tmp/library/TV/Show Name/Season 01/Show Name - S01E01.mkv"
```

```accept
# verifies: SC-003 — a dry-run changes nothing and skips rename
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$tmp/source/Movie.Production.2024.1080p" "$tmp/library"
printf x > "$tmp/source/Movie.Production.2024.1080p/Movie.Production.2024.1080p.mkv"
uv run --quiet trovium-run --source "$tmp/source" --library-root "$tmp/library" \
  --dry-run --json compact > "$tmp/run.json"
jq -e '.dry_run == true and .rename == null and (.rename_skipped | length > 0)' "$tmp/run.json" >/dev/null
test -f "$tmp/source/Movie.Production.2024.1080p/Movie.Production.2024.1080p.mkv"
test -z "$(find "$tmp/library" -type f -print -quit)"
```

```accept
# verifies: SC-004 — copy mode places files and renames them by default
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$tmp/source/Movie.Production.2024.1080p" "$tmp/library"
printf x > "$tmp/source/Movie.Production.2024.1080p/Movie.Production.2024.1080p.mkv"
uv run --quiet trovium-run --source "$tmp/source" --library-root "$tmp/library" \
  --mode copy --json compact > "$tmp/run.json"
jq -e '.ingest.counts.ingested == 1 and .rename != null and .rename.counts.renamed == 1' "$tmp/run.json" >/dev/null
test -f "$tmp/library/Movies/Movie Production (2024)/Movie Production (2024).mkv"
```

```accept
# verifies: SC-005 — an unreachable client exits 3 and does not rename
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$tmp/library"
code=0
uv run --quiet trovium-run --client-url http://127.0.0.1:9 \
  --library-root "$tmp/library" --json compact > "$tmp/out.json" 2> "$tmp/err.txt" || code=$?
test "$code" -eq 3
test -z "$(find "$tmp/library" -type f -print -quit)"
```

```accept
# verifies: SC-006 — the deployed command set includes trovium-run
export PYTHONDONTWRITEBYTECODE=1
uv run --quiet pytest -q -p no:cacheprovider \
  tests/integration/deploy/test_install_local.py::test_install_creates_a_private_working_installation
```

## Dependencies and order

- T001 before T003.
- T003-T005 before T006-T007.
- T008 before T010.
- T011 last.
