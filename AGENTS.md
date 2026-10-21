# AGENTS.md

Instructions for agents working in trovium.

## What this is

Python ≥3.13, uv-managed collection of **single-purpose CLI tools** replacing
the *arr media-automation stack. Two commands ship today: `trovium-ingest`
(classify and place media from a download client or a directory) and
`trovium-deploy` (install, upgrade, inspect, and uninstall trovium itself).
Steps exchange plain files/JSON over stdin/stdout; no shared database, no
hidden state (constitution principles XXV–XXVII in
`.specify/memory/constitution.md` — read it before feature work).

Feature work runs through the spec-kit flow: `/speckit.specify → /speckit.plan
→ /speckit.tasks → /speckit.implement` (commands live in
`.opencode/commands/speckit.*.md`; specs in `specs/NNN-slug/`, one branch per
feature). Implementation does not start without an agreed spec (XXIV).
Personal overrides go in `AGENTS.local.md` (gitignored).

## Commands

```sh
uv sync                 # first: prepare the environment (uv only; no pip/system installs)
npm ci                  # once: pinned prettier/markdownlint-cli2 for the gate
scripts/check.sh        # THE canonical check: ruff lint+format, mypy strict, pytest, prettier, markdownlint, shellcheck
uv run pytest tests/integration/test_client_ingest.py   # one test file
uv run pytest -k "single_file"          # one test by name
uv run pytest -n 0 tests/unit/test_library.py   # serial, for debugging (default is -n auto)
uv run ruff check --fix . && uv run ruff format .       # lint autofix + format
uv run mypy .           # `mypy .` is accepted and covers src/ + tests/ + tools/
```

`scripts/check.sh` is the one quality gate: local runs, the git pre-commit
hook, and CI all reach it through `.specify/gates/verify.sh --boundary
agent|git|ci`, and CI also runs a canary suite proving the gate still blocks.
Never declare work finished with it red (XXII). Gate tooling is version-pinned
(`.tool-versions`, `package-lock.json`); use the pinned binaries rather than
global substitutes.

Long-running commands must be started in the background and followed live.
For the spec-gates test and gate runs (`scripts/check.sh`, `verify.sh`,
pre-commit hooks, CI gate watches), use
`.opencode/skills/background-and-follow/SKILL.md`.

## Rules that gate you (they will refuse, not warn)

- **No direct commits to `main`** — the pre-commit hook blocks the branch,
  merge commits included (II). Feature branches `NNN-slug`, squash-merged
  through PRs. `GATES_ALLOW_MAIN_COMMIT=1` is the release override and raises
  an approval prompt at the agent boundary.
- **Conventional Commits**: `type(scope): description`; subjects over 72
  characters warn. Emoji, `Co-Authored-By:` trailers, self-referential
  language ("I added …"), marketing adjectives ("seamless", "robust", …),
  AI filler ("As an AI", "Happy to help"), and AI branding (Anthropic, GPT,
  OpenAI, Copilot, standalone "Claude", agent attribution lines) are errors
  in commit and PR text (III). Pre-commit also scans staged files for secrets
  and forbidden paths.
- **Protected paths**: `.specify/gates/policy.json`,
  `.specify/gates/hooks.local.d/**`, and the policy-contract artifacts
  (`baseline.json`, `baseline.lock.json`, `policy.effective.json`) refuse
  edits; `.specify/memory/constitution.md` is ask-gated (VIII/IX). Commits
  touching a protected path need a `Protected-Change: <path>` trailer per path
  plus `Approved-By: <name>`; declarations in a PR description count for every
  commit (a squash merge keeps the description, not the trailers).
- **Stage explicit paths**: `git add .`, `-A`/`--all`, and whole-directory
  stages are blocked (policy `git.block_bulk_staging`); `git add -u`, `-p`,
  and named files are fine.
- **Destructive commands are blocked**: `git push --force`,
  `git reset --hard`, `git clean -f`, `git checkout .`/`git restore .`,
  `chmod 777`, `rm` of root/home/absolute paths outside temp directories,
  and piping remote content to a shell. Hook bypasses (`--no-verify`,
  `HUSKY=0`, `SKIP=`, `core.hooksPath`) and remote-branch deletes ask
  instead of block.
- **Secret files** (`.env*`, keys, certificates, credential stores) are
  blocked to edit and to commit; lock files (`package-lock.json`, `yarn.lock`,
  `pnpm-lock.yaml`, `Cargo.lock`, `poetry.lock`) are blocked to edit.
- **One runtime dependency**: `httpx` only. `tests/unit/test_dependency_budget.py`
  fails CI on any addition — changing the budget means amending spec/plan
  first, not the pyproject alone.
- **Do not weaken the gates**: setting `GATES_SKIP`, `GATES_POLICY_FILE`,
  `GATES_ALLOW_MAIN_COMMIT`, `GATES_RUNTIME_DIR`, `GATES_TEST`, or
  `GATES_SPEC_EXEC` raises an approval prompt.
- **PR titles/descriptions** pass the same message rules as commits; CI runs
  `pr-check.sh` over the PR range (text, protected changes, secrets) using the
  base revision's rules, so a PR cannot replace the code that judges it.
- **Spec gate acceptance**: encode each success criterion as a fenced `accept`
  block under a task in `tasks.md`, labelled `# verifies: SC-xxx` and driving
  the shipped CLI rather than internals. Blocks are enforced only when
  `spec.md` says exactly `**Status**: Complete` (or `verify.sh --accept` asks
  for an incomplete feature); other statuses are informational. Malformed
  blocks fail closed, and a Complete feature with zero blocks has nothing
  executable to enforce.

## Projection / vendored surfaces (do not hand-edit)

- `.specify/**` and `.opencode/commands/speckit.*.md` are projected/generated by
  spec-kit (XX). They are excluded from formatters and linters on purpose;
  regenerate them through `.specify/extensions/gates/runtime/project.sh` or the
  `/speckit.gates.*` commands, never by patching files.
- `.specify/gates/policy.json` is user-owned: seeded once, never overwritten by
  upgrades. A human edits it, and the commit needs the trailer.
- `.opencode/plugins/gates/`, `.opencode/skills/`, and `tools/` are
  hand-written and in scope for linting.

## Testing notes

- Layers: `tests/unit/`, `tests/contract/` (CLI + record contracts pinned in
  `specs/…/contracts/`), `tests/integration/`.
- Real qBittorrent behavior is exercised via `tools/qbt-live-rig/` (Linux-only,
  two local instances + tracker, no root); stub transports live behind
  `httpx.MockTransport`. Never claim live verification
  that only stubs prove.
- Client gotchas (5.x `stop` vs `pause`, `root_path` vs `content_path`, async
  `setLocation` + recheck) are exercised by the rig and pinned in
  `tests/integration/test_client_ingest.py`; the rig README catalogues them.

## CI

- `gates.yml`: `verify.sh --boundary ci`, the canary suite, and `pr-check.sh`
  for PR text, protected changes, and secrets.
- `deploy-linux.yml`: deployment suites, `verify.sh --accept 002-server-deployment`,
  a locked release-bundle build, an offline install, and a musl-host refusal.
- `release.yml`: on `v*` tags, builds and publishes bundles for
  `linux-x86_64` and `linux-aarch64`.
