# Implementation Plan: Profile-Driven Rename

**Feature**: `004-profile-rename` | **Date**: 2026-10-21

## Summary

Add a second pipeline step, `trovium-rename`, that consumes an ingest record
and renames the placed files using the profile's naming rules. It is
record-driven, dry-runnable, idempotent, and safe by default: copy/hardlink
records and client-relocated items are refused unless `--allow-unsafe` is set.

## Architecture

```text
stdin / --record -> validate -> profile.plan_names -> plan per item
                                      |
                                      v
                         collision check -> apply / dry-run
                                      |
                                      v
                               rename record
```

### Profile contract addition

```python
@dataclass(frozen=True)
class NamePlan:
    source: Path
    name: str | None
    reason: str | None = None


class Profile:
    def plan_names(
        self, classification: Classification, files: tuple[Path, ...]
    ) -> tuple[NamePlan, ...]:
        return tuple(NamePlan(path, path.name) for path in files)
```

`None` means the file cannot be named safely; the reason is reported and the
item is `skipped` (or `error` if other files in the item can be renamed).

### Naming

- Books: `Author - Title (Year).ext`; series:
  `Author - Series #N - Title (Year).ext`; unknown author omits the author.
- Video movie: `Title (Year).ext` only when the destination holds exactly one
  member file.
- Video TV: `Show - S01E01.ext`; extra episodes parsed from the file name
  become `-E02`.
- Sidecars keep their names.
- Suffixes are preserved as-is.

### Rename engine

- `rename.py` holds the record model, validation, planning, apply, and CLI.
- The input record is validated once: `declared` object, registered profile,
  `mode`, `items` list.
- Safety:
  - `mode != "move"` and no `--allow-unsafe` -> misuse (exit 2), no changes.
  - Item `client_actions` contains `setLocation` and no `--allow-unsafe` ->
    item `skipped` with a seeding reason.
  - `--allow-unsafe` writes a warning to stderr.
- Planning:
  - Scan the destination's direct files, so the plan is independent of the
    names a previous rename produced.
  - Detect duplicate target names across the item.
  - Refuse a target that exists and is not the source; fail the whole item.
  - A missing source with an existing target is a completed rename
    (`already_handled`).
- Applying:
  - Re-check each target immediately before renaming.
  - Rename one item's files in order; on failure, rename the applied ones back.
  - No delete; no overwrite.
- Record:
  - `renamed`, `already_handled`, `skipped`, `error`; `total` count.
  - Per item: `name`, `kind`, `title`, `details`, `destination`,
    `disposition`, `reason`, `actions` (`op: "rename"`).
  - Echo `declared.profile`, `declared.library_root`, `declared.mode`.

### CLI

```text
trovium-rename [--record PATH] [--dry-run] [--allow-unsafe]
               [--on-fail {stop,continue}] [--json {compact,pretty}]
```

- No `--record` reads stdin; a TTY with no record is misuse.
- Exit 0 for a completed run (including per-item skips/errors), 2 for misuse
  or an unsafe record without the override.
- Add the console script `trovium-rename = "trovium.rename:main"`.

## Contract changes

- `specs/004-profile-rename/contracts/cli.md`
- `specs/004-profile-rename/contracts/record-schema.md`
- Update `docs/profiles.md` and the profile contract note: `plan_names` returns
  `NamePlan`.
- README usage and pipeline example.

## Risks and mitigations

| Risk                                                      | Mitigation                                                                                                               |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Renaming a seeding file breaks the client                 | Move-only default; skip `setLocation` items; explicit `--allow-unsafe`                                                   |
| Renaming a copy/hardlink item breaks ingest's no-op rerun | Refuse non-move records by default                                                                                       |
| `Path.rename` replaces an existing target on POSIX        | Pre-check target before every rename; fail the item and roll back                                                        |
| Multi-file movies/TV packs have no unambiguous name       | `plan_names` returns `None` with a reason; item is `skipped`                                                             |
| A prior partial run leaves both old and new names         | Re-run plans by scanning the destination; missing source + existing target is `already_handled`; both present is `error` |

## Testing strategy

- Unit: `NamePlan` for books, movie, TV, multi-episode, multi-file skip.
- Unit: rename planning (dry-run, rerun, collision, unsafe refusal,
  `setLocation` skip, malformed record, unknown profile).
- Integration: `trovium-ingest` books/movie/TV record piped into rename; verify
  names and rerun.
- Acceptance: books, video, dry-run parity, rerun, safety refusal, collision.
