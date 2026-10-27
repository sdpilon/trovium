# Tasks: Books Series Prefixes and Sibling Metadata

**Feature**: `006-books-behavior` | **Plan**: [plan.md](plan.md) |
**Spec**: [spec.md](spec.md) | **Contract**:
[contracts/books-behavior.md](contracts/books-behavior.md)

## Phase 1: Setup

**Purpose**: Confirm the current suite is the baseline before the behavior
changes.

- [x] T001 Run the existing books, rename, and video tests as a baseline with
      `uv run pytest` on `tests/unit/profiles/test_books.py`,
      `tests/unit/profiles/test_video.py`,
      `tests/integration/test_books_ingest.py`,
      `tests/integration/test_run_pipeline.py`, and
      `tests/unit/test_rename.py`.

## Phase 2: User Story 1 - Numbered series files (P1) 🎯 MVP

**Goal**: A leading `N - Title` or `N. Title` becomes a series index, and
rename keeps that index in the canonical filename.

**Independent Test**: Ingest `01 - Sample Title.azw3` and
`2. Another Title (2021).epub`; verify the record fields, destination, and
renamed names without involving sibling metadata.

### Tests for User Story 1

- [x] T002 [P] [US1] Replace the obsolete numeric-prefix test and add cases
      for `01 - Sample Title`, `0001 - Title`, `0999 - Title`,
      `2. Another Title (2021)`, `01 - Sample Title - Sample Author`,
      `01 - Sample Title (Author)`, `2020 - A Title`, `1000 - A Title`,
      `0 - A Title`, `1.5 - Title`, `1 - Title (2020)` precedence, and
      `1 - Series #2 - Title` precedence in
      `tests/unit/profiles/test_books.py`.
- [x] T003 [P] [US1] Add `plan_names` tests for `N - Title (Year)`, a missing
      year, and the author-plus-index case (the numeric form wins) in
      `tests/unit/profiles/test_books.py`.

### Implementation for User Story 1

- [x] T004 [US1] Add `_SERIES_INDEX` to `src/trovium/profiles/books.py` with
      the 1–999 range check, whitespace-aware separator, trailing-year
      handling, and precedence before the existing series/author forms.
- [x] T005 [US1] Add the numeric branch to `BooksProfile._base_name` in
      `src/trovium/profiles/books.py`, rendering `N - Title (Year)` when the
      series name is absent.
- [x] T006 [US1] Add an ingest-to-rename integration test for a numbered file
      in `tests/integration/test_rename_pipeline.py`, asserting the placed
      destination and the `1 - Sample Title.azw3` target.

**Checkpoint**: User Story 1 works without any sibling metadata. Ingest and
rename for numbered files are independently testable.

---

## Phase 3: User Story 2 - Metadata across sibling formats (P1)

**Goal**: A non-EPUB file without its own metadata uses exactly one same-stem
sibling EPUB, so both formats share a destination; ambiguous pairing is
`unresolvable` with a named reason.

**Independent Test**: Ingest the mixed `Sample Title - Sample Author` EPUB/AZW3
folder and verify both destinations and the AZW3 metadata source; then ingest a
folder with two same-stem EPUBs and verify the AZW3 is `unresolvable` while the
EPUBs keep their own classifications.

### Tests for User Story 2

- [x] T007 [P] [US2] Add unit tests for sibling metadata in
      `tests/unit/profiles/test_books.py`: one sibling, sibling plus filename,
      own `metadata.opf` wins, an unreadable own `metadata.opf` treated as
      absent, malformed sibling fallback, and the ambiguous result, including
      two same-stem EPUBs where one is malformed.
- [x] T008 [P] [US2] Add integration tests for the mixed folder, the
      `epub+sibling` record value, the ambiguous reason, and the surviving EPUB
      records, including one valid and one malformed same-stem EPUB, in
      `tests/integration/test_books_ingest.py`.

### Implementation for User Story 2

- [x] T009 [US2] Add the `Unresolved(reason)` result and the widened
      `Profile.classify` return type in `src/trovium/profiles/base.py`, and
      export it from `src/trovium/profiles/__init__.py`.
- [x] T010 [US2] Handle `Unresolved` in `src/trovium/cli.py` by emitting its
      reason for the `unresolvable` item before the generic `None` reason.
