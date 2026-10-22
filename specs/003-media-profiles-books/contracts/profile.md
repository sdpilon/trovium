# Profile Contract

**Feature**: `003-media-profiles-books` | **Date**: 2026-10-21

> **Update**: `specs/004-profile-rename/contracts/profile.md` changes
> `plan_names` to return `NamePlan` values. The rest of this contract still
> applies.

A profile is the media-type module the ingest engine delegates to. It answers
three questions and nothing else:

1. Which files belong to a candidate?
2. What does the candidate mean (kind, title, details)?
3. Where does the resulting library item belong?

Sources, placement, conflict handling, idempotency, client actions, and the
record envelope stay in the engine. A profile is not a pipeline step and not a
configuration language.

## The class

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

`is_member`, `is_incidental`, `collect_files`, and `plan_names` have defaults.
`groups`, `classify`, and `destination` are required.

### Types

```python
@dataclass(frozen=True)
class CandidateGroup:
    name: str
    files: tuple[Path, ...]
    root: Path | None = None


@dataclass(frozen=True)
class Classification:
    profile: str
    kind: str
    title: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)
```

- `name` is the display name used by the classifier and the record.
- `files` is everything that travels with the candidate, including sidecars.
- `kind` is profile-defined. It is emitted as `kind` in the record and is the
  value matched by `category`.
- `details` is profile-defined and emitted as the item's `details` object.
- `classify` returns `None` when it cannot classify confidently. The engine
  records `unresolvable`; the profile must not guess.

### Registration

```python
# src/trovium/profiles/mytype.py
class MyTypeProfile(Profile):
    name = "mytype"
    categories = ("thing", "all")
    extensions = frozenset({".thing"})
    ...


# src/trovium/profiles/__init__.py
from trovium.profiles.mytype import MyTypeProfile

PROFILES = {
    profile.name: profile
    for profile in (VideoProfile(), BooksProfile(), MyTypeProfile())
}
```

A test or distribution can call `register_profile(profile)` instead. The engine
never imports a built-in profile; it resolves the requested name through the
registry.

## The rules

- Classification may read the candidate's files (for example an EPUB's OPF),
  but must not write, move, or delete anything.
- `destination` must return a path beneath the library root and must use
  `safe_component` for user-derived folder names.
- Idempotency is convention-based: the engine compares the candidate's files
  with the resolved destination by name, size, and hash. A profile that yields
  unstable destinations breaks the no-op rerun guarantee.
- A profile that needs a new capability (browse, download, schedule) is
  pointing at a new pipeline step, not a larger profile.

## Reference profile

`tests/fixtures/profiles/distros.py` is a complete, non-media profile:

- membership: `.iso`, `.img`;
- grouping: one candidate per source entry;
- classification: `ubuntu-24.04.1-live-server-amd64.iso` becomes
  `kind: "iso"`, title `Ubuntu`, details `{version, arch}`;
- destination: `Distros/<Name>/<Version>/<Arch>/`.

It is registered only by the tests. The test
`tests/unit/profiles/test_registry.py` runs it through `run_disk` and the CLI
without any engine change.

## Checklist for a new profile

- [ ] Module under `src/trovium/profiles/`, subclassing `Profile`.
- [ ] Declares `name`, `categories`, and `extensions`.
- [ ] Implements `groups`, `classify`, and `destination`.
- [ ] Returns `None` for ambiguous names.
- [ ] Uses `safe_component` for every user-derived path segment.
- [ ] Adds unit tests for membership, grouping, classification, and layout.
- [ ] Adds one integration test that drives the CLI with `--profile`.
- [ ] Registers in `src/trovium/profiles/__init__.py`.
- [ ] Documents the new `kind`, category values, and `details` keys.
