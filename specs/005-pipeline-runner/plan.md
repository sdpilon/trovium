# Implementation Plan: Pipeline Runner

**Feature**: `005-pipeline-runner` | **Date**: 2026-10-22

## Summary

Add `trovium-run`, a thin orchestrator over the existing ingest and rename
engines. It accepts the ingest options, runs ingest, then runs rename when the
record is move-mode and the run is real. It emits one combined JSON record.

The runner holds no domain logic. Classification, placement, naming, and
conflicts stay in the steps.

## Architecture

```text
config / CLI -> cli.resolve_options
                     |
                     v
              cli.run_resolved -> RunSummary
                     |
                     v
        move mode and not dry-run? -> rename.rename_items
                     |
                     v
        {source: "run", ingest, rename, rename_skipped}
```

### `cli` refactor

Extract the run half of `cli.main` into a reusable function:

```python
def run_resolved(*, resolved: ResolvedOptions, dry_run: bool) -> RunSummary: ...
```

It raises `AdapterError` for the runner and `main` to map to exit 3. No
behavior change to the CLI.

### Runner

`src/trovium/run.py`:

- Builds on `cli.build_parser()`; adds `--skip-rename` and `--allow-unsafe`.
- Resolves options exactly as ingest does, including config/environment
  precedence.
- Runs ingest.
- Rename conditions:
  - `--skip-rename` -> skip.
  - `dry_run` -> skip (files are not placed).
  - mode is not `move` and not `--allow-unsafe` -> skip.
  - otherwise
    `rename.rename_items(ingest.to_json(), profile, dry_run=False,
allow_unsafe=..., on_fail=...)`.
- Combined record:

  ```json
  {
    "source": "run",
    "dry_run": false,
    "profile": "books",
    "library_root": "/media",
    "ingest": {"...": "..."},
    "rename": {"...": "..."} | null,
    "rename_skipped": "reason" | null
  }
  ```

- JSON formatting follows `--json`.
- Exit codes mirror ingest: 0 completed, 2 misuse, 3 client failure.
- `AdapterError` from login/run -> no rename, exit 3.

### Console script and deployment

- `pyproject.toml`: `trovium-run = "trovium.run:main"`.
- Update the deployment tests that pin the installed command list to include
  `trovium-run`; the installer discovers it from the wheel.
- Clear the local bundle cache when validating so the fresh wheel is used.

## Risks and mitigations

| Risk                                   | Mitigation                                                                                          |
| -------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Runner duplicates step logic           | It calls `cli.run_resolved` and `rename.rename_items`; no classification/placement code in `run.py` |
| Dry-run tries to rename unplaced files | Dry-run always skips rename with a reason                                                           |
| Copy/hardlink run breaks seeding       | Default skip; `--allow-unsafe` pass-through                                                         |
| Client failure still renames           | Rename is only reached after a successful ingest summary                                            |
| New script breaks deploy tests         | Update the expected command list and rebuild the local bundle cache                                 |

## Testing

- Unit: skip reasons, combined record shape, `--skip-rename`,
  `--allow-unsafe` pass-through, exit 3 mapping.
- Integration: books and video through `run.main`; dry-run changes nothing;
  copy-mode skips rename; config-driven run.
- Acceptance: books, video, dry-run, copy-mode skip, client failure,
  deployment command set.