- [x] T011 [US2] Implement same-stem sibling discovery, `epub+sibling` and
      `epub+sibling+filename` labels, own-metadata precedence, and the
      ambiguity result in `src/trovium/profiles/books.py`.

**Checkpoint**: User Stories 1 and 2 both work. A mixed folder resolves both
formats to one destination; an ambiguous folder names the conflict without
guessing.

---

## Phase 4: Polish & Cross-Cutting Concerns

- [x] T012 [P] Update `docs/profiles.md`, `README.md`, and
      `specs/006-books-behavior/contracts/books-behavior.md` so the numeric
      grammar, sibling rules, `metadata_source` values, and `Unresolved`
      result match the implementation.
- [x] T013 Run the full `scripts/check.sh` gate in the background and follow
      its log until it passes.
- [x] T014 Mark `specs/006-books-behavior/spec.md` **Status: Complete**, check
      every task above, and run
      `.specify/gates/verify.sh --accept 006-books-behavior` to execute the
      acceptance blocks below.

## Acceptance

```accept
# verifies: SC-001 — a numbered file lands under Unknown and renames to the canonical index form
tmp=$(mktemp -d)
tmp=$(cd "$tmp" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source" "$tmp/library"
printf 'azw3\n' > "$tmp/source/01 - Sample Title.azw3"
uv run --quiet trovium-ingest --profile books --source "$tmp/source" \
  --library-root "$tmp/library" --mode move --json compact > "$tmp/ingest.json"
jq -e '.items[0].title == "Sample Title" and .items[0].details.series_index == 1' "$tmp/ingest.json" >/dev/null
jq -e '.items[0].details.author == null' "$tmp/ingest.json" >/dev/null
jq -e --arg dest "$tmp/library/Books/Unknown/Sample Title" \
  '.items[0].destination == $dest' "$tmp/ingest.json" >/dev/null
uv run --quiet trovium-rename --record "$tmp/ingest.json" --json compact > "$tmp/rename.json"
jq -e '.counts.error == 0' "$tmp/rename.json" >/dev/null
test -f "$tmp/library/Books/Unknown/Sample Title/1 - Sample Title.azw3"
```

```accept
# verifies: SC-002 — a mixed EPUB/AZW3 folder places both formats in one destination
tmp=$(mktemp -d)
tmp=$(cd "$tmp" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source" "$tmp/library"
uv run --quiet python - "$tmp" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, ".")
from tests.books_support import make_epub

root = Path(sys.argv[1])
make_epub(
    root / "source/Sample Title - Sample Author.epub",
    title="Sample Title",
    author="Sample Author",
    year=2020,
)
(root / "source/Sample Title - Sample Author.azw3").write_bytes(b"azw3")
PY
uv run --quiet trovium-ingest --profile books --source "$tmp/source" \
  --library-root "$tmp/library" --mode move --json compact > "$tmp/ingest.json"
test -f "$tmp/library/Books/Sample Author/Sample Title (2020)/Sample Title - Sample Author.epub"
test -f "$tmp/library/Books/Sample Author/Sample Title (2020)/Sample Title - Sample Author.azw3"
```

```accept
# verifies: SC-003 — ambiguous sibling pairing names the conflict and leaves the AZW3 unplaced
tmp=$(mktemp -d)
tmp=$(cd "$tmp" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source" "$tmp/library"
uv run --quiet python - "$tmp" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, ".")
from tests.books_support import make_epub

root = Path(sys.argv[1])
make_epub(root / "source/Book.epub", title="Book", author="Author", year=2020)
(root / "source/Book.EPUB").write_bytes(b"not a zip")
(root / "source/Book.azw3").write_bytes(b"azw3")
PY
if [ "$(find "$tmp/source" -maxdepth 1 -name 'Book.*' | wc -l | tr -d ' ')" -lt 3 ]; then
  echo "skip: filesystem cannot hold two same-stem EPUBs (see T007/T008)"
  exit 0
fi
# one valid and one malformed EPUB share the stem; both count for ambiguity
uv run --quiet trovium-ingest --profile books --source "$tmp/source" \
  --library-root "$tmp/library" --mode move --json compact > "$tmp/ingest.json"
jq -e '.items[] | select(.name == "Book" and .details.format == "epub" and .details.metadata_source == "epub") | .disposition == "ingested"' "$tmp/ingest.json" >/dev/null
test -f "$tmp/library/Books/Author/Book (2020)/Book.epub"
jq -e '.items[] | select(.name == "Book" and .disposition == "unresolvable" and (.reason | test("ambiguous")))' "$tmp/ingest.json" >/dev/null
test -z "$(find "$tmp/library" -name 'Book.azw3' -print -quit)"
```

