# Contract: Ingest and Rename Records

**Feature**: `007-ebooks-full-pipeline`

## Ingest / run record

No schema version change. The existing fields gain values, and one item field is
added.

```json
{
  "source": "run",
  "profile": "books",
  "mode": "auto",
  "ingest": {
    "declared": { "mode": "auto" },
    "items": [
      {
        "name": "Some.Book.Release",
        "disposition": "ingested",
        "destination": "/library/Books/Jane Doe/Some Book (2020)",
        "actions": [
          {
            "op": "hardlink",
            "source": "…/Some.Book.epub",
            "destination": "…/Some.Book.epub"
          },
          {
            "op": "hardlink",
            "source": "…/metadata.opf",
            "destination": "…/metadata.opf"
          }
        ]
      }
    ]
  },
  "rename": { "items": [{ "disposition": "renamed" }] },
  "rename_skipped": null
}
```

### Rules

- `declared.mode` is one of `auto`, `move`, `copy`, `hardlink`.
- `items[].actions[].op` is the effective operation: `hardlink` for a hardlink,
  `copy`, or `move` (plus `delete` for the move cleanup of an already-handled
  item).
- A hardlink that the filesystem refuses is a `copy` action whose reason says
  `hardlink unavailable…; copied instead`.
- `items[].disposition` is `unresolvable` when a client entry expands to more
  than one group; `items[].reason` names the groups and no placement action is
  present.
- `items[].client_actions` keeps its meaning: `setLocation` marks a relocated
  item.

## Rename input

`trovium-rename` reads a record and decides per item.

| Item state                                    | Result                               |
| --------------------------------------------- | ------------------------------------ |
| no `setLocation` in `client_actions`          | rename (any declared mode)           |
| `setLocation` present                         | skip with the seeding reason         |
| `setLocation` present and `--allow-unsafe`    | rename                               |
| target name already taken by other content    | collision error; nothing overwritten |
| target name already taken by the same content | no-op, already renamed               |

## Rerun

A second ingest of the same source after a rename reports `already_handled`
(`identical content already in the library`) and writes no file. Content
identity is size plus digest within the destination directory; the file name is
not part of the comparison.
