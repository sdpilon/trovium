# Implementation Plan: Media Profiles and Books

**Feature**: `003-media-profiles-books` | **Date**: 2026-10-21

## Summary

Extract the media-type decisions currently fused into `classify.py`,
`library.py`, `record.py`, `config.py`, and `cli.py` behind a small `Profile`
contract. Keep the ingest engine generic. Add a `books` profile that reads EPUB
metadata, falls back to a conservative filename grammar, and places ebooks
under `Books/<Author>/<Title> (Year)/`. Prove developer extensibility with a
test-only `distros` profile.

Video behavior and every existing test must stay green. The record and config
changes are additive.

## Technical Context

- Python 3.13, uv, `httpx` remains the only runtime dependency.
- EPUB parsing uses the standard library: `zipfile`, `xml.etree.ElementTree`.
- No network access during classification.
- The engine continues to emit the same JSON envelope; only `declared.profile`
  and an optional per-item `details` object are added.

## Architecture

```text
sources -> CandidateGroup -> Profile.classify -> Classification
                                  |
                                  v
                         Profile.destination -> compare_existing
                                  |
                                  v
                         plan_placement / apply_placement
                                  |
                                  v
                              ItemRecord
```

- `src/trovium/profiles/base.py`: `Profile` ABC, `CandidateGroup`,
  `Classification`, `safe_component`, shared membership helpers.
- `src/trovium/profiles/video.py`: video extensions, incidental rules,
  grouping, classifier, destination.
- `src/trovium/profiles/books.py`: ebook extensions, grouping, EPUB metadata,
  filename grammar, destination.
- `src/trovium/profiles/epub.py`: a small, defensive OPF reader.
- `src/trovium/profiles/__init__.py`: registry, `get_profile`,
  `available_profiles`, `register_profile`.

The engine modules import `Profile` and `Classification`, never a built-in
profile. The registry is the only place that names the built-ins.

### Profile contract

```python
class Profile(ABC):
    name: ClassVar[str]
    categories: ClassVar[tuple[str, ...]]
    extensions: ClassVar[frozenset[str]]

    def is_member(self, path: Path) -> bool: ...
    def is_incidental(self, path: Path) -> bool: ...
    def collect_files(self, root: Path) -> tuple[Path, ...]: ...
    def groups(self, entry: Path) -> tuple[CandidateGroup, ...]: ...
    def classify(self, group: CandidateGroup) -> Classification | None: ...
    def destination(self, classification, library_root: Path) -> Path: ...
    def plan_names(self, classification, files) -> tuple[tuple[Path, str], ...]: ...
```

`classify` returns `None` when no confident match exists. `plan_names` returns
identity in this feature; the rename step will use it.

### Engine changes

- `sources.disk_candidates(source_dir, profile)` asks the profile for groups.
  A source entry that yields no groups still produces one empty candidate, so
  the record can report `rejected_out_of_scope` with a reason.
- `sources.client_candidates(entries, profile)` keeps one candidate per
  torrent and asks the profile for its member files.
- `cli.process(..., profile)` classifies, scope-filters, resolves the
  destination, compares, plans, and applies. It no longer imports video code.
- `cli.in_scope(kind, category)` treats `all` as the only wildcard.
- `record.Declared` carries `profile` and a string `category`; `ItemRecord`
  carries an optional `details` map.
- `config` parses `profile` first, validates it against the registry, then
  validates `category` against that profile. Missing `profile` means `video`.
- The CLI adds `--profile`; the argument parser no longer pins category
  choices, because they are profile-dependent. The resolver names the allowed
  values in a misuse error.

## Books design

### Grouping

- A book file is one candidate.
- Recurse through a source directory and yield one group per member file.
- If a book's immediate parent contains exactly one member file, include
  recognized sidecars from that parent: `cover.*`, `metadata.opf`, `*.nfo`.
- If a parent contains several books, sidecars are unattributable and are
  ignored.

### Metadata

1. EPUB OPF (`META-INF/container.xml` -> OPF path -> `dc:title`,
   `dc:creator`, `dc:date`, `meta[@name='calibre:series']`,
   `meta[@name='calibre:series_index']`).
