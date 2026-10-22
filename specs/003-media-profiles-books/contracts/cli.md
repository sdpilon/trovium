# CLI Contract: profile-aware `trovium-ingest`

**Feature**: `003-media-profiles-books` | **Date**: 2026-10-21

This extends `specs/001-ingest-vertical-slice/contracts/cli.md`. Every existing
option keeps its meaning; `--profile` selects the media type and makes
`--category` profile-dependent.

## Usage

```text
trovium-ingest (--client-url URL | --source PATH)
               --library-root PATH
               [--profile NAME]
               [--category VALUE]
               [--mode {move,copy,hardlink}]
               [--post-ingest {keep,pause,delete}]
               [--dry-run]
               [--on-fail {stop,continue}]
               [--json {compact,pretty}]
```

## Options

| Option           | Required                            | Default                         | Notes                                    |
| ---------------- | ----------------------------------- | ------------------------------- | ---------------------------------------- |
| `--profile`      | no                                  | `video` (or `[ingest] profile`) | registered profile name                  |
| `--category`     | no                                  | `all`                           | one of the selected profile's categories |
| `--client-url`   | one of `--client-url` or `--source` | env `TROVIUM_CLIENT_URL`        | unchanged                                |
| `--source`       | as above                            | —                               | unchanged                                |
| `--library-root` | required                            | —                               | unchanged                                |
| `--mode`         | no                                  | `move`                          | unchanged                                |
| `--post-ingest`  | no                                  | `keep`                          | client mode only; unchanged              |
| `--dry-run`      | no                                  | off                             | unchanged                                |
| `--on-fail`      | no                                  | `continue`                      | unchanged                                |
| `--json`         | no                                  | `pretty`                        | unchanged                                |

Category values:

- `video`: `movie`, `tv`, `all`
- `books`: `book`, `all`

## Misuse refusals

In addition to the existing refusals:

- Unknown `--profile`: exit 2 and list the registered profiles.
- A `--category` that the selected profile does not define: exit 2 and list
  the allowed values.

## Examples

```sh
# video, unchanged
trovium-ingest --source ~/Downloads --library-root ~/Media

# ebooks
trovium-ingest --profile books --source ~/Books/incoming --library-root ~/Library

# books, inspect only
trovium-ingest --profile books --source ~/Books/incoming \
  --library-root ~/Library --dry-run
```
