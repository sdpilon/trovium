# Profile Naming Contract

**Feature**: `004-profile-rename` | **Date**: 2026-10-21

This extends the profile contract from
`specs/003-media-profiles-books/contracts/profile.md` with the rename hook.

## NamePlan

```python
@dataclass(frozen=True)
class NamePlan:
    source: Path
    name: str | None
    reason: str | None = None
```

`name is None` means the file cannot be named safely; `reason` is shown in the
rename record. A profile returns one plan per input file, in input order.

```python
def plan_names(
    self, classification: Classification, files: tuple[Path, ...]
) -> tuple[NamePlan, ...]: ...
```

The default implementation keeps every file's current name. The hook must not
read or write files beyond what classification already needs; it is a pure
mapping from classification plus file paths to names.

## Built-in rules

### Books

- author, title, year: `Author - Title (Year).ext`
- with series and index: `Author - Series #N - Title (Year).ext`
- no author: `Title (Year).ext`
- no year: omit the parenthesized year
- sidecars (cover, `metadata.opf`, `.nfo`): unchanged

### Video

- movie with one member file: `Title (Year).ext`
- TV file with `SxxEyy`: `Show - S01E01.ext`; extra episodes become `-E02`
- multi-file movie: every member gets `None` with a reason
- TV file without an episode marker: `None` with a reason
- sidecars: unchanged

## Rules

- Preserve the source suffix.
- Use `safe_component` for every user-derived segment.
- A target must be a bare file name, not a path.
- Do not include quality, codec, edition, or release-group tokens in this
  slice.
- Two files must not map to the same target; the rename engine fails the item
  closed.
