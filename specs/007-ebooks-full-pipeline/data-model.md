# Data Model: Ebooks Through the Full Pipeline

**Feature**: `007-ebooks-full-pipeline` | **Date**: 2026-10-29

## Placement mode

| Value      | Meaning                                                                 |
| ---------- | ----------------------------------------------------------------------- |
| `move`     | Relocate the source file into the library; source no longer present.    |
| `copy`     | Copy the file; the source stays untouched.                              |
| `hardlink` | Link the file when possible; fall back to copy with a reason otherwise. |
| `auto`     | Resolve per candidate from the matrix below.                            |

### Resolution matrix

| Source | Client state | Same filesystem | Effective mode                                  |
| ------ | ------------ | --------------- | ----------------------------------------------- |
| any    | any          | any             | explicit value (hardlink may fall back to copy) |
| disk   | none         | any             | `move`                                          |
| client | not seeding  | any             | `move`                                          |
| client | seeding      | yes             | `hardlink`                                      |
| client | seeding      | no              | `copy`                                          |

Same filesystem means the source file and the nearest existing ancestor of the
destination share a device (`st_dev`). An unavailable hardlink falls back to
`copy` with a reason; the item is not an error.

## Candidate

One source entry expanded by the active profile.

| Field               | Type                | Notes                                              |
| ------------------- | ------------------- | -------------------------------------------------- |
| `name`              | string              | Torrent name or disk entry name.                   |
| `source`            | `disk` \| `client`  | Drives the mode matrix.                            |
| `files`             | list of paths       | Member files, sidecars included when grouped.      |
| `root`              | path or null        | Source directory; used by the move guard.          |
| `client_state`      | `none` \| `seeding` | Set by the adapter; disk entries are `none`.       |
| `unresolved_reason` | string or null      | Set when a client entry expands to several groups. |
| `client_hash`       | string or null      | Adapter identity for client updates.               |

## Configuration

`[ingest]` gains the `auto` value; new installs write it.

```ini
[ingest]
profile = books
mode = auto
```

| Key       | Required | Default for new installs | Values                             |
| --------- | -------- | ------------------------ | ---------------------------------- |
| `profile` | no       | `video`                  | any registered profile             |
| `mode`    | no       | `auto`                   | `auto`, `move`, `copy`, `hardlink` |

Existing configs keep whatever they already declare. `trovium-deploy install`
and `install.sh` accept `--profile NAME`; an unknown name is refused before any
file is written.

## Ingest record

The combined `trovium-run` record keeps the existing shape; these fields carry
the feature:

| Field                      | Change                                                           |
| -------------------------- | ---------------------------------------------------------------- |
| `declared.mode`            | May be `auto`; still echoes the operator's choice.               |
| `items[].actions[].op`     | `move`, `copy`, or `link` — the effective operation per file.    |
| `items[].actions[].reason` | Carries `hardlink unavailable…; copied instead` when applicable. |
| `items[].disposition`      | `unresolvable` when `unresolved_reason` is set.                  |
| `items[].reason`           | Names the conflicting groups for a multi-book torrent.           |
| `items[].client_actions`   | Unchanged; `setLocation` marks a relocated item.                 |

## Placement identity

An item is already handled when every source file has a counterpart in the
destination directory with the same content: same size first, then BLAKE2b.
The counterpart does **not** need the source's name, so a file renamed by
`trovium-rename` still counts.

## Rename rules

| Record state                   | Rename default                 |
| ------------------------------ | ------------------------------ |
| explicit `move`, no relocation | rename                         |
| explicit `move`, relocated     | skip with the seeding reason   |
| `copy` or `hardlink`           | rename                         |
| `auto` (any effective mode)    | rename, except relocated items |
| `--allow-unsafe`               | rename even when relocated     |

Rename never overwrites; a same-name, different-content target stays a
collision.

## Sidecars and grouping

- A disk entry keeps using `profile.groups()`.
- A client entry now also uses `profile.groups()`.
- Exactly one group → one candidate carrying the group's files and sidecars.
- More than one group → one candidate with `unresolved_reason` naming the
  groups; nothing is placed and the client is untouched.
