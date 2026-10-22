# Config Schema Addendum: `[ingest] profile`

**Feature**: `003-media-profiles-books` | **Date**: 2026-10-21

This extends `specs/002-server-deployment/contracts/config-schema.md`. The
schema version stays `1`: `profile` is optional and the default preserves
every existing configuration.

## `[ingest]`

| Key           | Type   | Required | Default    | Notes                                    |
| ------------- | ------ | -------- | ---------- | ---------------------------------------- |
| `profile`     | string | no       | `video`    | a registered profile name                |
| `category`    | string | no       | `all`      | one of the selected profile's categories |
| `mode`        | enum   | no       | `move`     | unchanged                                |
| `post_ingest` | enum   | no       | `keep`     | unchanged                                |
| `on_fail`     | enum   | no       | `continue` | unchanged                                |
| `json`        | enum   | no       | `pretty`   | unchanged                                |

Validation order: resolve `profile` first, then validate `category` against
that profile. An unknown profile or an out-of-profile category is a
`ConfigError` naming the allowed values.

## Examples

Existing video configuration, unchanged:

```ini
[ingest]
category = movie
mode = move
```

Equivalent explicit video configuration:

```ini
[ingest]
profile = video
category = movie
```

Books:

```ini
[ingest]
profile = books
category = all
mode = copy
```

The generated default configuration now writes `profile = video` and
`category = all` so the new key is discoverable.
