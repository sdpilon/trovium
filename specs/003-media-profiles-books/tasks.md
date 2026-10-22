# Tasks: Media Profiles and Books

**Feature**: `003-media-profiles-books` | **Plan**: [plan.md](plan.md) |
**Spec**: [spec.md](spec.md)

## Phase 1: Profile contract and video extraction

- [x] T001 Add `profiles/base.py` with `Profile`, `CandidateGroup`,
      `Classification`, `safe_component`, and shared membership helpers.
- [x] T002 Add `profiles/__init__.py` with the built-in registry,
      `get_profile`, `available_profiles`, and `register_profile`.
- [x] T003 Move video extensions, incidental rules, classifier, grouping, and
      destination into `profiles/video.py`.
- [x] T004 Refactor `sources.py` to build candidates from
      `Profile.groups`/`collect_files`; keep one empty candidate for an entry
      with no member files.
- [x] T005 Refactor `cli.py` to resolve a profile, classify through it, and
      scope-filter with the profile's categories.
- [x] T006 Refactor `record.py` and `config.py` for `profile`, string
      categories, and optional item `details`.
- [x] T007 Update video unit, contract, and integration tests to the new
      module layout; add a `declared.profile == "video"` assertion.
- [x] T008 Run the full existing suite; no video regressions before books.

## Phase 2: Books profile

- [x] T009 Add `profiles/books.py` with ebook extensions, one-book-per-file
      grouping, and the single-book sidecar rule.
- [x] T010 Implement the conservative book filename grammar and tests.
- [x] T011 Add `profiles/epub.py`: container/OPF reader with size caps,
      regular-file checks, and fallback on parse errors.
- [x] T012 Merge EPUB metadata and filename fields; record `metadata_source`.
- [x] T013 Implement the books destination layout and unknown-author/year
      rules.
- [x] T014 Add books unit tests: grammar, metadata, destination, grouping,
      malformed EPUB.

## Phase 3: Engine proof and books integration

- [x] T015 Add `tests/integration/test_books_ingest.py`: EPUB metadata,
      filename-only PDF, multi-book folder, ambiguous name, rerun no-op.
- [x] T016 Add a `distros` fixture profile and an engine-level test proving no
      engine changes.
- [x] T017 Add `docs/profiles.md` with the contract, the `distros` example,
      and a new-profile checklist.
- [x] T018 Update the CLI, record, and config contracts and the README usage.

## Phase 4: Verification

- [x] T019 Run `scripts/check.sh` green.
- [x] T020 Mark the spec Complete; run the acceptance blocks below.

```accept
# verifies: SC-001 — video behavior is unchanged and tagged with the video profile
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source/Movie.Production.2024.1080p" "$tmp/library"
printf x > "$tmp/source/Movie.Production.2024.1080p/Movie.Production.2024.1080p.mkv"
out=$(uv run --quiet trovium-ingest --source "$tmp/source" --library-root "$tmp/library" --json compact)
printf '%s' "$out" | jq -e '.declared.profile == "video"' >/dev/null
printf '%s' "$out" | jq -e '.items[0].kind == "movie" and .items[0].disposition == "ingested"' >/dev/null
test -f "$tmp/library/Movies/Movie Production (2024)/Movie.Production.2024.1080p.mkv"
```

```accept
# verifies: SC-002 — EPUB and PDF books land in the documented layout with original names
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
uv run --quiet python tests/fixtures/books/make_source.py "$tmp"
mkdir -p "$tmp/library"
out=$(uv run --quiet trovium-ingest --profile books --source "$tmp/source" --library-root "$tmp/library" --mode copy --json compact)
printf '%s' "$out" | jq -e '.declared.profile == "books" and .counts.ingested == 4' >/dev/null
test -f "$tmp/library/Books/Alice Author/The PDF Book (2021)/Alice Author - The PDF Book (2021).pdf"
test -f "$tmp/library/Books/Jane Doe/Embedded Title (2020)/Jane Doe - The Great Book (2020).epub"
```

```accept
# verifies: SC-003 — embedded EPUB metadata wins and the record names the source
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
uv run --quiet python tests/fixtures/books/make_source.py "$tmp"
mkdir -p "$tmp/library"
out=$(uv run --quiet trovium-ingest --profile books --source "$tmp/source" --library-root "$tmp/library" --mode copy --json compact)
item=$(printf '%s' "$out" | jq -c '.items[] | select(.name == "Jane Doe - The Great Book (2020)")')
printf '%s' "$item" | jq -e '.title == "Embedded Title" and .details.metadata_source == "epub"' >/dev/null
test -d "$tmp/library/Books/Jane Doe/Embedded Title (2020)"
```

```accept
# verifies: SC-004 — ambiguous names are surfaced and a second run is a no-op
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
uv run --quiet python tests/fixtures/books/make_source.py "$tmp"
mkdir -p "$tmp/library"
first=$(uv run --quiet trovium-ingest --profile books --source "$tmp/source" --library-root "$tmp/library" --mode copy --json compact)
printf '%s' "$first" | jq -e '.items[] | select(.name == "mystery file") | .disposition == "unresolvable"' >/dev/null
before=$(find "$tmp/library" -type f -exec cksum {} + | sort)
second=$(uv run --quiet trovium-ingest --profile books --source "$tmp/source" --library-root "$tmp/library" --mode copy --json compact)
after=$(find "$tmp/library" -type f -exec cksum {} + | sort)
test "$before" = "$after"
printf '%s' "$second" | jq -e '.counts.ingested == 0 and .counts.already_handled == 4' >/dev/null
```

```accept
# verifies: SC-005 — a registered non-media profile runs through the engine and CLI with no engine change
uv run --quiet pytest -q -p no:cacheprovider tests/unit/profiles/test_registry.py -k 'distros_profile'
```

```accept
# verifies: SC-006 — a malformed EPUB falls back to the filename and does not abort the run
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
uv run --quiet python tests/fixtures/books/make_source.py "$tmp"
mkdir -p "$tmp/library"
out=$(uv run --quiet trovium-ingest --profile books --source "$tmp/source" --library-root "$tmp/library" --mode copy --json compact)
item=$(printf '%s' "$out" | jq -c '.items[] | select(.name == "Jane Doe - Broken Book (2019)")')
printf '%s' "$item" | jq -e '.disposition == "ingested" and .title == "Broken Book" and .details.metadata_source == "filename"' >/dev/null
test -f "$tmp/library/Books/Jane Doe/Broken Book (2019)/Jane Doe - Broken Book (2019).epub"
```

## Dependencies and order

- T001-T003 before T004-T008.
- T008 must pass before T009.
- T009-T014 before T015.
- T016 needs `register_profile` from T002 and the generic engine from T004.
- T018 before T019; T020 last.
