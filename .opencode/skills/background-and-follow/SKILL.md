---
name: Background And Follow
description: ALWAYS use when a command may take longer than ~20 seconds or is run in the background. Start it with the shell tool's background mode, then immediately follow its log or output path until completion. Covers scripts/check.sh, .specify/gates/verify.sh, pre-commit gate runs, full pytest, release bundle builds, Docker checks, and gh run watch. Prevents buffered wrapper output from being mistaken for a result. Do not use for fast read-only commands or commands that need interactive input.
compatibility: Requires background command execution and a log or output path.
---

# Background And Follow

Long commands must stay visible. A command is not "running in the
background" until a live follower is attached to its log or output.

## When to use

Use this skill for jobs that take more than roughly 20 seconds or whose
duration is unknown:

- `scripts/check.sh` and `.specify/gates/verify.sh`
- pre-commit hooks, including `git commit`
- the full `pytest` suite and deployment integration suites
- `tools/release/build_bundle.py`, especially `--locked`
- Docker verification runs
- `gh run watch`, `gh pr checks --watch`, and other CI waits

Do not use it for status checks, one targeted test, a file-scoped lint, or
anything else that finishes in a few seconds. Never background a command that
needs interactive input.

## The rule

1. Start the long command in the background. Do **not** append `| tail`,
   `| head`, or another buffering pipe.
2. Record the shell ID and the output path the tool returns.
3. Immediately start one follower for the log or output path. Do not sleep,
   do not take repeated snapshots, and do not end the turn with the job
   unmonitored.
4. Read the final status from the log, not from a buffered wrapper stream.
5. If the follower times out while the job is still running, report that it
   is still running with the log path. Never report pass or fail from a
   partial log.

## Repo log map

| Command                                   | Live source                                                        |
| ----------------------------------------- | ------------------------------------------------------------------ |
| `scripts/check.sh`                        | `${TMPDIR:-/tmp}/trovium-gate.log` (truncated at start)            |
| `.specify/gates/verify.sh --boundary ...` | gate log for `custom`, then the command output for `spec`/`parity` |
| `git commit` (pre-commit)                 | gate log; the hook runs `verify.sh`                                |
| Full `pytest`                             | the background output path                                         |
| `gh run watch` / `gh pr checks --watch`   | its own stream                                                     |
| `build_bundle.py --locked`, Docker runs   | the background output path                                         |

For a local gate, follow the gate log:

```bash
bash .opencode/skills/background-and-follow/scripts/follow-log.sh \
  "${TMPDIR:-/tmp}/trovium-gate.log" \
  '(==> gate (passed|failed)|<== .* failed)'
```

For an arbitrary output file, pass that path and its completion pattern. For
CI, `gh run watch <id> --interval 20 --exit-status` already exits when the run
completes.

## Why not `tail -f | awk`

`tail -f "$log" | awk '... exit'` does not reliably exit. `awk` exits when it
matches, but `tail` stays blocked waiting for another line, and the shell waits
for the whole pipeline. The follower can outlive the gate indefinitely.

`follow-log.sh` avoids this by streaming through a FIFO and killing its `tail`
child on exit. If a follower is run in the background, it must terminate on
its own when the pattern matches.

## Failure handling

- A red gate is a red gate: read the failing phase and its output, not just
  the exit code.
- If the wrapper output is truncated or buffered, use the underlying log.
- If the monitor itself hangs, kill it and report the log path instead of
  leaving an orphan process.
- Do not start a second full gate while one is running.

## Checklist

- [ ] The command is in the background.
- [ ] No `| tail` or `| head` on the backgrounded command.
- [ ] A follower is running against the log or output path.
- [ ] The follower exits when the job finishes.
- [ ] Final status came from the log, not a buffered wrapper.
- [ ] No orphan `tail`, `gh run watch`, or monitor process remains.
