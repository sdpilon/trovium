# spec-gates → OpenCode adapter (proof of concept)

Bridges the [spec-gates](https://github.com/schwichtgit/spec-gates) extension's
Claude Code hook boundary onto OpenCode's plugin/permission API, without
modifying the gate scripts.

Status: **proof of concept**. `protect-files` (edits) and `validate-bash`
(shell) are wired and verified live. The remaining hooks are mapped below but
not yet ported.

> **A staged upstream contribution, not trovium's own tooling.** The adapter
> bridges the spec-gates extension onto OpenCode and belongs upstream as an
> OpenCode projection target (a sibling to the existing `claude` target — see
> _Layout_). It lives in this repo only because trovium is its first consumer;
> the intended end state is a thin, generated projection. It depends on
> spec-gates internals (the hook scripts, the `.specify/gates/lib` runtime, the
> exit-code/ask-JSON contract), so drift with spec-gates is the expected failure
> mode, not an edge case.

## How it works

The whole adapter is one OpenCode **permission `evaluate` hook** plus a pure
core:

| File       | Role                                                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------------------------------------- |
| `gates.ts` | Agent-agnostic core: run a gate script, translate its result into a decision. No OpenCode import, so it is unit-testable. |
| `index.ts` | OpenCode binding: `ctx.permission.hook("evaluate")`. Loads automatically from `.opencode/plugins/`.                       |
| `prove.ts` | Runs the core against the **real** projected scripts and asserts block/ask/allow.                                         |

OpenCode evaluates a permission decision for every tool call and hands the hook
the tool's **action** and **resources**. We map those to the gate scripts the
Claude Code wiring would have run:

| OpenCode action                | Resources                          | Gate script        |
| ------------------------------ | ---------------------------------- | ------------------ |
| `shell`                        | scanner-produced command string(s) | `validate-bash.sh` |
| `edit` (also `write`, `patch`) | target path(s)                     | `protect-files.sh` |

The hook then translates the gate's result back into OpenCode's vocabulary:

| Gate script result                           | Decision  | Adapter does                                                                             |
| -------------------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| exit 2, `BLOCKED: …` (stderr)                | **block** | `event.effect = "deny"`, `event.message = "gates: …"` (the reason is shown to the model) |
| exit 0, ask JSON on stdout                   | **ask**   | `event.effect = "ask"`, `event.message = "gates: …"`                                     |
| exit 0, no output                            | **allow** | leave the decision untouched                                                             |
| any other exit (e.g. the bash 3.2 bug below) | **ask**   | never a silent allow                                                                     |
| script not projected                         | **allow** | inert — there is no policy to enforce                                                    |

Why `permission.evaluate` and not `ctx.tool.hook("execute.before")`? The tool
hook is documented as "inspect or **replace** input" with no reject API; the
permission hook is OpenCode's documented block/ask mechanism, so it maps 1:1
onto gates' exit codes.

## Proven live

Adding the plugin needed **no restart** — OpenCode hot-loaded it. The adapter's
own log (`.specify/gates/opencode-adapter.log`) records:

```text
adapter loaded (bash=bash, hooks=…/.claude/hooks/gates)
DENY  edit  [".specify/gates/policy.json"]               :: Gates policy (a human edits it; the commit needs a Protected-Change trailer)
ASK   shell ["GATES_SKIP=1 echo gates-poc-live-ask-ok"]  :: gates: this command sets GATES_SKIP, which weakens what the gates enforce; confirm it
```

- The **DENY** line: editing the protected policy was rejected, and the reason
  was surfaced to the model.
- The **ASK** line: a `GATES_SKIP=1 …` command raised an ask; on approval the
  command ran.

Run the offline proof (14 cases) from the project root:

```sh
bun .opencode/plugins/gates/prove.ts
```

It covers `.env`/`credentials.json` blocks, `rm -rf /` and `git push --force`
blocks, `git push --delete` / `git commit --no-verify` asks, allows, a
`hooks.local.d` rule, the bash-3.2 regression, and the not-projected-inert
case. The local-rule case runs in a temporary copy of the projected hooks, so
it never touches the checkout's own `hooks.local.d`.

## Bug found: `validate-bash.sh` is defeated on macOS's default bash (3.2)

The bundled canary suite flags the agent boundary as broken on stock macOS, and
it is right. `validate-bash.sh` wraps `grep`/`sed`/`tr`/`awk` in shell functions
(lines 70–73) and tests them as `if grep …; then`. In **bash 3.2** — which is
`/bin/bash` on macOS, and gates' hook shebang is `#!/bin/bash` — `set -e` is
**not** suppressed inside a function body called as an `if` condition (fixed in
later bash). So the hook exits 1 the moment a rule does not match, _before_ it
prints any block:

```sh
$ printf '%s' '{"tool_input":{"command":"rm -rf /"}}' | CLAUDE_PROJECT_DIR=… /bin/bash .claude/hooks/gates/validate-bash.sh ; echo $?
1                          # silent: Claude Code sees a non-blocking error and RUNS the command
$ … | CLAUDE_PROJECT_DIR=… /opt/homebrew/bin/bash .claude/hooks/gates/validate-bash.sh ; echo $?
BLOCKED: Destructive rm command targeting root, home, or wildcard
2
```

Minimal repro:

```sh
/bin/bash -c 'set -euo pipefail; grep() { command grep "$@"; }; if grep -qE zzz <<<hello; then :; fi; echo reached'
# bash 3.2 prints nothing (exit 1); bash >=4 prints "reached"
```

`protect-files.sh` is unaffected (it exits 2 before hitting a non-matching
`if grep`). The git hooks are usually fine because the stub `exec bash`s the
projected hook (`exec bash "$hook"`), picking up whatever `bash` is on `PATH`.

**Implications.** On a machine whose `PATH` bash is 3.2, spec-gates'
`validate-bash` agent hook silently allows every command and the canary reports
it as a broken gate. The extension's own docs describe bash 3.2 support as a
goal, so this is an upstream bug worth reporting.

**What this adapter does about it.** `resolveBash()` prefers a `bash >= 4` on
`PATH` (or `$GATES_BASH` / Homebrew paths) so the scripts run on a healthy
interpreter. If only bash 3.2 is available, the broken hook surfaces as an
**ask** rather than a silent allow.

## Canary status on macOS

`bash .specify/gates/canary.sh --only bash,bulk,local` still reports three
accepted canaries on a stock macOS host. That is the bug above, measured
through the Claude projection: the canary runs the projected hook by path, so
its `#!/bin/bash` selects 3.2. The live OpenCode boundary is not affected:
`resolveBash()` selects a bash >= 4, and `prove.ts` shows the same `rm -rf /`,
`git add -A`, and `hooks.local.d` probes blocking through the adapter. The
canary suite remains the signal for the Claude projection; the proof harness is
the signal for this adapter.

## The real conversion gaps

1. **`Stop` "refuse to end the turn" (`verify-quality.sh`, `format-changed.sh`).**
   Claude Code's `Stop` hook can block the end of a turn; OpenCode has no 1:1.
   The closest seam is `ctx.event.subscribe` on idle plus re-driving the session
   (`ctx.session.synthetic` / prompt). Not attempted here — this is the one piece
   that needs real design work, and it is why the PoC stops at the two
   PreToolUse-style gates.
2. **`ask` routing.** Handled: gates' ask-JSON becomes OpenCode's permission
   `ask` effect rather than being passed through.
3. **Fidelity of the `shell` resource.** OpenCode hands the permission hook the
   _scanner-produced_ command string (compound commands may split into several
   resources). That is usually equal to the raw command, but if exact raw text
   matters, capture it in `ctx.tool.hook("execute.before")` and correlate.
4. **`post-edit` auto-format** (`post-edit.sh` → `format-changed.sh`) maps to
   `ctx.tool.hook("execute.after")`; not wired yet.

## Layout / dependencies

- The hook scripts are read from `.claude/hooks/gates/*.sh` — where `project.sh`
  projects the Claude-shaped scripts. A cleaner upstream design would add an
  `opencode` projection target so they live under `.specify/gates/hooks/opencode/`.
  The `.claude/` copies are harmless; only the OpenCode plugin actually runs.
- Reuses the agent-agnostic core (`.specify/gates/lib/*.sh`, policy) unchanged.
- Needs `jq`, `git`, `python3`, `cmp`, and a `bash >= 4` (see above).

## Turning gates on / off

- **On:** the plugin auto-loads whenever `.opencode/plugins/gates/` exists and
  `.claude/hooks/gates/` is projected.
- **Off:** delete/rename `.opencode/plugins/gates/`, or remove the projection.
- `git.block_bulk_staging` (refuse `git add -A`/`.`/directories) is **enabled**
  in `.specify/gates/policy.json`, so bulk staging is refused at the agent
  boundary. It is off in the freshly inferred policy; because
  `protect-files.sh` guards the policy as human-owned, a human turns it on (or
  approves a permission ask that does).