2. A sibling `metadata.opf`, parsed with the same reader.
3. Filename grammar.

Fields are merged: OPF values win; missing fields may be filled from the
filename. `details.metadata_source` is one of `epub`, `epub+filename`,
`filename`, or `filename-only` (for non-EPUB formats).

EPUB safety: cap `container.xml` and OPF reads, reject entries that are not
regular files, use `xml.etree.ElementTree` without external entity resolution,
and fall back on `zipfile.BadZipFile`, `KeyError`, `ET.ParseError`, and
`OSError`. A bad archive is an `unresolvable`/filename outcome, not a run-level
failure.

### Filename grammar

Precedence, first match wins:

1. `Author - Series #N - Title (Year)`
2. `Author - Title (Year)`
3. `Title (Year) - Author`
4. `Title (Author)` (year optional)
5. `Title (Year)` (author unknown)

Recognize `-`, `–`, and `—` as separators. Strip bracketed release tags
only when they are not a four-digit year. If the result has no title, return
`None`.

### Destination

```text
Books/<Author>/<Title> (Year)/
Books/<Author>/<Title>/
Books/Unknown/<Title> (Year)/
```

Author and title pass through `safe_component` (illegal path characters
removed). Series and series index stay in `details`; the rename step will use
them.

### Record

```json
{
  "declared": { "profile": "books", "category": "all", "...": "..." },
  "items": [
    {
      "kind": "book",
      "title": "The Book",
      "details": {
        "author": "Jane Doe",
        "year": 2020,
        "series": null,
        "series_index": null,
        "format": "epub",
        "metadata_source": "epub"
      }
    }
  ]
}
```

Video keeps `kind: "movie" | "tv"` and gains only `declared.profile`; its
`details` may carry the existing year/season/episodes information.

## Contract changes

- `specs/003-media-profiles-books/contracts/profile.md` (new, developer
  contract).
- `specs/003-media-profiles-books/contracts/record-schema.md` (v2 addendum:
  `declared.profile`, `details`, profile-defined `kind`/`category`).
- `specs/003-media-profiles-books/contracts/cli.md` (add `--profile`,
  profile-dependent category).
- `specs/003-media-profiles-books/contracts/config-schema.md` (add
  `[ingest] profile`; category validation).
- `docs/profiles.md` (how to add a profile, with the `distros` example).

The configuration schema version stays `1`: the new key is optional and the
default preserves every existing config.

## Risks and mitigations

| Risk                                  | Mitigation                                                                    |
| ------------------------------------- | ----------------------------------------------------------------------------- |
| Book filenames are ambiguous          | EPUB metadata first; conservative grammar; `unresolvable` over guessing       |
| EPUB parsing is a security surface    | Size caps, regular-file checks, stdlib parser, fallback on any error          |
| Profile ABC guessed with one consumer | Books is the second consumer; the `distros` fixture is a third, non-media one |
| Video regression from the refactor    | Run the full video suite after the seam, before books                         |
| Record contract break                 | Additive fields only; video `kind`/`category` values unchanged                |
| Category validation drift             | One resolver validates against the selected profile for both CLI and config   |

## Implementation sequence

1. Write the profile types and registry.
2. Move video logic behind `VideoProfile`; update the engine and tests.
3. Run the full existing suite; fix regressions before books.
4. Add the books profile: grouping, filename grammar, destination.
5. Add the EPUB OPF reader and metadata merge.
6. Add books unit and integration tests.
7. Add the `distros` fixture test and the profile-author guide.
8. Update contracts and README.
9. Run `scripts/check.sh`, then mark the spec Complete and run the acceptance
   blocks.

## Testing strategy

- Unit: video classifier/destination/grouping; books grammar, metadata merge,
  destination, sidecar grouping; registry behavior.
- Contract: record shape (`declared.profile`, `details`), CLI `--profile`,
  category validation, config default.
- Integration: video regression; books disk ingest from generated EPUB/PDF
  fixtures; rerun no-op; malformed EPUB fallback.
- Extension: a `distros` profile registered in the test process runs through
  `disk_candidates`, `process`, and `run_disk` with no engine changes.
