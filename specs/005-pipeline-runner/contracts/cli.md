# CLI Contract: `trovium-run`

**Feature**: `005-pipeline-runner` | **Date**: 2026-10-22

`trovium-run` is the configured ingest -> rename pipeline. It accepts the
ingest options and emits one combined JSON record.

## Usage

```text
trovium-run [--source PATH | --client-url URL]
            [--library-root PATH]
            [--config PATH]
            [--profile NAME]
            [--category VALUE]
            [--mode {move,copy,hardlink}]
            [--post-ingest {keep,pause,delete}]
            [--dry-run]
            [--on-fail {stop,continue}]
            [--json {compact,pretty}]
            [--skip-rename]
            [--allow-unsafe]
```

All ingest options keep their meaning and defaults. Two additions:

| Option           | Default | Notes                                                                             |
| ---------------- | ------- | --------------------------------------------------------------------------------- |
| `--skip-rename`  | off     | Run ingest only; leave the placed names unchanged                                 |
| `--allow-unsafe` | off     | Pass `--allow-unsafe` to rename; permits copy/hardlink and client-relocated items |

## Behavior

1. Resolve options exactly as `trovium-ingest` does (flags, environment,
   config, defaults).
2. Run ingest.
3. Run rename when the ingest mode is `move`, the run is not a dry-run, and
   `--skip-rename` is not set. `--allow-unsafe` is passed through.
4. Skip rename with a reason when:
   - `--skip-rename` is set;
   - the run is a dry-run (the files are not placed);
   - the mode is copy/hardlink and `--allow-unsafe` is not set.
5. Emit the combined record on stdout.

A run-level client failure exits `3` and does not attempt rename.

## Exit codes

| Code | Meaning                                                       |
| ---- | ------------------------------------------------------------- |
| `0`  | Run completed; per-item outcomes are in `ingest` and `rename` |
| `2`  | Misuse (same refusals as ingest)                              |
| `3`  | Run-level client failure; no rename attempted                 |

## Examples

```sh
# books, one command
trovium-run --profile books --source ~/Books/incoming --library-root ~/Media

# configured pipeline, suitable for cron/systemd
trovium-run --config ~/.config/trovium/config.ini

# inspect without placing or renaming
trovium-run --config ~/.config/trovium/config.ini --dry-run
```
