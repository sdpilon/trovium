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

Run the offline proof (15 cases) from the project root:

```sh
bun .opencode/plugins/gates/prove.ts
```

It covers `.env`/`credentials.json` blocks, `rm -rf /` and `git push --force`
blocks, `git push --delete` / `git commit --no-verify` asks, allows, a
`hooks.local.d` rule, a hook that exits 1 surfacing as an ask, the bash-3.2
interpreter still blocking, and the not-projected-inert case. The local-rule
and broken-hook cases run in temporary copies, so they never touch the
checkout's own hooks.

## Resolved upstream: the bash 3.2 silent-allow bug

The adapter was written against spec-gates 0.3.x, where `validate-bash.sh`
wrapped `grep`/`sed`/`tr`/`awk` in shell functions and tested them as
`if grep …; then`. On macOS's `/bin/bash` 3.2, `set -e` was not suppressed
inside a function body called as an `if` condition (fixed in later bash), so
the hook exited 1 the moment a rule did not match, before printing any block.
Claude Code read that as a non-blocking error and ran the command.

spec-gates 0.4.0 rewrote the file and command hooks so they never silently
allow (#83): a non-match falls through, undecidable input becomes a PreToolUse
`ask`, and a missing `grep`/`sed`/`tr`/`awk` is named instead of allowed. The
projected 0.4.1 validator now blocks under macOS's 3.2.57:

```sh
$ printf '%s' '{"tool_input":{"command":"rm -rf /"}}' | CLAUDE_PROJECT_DIR=… /bin/bash .claude/hooks/gates/validate-bash.sh ; echo $?
BLOCKED: Destructive rm command targeting root, home, or wildcard
2
```

`resolveBash()` still prefers a `bash >= 4` (`$GATES_BASH`, `bash` on `PATH`,
Homebrew paths), and `prove.ts` pins `/bin/bash` as a regression case, so a
future 3.2 regression fails the proof rather than passing silently. If only
bash 3.2 is available, a broken hook surfaces as an **ask**, never an allow.

## Canary status

`bash .specify/gates/canary.sh` reports 16 run, 16 blocked, 0 accepted,
0 skipped on macOS and in CI. The `bash`, `bulk` and `local` canaries that
this README once listed as accepted now block: they probe the same
`validate-bash.sh` script the adapter spawns, so the canary suite and the
OpenCode boundary share one chokepoint instead of two implementations. The
canaries still run the hook through its shebang (the Claude projection);
`prove.ts` covers the adapter's translation layer.

## The real conversion gaps

1. **`Stop` "refuse to end the turn" (`verify-quality.sh`, `format-changed.sh`).**
   Claude Code's `Stop` hook can veto the end of a turn, and that is how XXII
   (Stop Hook Discipline) is enforced at the agent boundary. OpenCode has no
   block-before-stop seam: the closest is `ctx.event.subscribe` on idle plus
   re-driving the session (`ctx.session.synthetic` / prompt), which starts
   another turn instead of refusing the stop. Until that is designed, XXII
   holds at the git and CI boundaries (pre-commit, `gates.yml`) but not at the
   moment an OpenCode turn ends. `doctor.sh` still reports it as enforced
   because the projection declares `verify-quality.sh`; this is the fidelity
   gap, and it is why the PoC stops at the two PreToolUse-style gates.
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
