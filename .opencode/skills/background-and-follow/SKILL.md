---
name: Background And Follow
description: Use when a test or gate run required by the spec-gates extension will take longer than ~20 seconds. Covers scripts/check.sh, .specify/gates/verify.sh, the pre-commit hook that invokes them, and the CI gate run. Start it with the shell tool's background mode, then immediately follow its log or output path until completion. Prevents buffered wrapper output from being mistaken for a result. Do not use for targeted tests, file-scoped lints, builds, Docker checks, or commands that need interactive input.
compatibility: Requires background command execution and a log or output path.
---

# Background And Follow

The spec-gates extension runs the same test and gate suite locally, at the
git boundary, and in CI. Those runs must stay visible. A gate is not
"running in the background" until a live follower is attached to its log or
output.

## When to use

Use this skill only for the test and gate runs the spec-gates extension
requires:

- `scripts/check.sh`, the `verify-quality` gate at every boundary
- `.specify/gates/verify.sh` (also reached through `/speckit.gates.verify`)
- pre-commit hooks, including a plain `git commit`
- `gh run watch` / `gh pr checks --watch` while a gate-bearing pipeline runs

Do not use it for one targeted test, a file-scoped lint, a standalone
`uv run pytest`, release builds, Docker checks, or anything else that
finishes in a few seconds. Never background a command that needs interactive
input.

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
| `gh run watch` / `gh pr checks --watch`   | its own stream                                                     |

For a local gate, follow the gate log:

```bash
bash .opencode/skills/background-and-follow/scripts/follow-log.sh \
  "${TMPDIR:-/tmp}/trovium-gate.log" \
  '(==> gate (passed|failed)|<== .* failed)'
```

For an arbitrary output file, pass that path and a completion pattern the
command actually prints. Do not wrap a command that already reports its own
completion: `gh run watch <id> --interval 20 --exit-status` exits when the run
finishes, and `gh pr checks --watch` prints only a check table with no summary
line, so run it directly and read its exit code instead of following it with
`follow-log.sh`.

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
