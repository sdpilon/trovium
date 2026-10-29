# Contract: Configuration and CLI

**Feature**: `007-ebooks-full-pipeline`

## `trovium-deploy install`

| Flag        | Required | Value                   | Behavior                                        |
| ----------- | -------- | ----------------------- | ----------------------------------------------- |
| `--profile` | no       | registered profile name | Written to `[ingest] profile`; default `video`. |
| other flags | —        | —                       | Unchanged from specification 002.               |

- An unknown profile fails with `config_invalid`, names the registered
  profiles, and writes no configuration.
- An existing configuration is retained on upgrade, including its profile and
  mode; `--profile` is ignored with the existing "existing config retained"
  warning when the config already exists and differs.
- The generated `[ingest] mode` is `auto`.

## `install.sh`

| Flag        | Forwarded to             |
| ----------- | ------------------------ |
| `--profile` | `trovium-deploy install` |

`--profile` is a mode option: it is accepted with the install mode and refused
with `--status` or `--uninstall`, like the other config flags.

## Configuration file (schema 1, additive)

```ini
[ingest]
profile = books
mode = auto
```

| Key       | Default for a new config | Accepted values                    |
| --------- | ------------------------ | ---------------------------------- |
| `profile` | `video`                  | any registered profile             |
| `mode`    | `auto`                   | `auto`, `move`, `copy`, `hardlink` |

Existing schema-1 files remain valid. `mode = auto` was not accepted by earlier
releases; upgrading is one-way until the new release is installed.

## `trovium-ingest` / `trovium-run`

| Flag     | New value | Effect                                                                |
| -------- | --------- | --------------------------------------------------------------------- |
| `--mode` | `auto`    | Resolve the effective mode per candidate (see the data model matrix). |

Precedence is unchanged: CLI flag, then config, then the built-in default
(`auto`).

## Dry run

`--dry-run` resolves `auto` before planning, so the reported operations and
reasons match a real run. `declared.mode` remains `auto`; actions carry the
effective operation.
