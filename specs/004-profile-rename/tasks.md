# Tasks: Profile-Driven Rename

**Feature**: `004-profile-rename` | **Plan**: [plan.md](plan.md) |
**Spec**: [spec.md](spec.md)

## Phase 1: Profile naming

- [x] T001 Add `NamePlan` and change `Profile.plan_names` to return it.
- [x] T002 Implement books `plan_names` (author, series, year, sidecars).
- [x] T003 Implement video `plan_names` (movie single-file, TV episodes,
      multi-file skips).
- [x] T004 Add unit tests for every naming rule.

## Phase 2: Rename engine and CLI

- [x] T005 Add the rename record model and input validation.
- [x] T006 Implement destination scanning, duplicate/collision detection, and
      per-item planning.
- [x] T007 Implement apply with rollback and no-overwrite checks.
- [x] T008 Implement the CLI, stdin/`--record`, `--dry-run`,
      `--allow-unsafe`, `--on-fail`, `--json`.
- [x] T009 Add the `trovium-rename` console script and dependency-budget test.

## Phase 3: Safety and integration

- [x] T010 Enforce move-only by default and skip `setLocation` items.
- [x] T011 Add unit tests for dry-run, rerun, collision, unsafe refusal,
      malformed record, and unknown profile.
- [x] T012 Add the ingest-to-rename integration tests for books, movie, and TV.
- [x] T013 Update the profile guide, README, and contracts.

## Phase 4: Verification

- [x] T014 Run `scripts/check.sh` green.
- [x] T015 Mark the spec Complete and run the acceptance blocks.

```accept
# verifies: SC-001 — books rename to the documented pattern and keep sidecars
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
uv run --quiet python tests/fixtures/books/make_source.py "$tmp"
mkdir -p "$tmp/library"
uv run --quiet trovium-ingest --profile books --source "$tmp/source" \
  --library-root "$tmp/library" --json compact > "$tmp/ingest.json"
uv run --quiet trovium-rename --record "$tmp/ingest.json" --json compact > "$tmp/rename.json"
jq -e '.counts.renamed > 0 and .counts.error == 0' "$tmp/rename.json" >/dev/null
test -f "$tmp/library/Books/Jane Doe/Embedded Title (2020)/Jane Doe - Embedded Title (2020).epub"
test -f "$tmp/library/Books/Alice Author/The PDF Book (2021)/Alice Author - The PDF Book (2021).pdf"
test -f "$tmp/library/Books/Folder Author/Solo Book (2018)/Folder Author - Solo Book (2018).epub"
test -f "$tmp/library/Books/Folder Author/Solo Book (2018)/cover.jpg"
```

```accept
# verifies: SC-002 — movie and TV files rename; multi-file movies are skipped
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source/Movie.Production.2024.1080p" "$tmp/source/Show.Name.S01" "$tmp/library"
printf x > "$tmp/source/Movie.Production.2024.1080p/Movie.Production.2024.1080p.mkv"
printf a > "$tmp/source/Show.Name.S01/Show.Name.S01E01.mkv"
printf b > "$tmp/source/Show.Name.S01/Show.Name.S01E02.mkv"
uv run --quiet trovium-ingest --source "$tmp/source" --library-root "$tmp/library" \
  --json compact > "$tmp/ingest.json"
uv run --quiet trovium-rename --record "$tmp/ingest.json" --json compact > "$tmp/rename.json"
jq -e '.counts.error == 0' "$tmp/rename.json" >/dev/null
test -f "$tmp/library/Movies/Movie Production (2024)/Movie Production (2024).mkv"
test -f "$tmp/library/TV/Show Name/Season 01/Show Name - S01E01.mkv"
test -f "$tmp/library/TV/Show Name/Season 01/Show Name - S01E02.mkv"
```

```accept
# verifies: SC-003 — a dry-run plan matches the real run
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source/Movie.Production.2024.1080p" "$tmp/library"
printf x > "$tmp/source/Movie.Production.2024.1080p/Movie.Production.2024.1080p.mkv"
uv run --quiet trovium-ingest --source "$tmp/source" --library-root "$tmp/library" \
  --json compact > "$tmp/ingest.json"
uv run --quiet trovium-rename --record "$tmp/ingest.json" --dry-run --json compact > "$tmp/plan.json"
test -f "$tmp/library/Movies/Movie Production (2024)/Movie.Production.2024.1080p.mkv"
uv run --quiet trovium-rename --record "$tmp/ingest.json" --json compact > "$tmp/real.json"
jq -e --slurpfile real "$tmp/real.json" '.items[0].actions == $real[0].items[0].actions' "$tmp/plan.json" >/dev/null
```

```accept
# verifies: SC-004 — a second rename of the same record is a no-op
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source/Movie.Production.2024.1080p" "$tmp/library"
printf x > "$tmp/source/Movie.Production.2024.1080p/Movie.Production.2024.1080p.mkv"
uv run --quiet trovium-ingest --source "$tmp/source" --library-root "$tmp/library" \
  --json compact > "$tmp/ingest.json"
uv run --quiet trovium-rename --record "$tmp/ingest.json" --json compact > /dev/null
before=$(find "$tmp/library" -type f -exec cksum {} + | sort)
uv run --quiet trovium-rename --record "$tmp/ingest.json" --json compact > "$tmp/second.json"
after=$(find "$tmp/library" -type f -exec cksum {} + | sort)
test "$before" = "$after"
jq -e '.counts.renamed == 0 and .counts.already_handled > 0' "$tmp/second.json" >/dev/null
```

```accept
# verifies: SC-005 — copy/hardlink records are renamed without an override
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source/Movie.Production.2024.1080p" "$tmp/library"
printf x > "$tmp/source/Movie.Production.2024.1080p/Movie.Production.2024.1080p.mkv"
uv run --quiet trovium-ingest --source "$tmp/source" --library-root "$tmp/library" \
  --mode copy --json compact > "$tmp/ingest.json"
uv run --quiet trovium-rename --record "$tmp/ingest.json" --json compact > "$tmp/out.json"
jq -e '.counts.renamed == 1 and .counts.error == 0' "$tmp/out.json" >/dev/null
test -f "$tmp/library/Movies/Movie Production (2024)/Movie Production (2024).mkv"
```

```accept
# verifies: SC-006 — a target collision leaves the item untouched
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source/Show.Name.S01" "$tmp/library/TV/Show Name/Season 01"
printf x > "$tmp/source/Show.Name.S01/Show.Name.S01E01.mkv"
printf z > "$tmp/source/Show.Name.S01/Show.Name.S01E02.mkv"
printf y > "$tmp/library/TV/Show Name/Season 01/Show Name - S01E01.mkv"
uv run --quiet trovium-ingest --source "$tmp/source" --library-root "$tmp/library" \
  --mode copy --json compact > "$tmp/ingest.json"
uv run --quiet trovium-rename --record "$tmp/ingest.json" --allow-unsafe --json compact > "$tmp/rename.json"
jq -e '.counts.error == 1 and .counts.renamed == 0' "$tmp/rename.json" >/dev/null
test -f "$tmp/library/TV/Show Name/Season 01/Show.Name.S01E01.mkv"
test -f "$tmp/library/TV/Show Name/Season 01/Show.Name.S01E02.mkv"
test "$(cat "$tmp/library/TV/Show Name/Season 01/Show Name - S01E01.mkv")" = "y"
```

## Dependencies and order

- T001 before T002-T003.
- T005-T008 before T010-T012.
- T012 before T014.
- T015 last.
