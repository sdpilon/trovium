# Writing a media profile

Trovium's promise is one pipeline with many media types, not one application
per type. A **profile** is the module that teaches the generic ingest engine
about one type. It answers:

1. Which files belong to a candidate?
2. What does the candidate mean?
3. Where does the library item belong?

The engine owns sources, placement, conflict handling, idempotency, client
actions, and the run record. A profile is not a pipeline step and not a
configuration language.

The full contract is
[`specs/003-media-profiles-books/contracts/profile.md`](../specs/003-media-profiles-books/contracts/profile.md).

## The smallest useful profile

`tests/fixtures/profiles/distros.py` is a complete non-media example. It
classifies Linux distribution images and places them under
`Distros/<Name>/<Version>/<Arch>/`:

```python
class DistrosProfile(Profile):
    name = "distros"
    categories = ("iso", "all")
    extensions = frozenset({".iso", ".img"})

    def groups(self, entry: Path) -> tuple[CandidateGroup, ...]:
        files = self.collect_files(entry)
        if not files:
            return ()
        return (CandidateGroup(name=entry.name, files=files, root=entry),)

    def classify(self, group: CandidateGroup) -> Classification | None:
        match = _IMAGE.search(group.name)
        if match is None:
            return None
        return Classification(
            profile=self.name,
            kind="iso",
            title=match.group("name"),
            details={"version": match.group("version"), "arch": match.group("arch")},
        )

    def destination(self, classification, library_root: Path) -> Path:
        return (
            library_root
            / "Distros"
            / safe_component(classification.title or "Unknown").title()
            / safe_component(str(classification.details["version"]))
            / safe_component(str(classification.details["arch"]))
        )
```

Register it in `src/trovium/profiles/__init__.py`:

```python
from trovium.profiles.distros import DistrosProfile

PROFILES = {
    profile.name: profile
    for profile in (VideoProfile(), BooksProfile(), DistrosProfile())
}
```

Then `trovium-ingest --profile distros --source ~/isos --library-root ~/library`
works with no engine change.

## The methods

| Method                              | Required | Responsibility                                 |
| ----------------------------------- | -------- | ---------------------------------------------- |
| `is_member(path)`                   | no       | default: suffix in `extensions`                |
| `is_incidental(path)`               | no       | default: never; override for samples/clutter   |
| `collect_files(root)`               | no       | default: recursive member files                |
| `groups(entry)`                     | yes      | split one source entry into candidates         |
| `classify(group)`                   | yes      | return `Classification` or `None`; never guess |
| `destination(classification, root)` | yes      | library path beneath `root`                    |
| `plan_names(classification, files)` | no       | identity until the rename step                 |

`Classification.details` is emitted as the item's `details` object. Keep the
keys stable for a profile; downstream steps and users read them.

## Rules

- Read candidate files if the type carries metadata (EPUB is the example), but
  never write, move, or delete during classification.
- Return `None` for ambiguity. The engine records `unresolvable` and leaves
  the source untouched.
- Use `safe_component` for every user-derived path segment.
- Keep destinations stable; idempotency compares the resolved destination's
  files by name, size, and hash. An unstable layout breaks the no-op rerun.
- One candidate's files travel together. If a folder holds many items, yield
  one group per item (books does this).
- A profile does not add a pipeline capability. Browsing or downloading a new
  type is a new step, not a larger profile.

## Tests to add

- Membership and incidental filtering.
- Grouping: one entry, many entries, empty.
- Classification: a confident name, an ambiguous name, a metadata-bearing
  file, and a malformed file.
- Destination: normal, unknown fields, and unsafe characters.
- One integration test that drives the CLI with `--profile` and verifies the
  record and the placed files.
- One rerun test: the second run is `already_handled` and changes nothing.

The `distros` test in `tests/unit/profiles/test_registry.py` is the template
for proving a new profile needs no engine changes.