```accept
# verifies: SC-004 — both formats name their metadata source
tmp=$(mktemp -d)
tmp=$(cd "$tmp" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source" "$tmp/library"
uv run --quiet python - "$tmp" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, ".")
from tests.books_support import make_epub

root = Path(sys.argv[1])
make_epub(
    root / "source/Sample Title - Sample Author.epub",
    title="Sample Title",
    author="Sample Author",
    year=2020,
)
(root / "source/Sample Title - Sample Author.azw3").write_bytes(b"azw3")
PY
uv run --quiet trovium-ingest --profile books --source "$tmp/source" \
  --library-root "$tmp/library" --mode move --json compact > "$tmp/ingest.json"
jq -e '[.items[] | select(.details.format == "epub")][0].details.metadata_source == "epub"' "$tmp/ingest.json" >/dev/null
jq -e '[.items[] | select(.details.format == "azw3")][0].details.metadata_source == "epub+sibling"' "$tmp/ingest.json" >/dev/null
```

SC-005 is covered by T013; it has no separate CLI block.

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 starts immediately.
- **User Story 1 (Phase 2)**: Starts after T001. T002/T003 are the tests;
  T004/T005 implement; T006 integrates.
- **User Story 2 (Phase 3)**: Starts after T001. T007/T008 are the tests;
  T009/T010 add the result channel; T011 implements the books behavior.
- **Polish (Phase 4)**: T012 after T006 and T011; T013 after T012; T014 last.

### Story Dependencies

- **US1** is the MVP and has no dependency on US2.
- **US2** has no logical dependency on US1, but both edit
  `src/trovium/profiles/books.py`. Finish US1 (T004/T005) before starting
  T011 to avoid overlapping edits.

### Within Each Story

- Write the tests in T002/T003 and T007/T008 first; they should fail before
  the matching implementation.
- T004 before T005; T005 before T006.
- T009 before T010; T010 before T011.
- T012 covers all behavior; T013 is the full gate; T014 is the completion
  marker and acceptance run.

## Parallel Execution Examples

### User Story 1

```bash
# The parser tests and the rename tests touch different files:
Task: "T002 [P] [US1] Add parser tests in tests/unit/profiles/test_books.py"
Task: "T003 [P] [US1] Add plan_names tests in tests/unit/profiles/test_books.py"

# Then the implementation is sequential because both tasks edit books.py:
Task: "T004 [US1] Add _SERIES_INDEX in src/trovium/profiles/books.py"
Task: "T005 [US1] Add the numeric rename branch in src/trovium/profiles/books.py"
Task: "T006 [US1] Add the ingest-to-rename integration test"
```

### User Story 2

```bash
# The unit and integration tests touch different files:
Task: "T007 [P] [US2] Add sibling unit tests in tests/unit/profiles/test_books.py"
Task: "T008 [P] [US2] Add sibling integration tests in tests/integration/test_books_ingest.py"

# Then the shared result channel and the profile implementation:
Task: "T009 [US2] Add Unresolved in src/trovium/profiles/base.py"
Task: "T010 [US2] Handle Unresolved in src/trovium/cli.py"
Task: "T011 [US2] Implement sibling lookup in src/trovium/profiles/books.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001.
2. Complete T002–T006.
3. Run the books and rename tests; verify the numbered form end to end.
4. Stop and validate before adding sibling metadata.

### Incremental Delivery

1. US1 lands the grammar and rename change.
2. US2 adds sibling metadata and the named ambiguity result.
3. T012 documents the shipped behavior.
4. T013 proves the full gate; T014 marks the spec Complete and runs the
   acceptance blocks.

## Notes

- [P] tasks touch different files and have no incomplete-task dependency.
- Tests are included because the constitution requires coverage per behavior
  (XVII), not because the spec requests TDD.
- The case-sensitive ambiguity acceptance block skips on a filesystem that
  cannot hold two same-stem EPUBs; T007 proves the branch independently.
- Keep `metadata_source` values and the record envelope additive; do not
  change video or music behavior.
- Commit at coherent boundaries after the spec, plan, contract, and
  implementation chunks; the full gate is the pre-PR proof.
