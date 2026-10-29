# Research: Ebooks Through the Full Pipeline

**Feature**: `007-ebooks-full-pipeline` | **Date**: 2026-10-29

## 1. How to represent the adaptive default

- **Decision**: add `auto` as a fourth placement mode (`Mode.AUTO`). It is
  accepted by `--mode` and `[ingest] mode`, and new installations default to
  it.
- **Rationale**: one value flows through the existing CLI, config, record, and
  validation paths. Operators can still pin `move`, `copy`, or `hardlink`.
- **Alternatives**: a boolean `adaptive = true` (two knobs, ambiguous
  combinations); install-time resolution (cannot know the torrent's filesystem
  relationship at install time).

## 2. Where and how the mode resolves

- **Decision**: a pure `effective_mode(mode, candidate, destination)` helper in
  `placement.py` returns `move`, `copy`, or `hardlink`. `cli.process` computes
  it once per candidate and uses it for planning, applying, and the client
  move guard. Resolution rule:
  - explicit `move` / `copy` / `hardlink` → unchanged;
  - `auto` and the candidate is a seeding client item → `hardlink` when the
    source and the destination's nearest existing ancestor share `st_dev`,
    otherwise `copy`;
  - `auto` and anything else (disk entry, non-seeding client item) → `move`.
- **Rationale**: the rule needs runtime facts (source kind, client state,
  filesystem) that profiles must not know. `placement.py` already owns
  filesystem probes and fallback reasons.
- **Alternatives**: resolve in the profile (leaks client/filesystem concerns
  into media code); resolve in the adapter (violates XXVII and duplicates per
  client).

## 3. Cross-filesystem and refused hardlinks

- **Decision**: keep the existing fallback: an unavailable hardlink becomes a
  copy with a reason (`hardlink unavailable…; copied instead`).
- **Rationale**: the behavior already exists for explicit hardlink mode and is
  covered by tests; the adaptive default should not invent a new failure mode.
- **Alternatives**: fail the item (worse for the default path); silently move
  (breaks seeding).

## 4. Non-seeding client items and the move guard

- **Decision**: `auto` resolves a client item that is not `SEEDING` to `move`.
  The existing move guard applies to **explicitly selected** `move` only, so
  the adaptive path follows the user's rule.
- **Rationale**: the qBittorrent adapter reports every completed torrent as
  seeding, so this branch is currently reachable only through other clients or
  future adapters. When it is reached, the user's explicit policy wins.
- **Tradeoff recorded**: moving a client-tracked folder can leave the client
  pointing at missing files. The refusal for explicit `--mode move` still
  protects that choice; `auto` is the operator's stated policy.
- **Alternatives**: keep the guard for `auto` (would contradict the rule);
  copy non-seeding items (safe but not what was asked).

## 5. Content identity for reruns after a rename

- **Decision**: when the same-name target is absent, `compare_existing` scans
  the destination directory for a file with the same size and digest. A match
  means the item is already handled.
- **Rationale**: the rename step changes the library filename, so a later
  ingest cannot match by name. Content identity is file-based, stateless, and
  keeps the XXV rerun promise without a lookup table or record history.
  Destination directories hold a handful of files; size checks run first.
- **Alternatives**: persist a rename mapping in the record (hidden state
  between steps); compare mtime (fragile across copies); always digest the
  whole directory (cost without benefit).

## 6. Rename safety for copy and hardlink

- **Decision**: remove the `declared.mode is not move` gate in
  `trovium-rename`; keep the client-relocated (`setLocation`) skip and the
  `--allow-unsafe` override. `trovium-run` no longer requires `--allow-unsafe`
  for copy/hardlink.
- **Rationale**: with content identity in place, a rerun after rename is safe.
  Hardlink renaming only changes the library directory entry; the torrent's
  entry stays. Client-relocated items still break when renamed, so that skip
  remains.
- **Alternatives**: special-case `auto` only (same code path, leaves copy/
  hardlink refusing); keep the flag (contradicts the full-pipeline goal).

## 7. Expanding a client entry through the profile

- **Decision**: in `client_candidates`, expand a completed entry through
  `profile.groups()`. Exactly one group becomes the candidate (with sidecars);
  more than one group produces a candidate with an `unresolved_reason` naming
  the groups, which `process` reports as `unresolvable` without placing.
- **Rationale**: client entries are one item per torrent, so a multi-book
  torrent must be refused, not split across client actions. Profiles already
  own grouping; the engine only enforces one-candidate-per-torrent.
- **Alternatives**: keep `collect_files` (drops sidecars); split a torrent into
  several candidates (client update/relocate becomes ambiguous).

## 8. Installer selection

- **Decision**: `trovium-deploy install --profile NAME` (and
  `install.sh --profile NAME`) validate through `get_profile` and write
  `IngestSettings(profile=NAME, mode=AUTO)`. Upgrades keep the existing config,
  as they do today.
- **Rationale**: the profile must be chosen before the first run; the config
  loader already validates `[ingest] profile`.
- **Alternatives**: a separate `trovium config` command (later slice); writing
  a books-only `copy` default (replaced by the adaptive rule).

## 9. Dry-run parity

- **Decision**: the plan resolves `auto` before computing actions, so
  `--dry-run` reports the same `link` / `copy` / `move` operations and reasons
  as a real run. `declared.mode` stays `auto`; the actions carry the effective
  operation.
- **Rationale**: FR-006-style parity is already pinned in 001; adding a mode
  that resolves differently at plan time would regress it.

## 10. Compatibility

- Existing configs keep their explicit modes; only new installs default to
  `auto`. Older binaries reject `mode = auto`; this is pre-alpha and the
  release notes name the new value.
- No record schema version change: `declared.mode` was already a string and the
  action kinds already distinguish move/copy/link.
