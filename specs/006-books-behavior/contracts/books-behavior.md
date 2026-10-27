# Books Behavior Contract

**Feature**: `006-books-behavior` | **Date**: 2026-10-26

This extends the books record schema in
`specs/003-media-profiles-books/contracts/record-schema.md` and the naming
contract in `specs/004-profile-rename/contracts/profile.md`. The record
envelope, dispositions, CLI options, exit codes, and destination rules are
unchanged.

## Filename grammar

The books profile recognizes one additional form, checked before the existing
series and author forms:

```text
N - Title
N. Title
```

`N` is an integer from 1 to 999, with leading zeros allowed; the value, not
the digit width, is checked. The separator is a hyphen with whitespace on both
sides, or a period followed by whitespace. An
optional trailing `(Year)` is the only special text after the prefix;
everything else belongs to the title. The form does not imply an author or a
series name.

| Input                               | Parse                                               |
| ----------------------------------- | --------------------------------------------------- |
| `01 - Sample Title`                 | title `Sample Title`, `series_index` 1, author null |
| `2. Another Title (2021)`           | title `Another Title`, `series_index` 2, year 2021  |
| `01 - Sample Title - Sample Author` | title `Sample Title - Sample Author`, author null   |
| `01 - Sample Title (Author)`        | title `Sample Title (Author)`, author null          |
| `2020 - A Title`                    | not this form; remains `unresolvable`               |
| `1000 - A Title`                    | not this form; remains `unresolvable`               |
| `0 - A Title`                       | not this form; remains `unresolvable`               |
| `1.5 - Title`                       | not this form; remains `unresolvable`               |

All other documented forms and the #41 ambiguous-name behavior are unchanged.
An integer outside 1–999 falls through to the existing forms.

## Sibling metadata

A non-EPUB candidate with no usable own metadata may use a sibling EPUB:

- The sibling is a regular `.epub` file in the candidate's folder with exactly
  the same filename stem (case-sensitive `Path.stem`).
- Exactly one same-stem EPUB file must exist, whether or not it is readable.
  Two or more same-stem EPUB files make the candidate `unresolvable`; the
  reason names the ambiguity and the candidates involved.
- When the sole sibling EPUB is malformed or has no usable metadata, fall
  back to the filename; it does not fail the run.
- Own embedded metadata or a readable `metadata.opf` wins wholesale. An
  unreadable own `metadata.opf` is treated as absent.
- The sibling is read, never moved or placed as part of this candidate. Each
  file remains its own candidate.

### `metadata_source`

The books `details.metadata_source` field gains two values:

| Value                   | Meaning                                                                                         |
| ----------------------- | ----------------------------------------------------------------------------------------------- |
| `epub+sibling`          | The sibling EPUB supplied every used field                                                      |
| `epub+sibling+filename` | The sibling EPUB supplied at least one field and the filename filled at least one missing field |

Existing values (`epub`, `opf`, `filename`, `epub+filename`, `opf+filename`)
are unchanged.

## Profile result

The profile contract gains an additive result for a named unresolved reason:

```python
@dataclass(frozen=True)
class Unresolved:
    reason: str


class Profile:
    def classify(self, group: CandidateGroup) -> Classification | Unresolved | None: ...
```

`None` keeps the engine's generic "name grammar not confidently matched"
reason. `Unresolved` lets the profile explain a specific failure, such as an
ambiguous sibling pairing. Only the books profile returns it in this feature;
other profiles keep their existing return values.

## Rename names

The books naming rules gain one form:

| Classification   | Target                                  |
| ---------------- | --------------------------------------- |
| series and index | `Author - Series #N - Title (Year).ext` |
| index, no series | `N - Title (Year).ext`                  |
| author, no index | `Author - Title (Year).ext`             |
| neither          | `Title (Year).ext`                      |

`Author` is included only when known; an unknown author omits the prefix, as
in the 004 naming contract. The year is omitted when absent, and `N` is
rendered with `_format_index` (integer or decimal, no artificial padding).
Sidecars keep their names and suffixes are preserved. If sibling metadata
supplies an author while the filename supplies the index, the index form wins
for the filename; the author remains in the record and the destination.

## Invariants

- No new runtime dependency.
- No guessing: ambiguous pairing is `unresolvable`, never a best-effort match.
- The record envelope and dispositions are unchanged.
- The `Books/<Author>/<Title> (Year)/` destination is unchanged.
- A second ingest or rename run remains a no-op.
