# trovium Constitution

## Core Principles

### I. No Secrets

<!-- gates:enforce surface=git-hook ref=pre-commit -->

Secrets never enter the repository, its history, or its logs. Credentials
live in the environment or a secret manager, never in tracked files. A key
that reaches the history is treated as compromised and rotated immediately —
removal from `HEAD` is not remediation.

### II. Branch First

<!-- gates:enforce surface=git-hook ref=pre-commit -->

Every change reaches `main` through a pull request. The git boundary refuses
a direct commit to `main`; the only escape is an explicit, per-commit
override reserved for release automation. Feature branches are cut from
`main` and merged back through review.

### III. Conventional Commits

<!-- gates:enforce surface=git-hook ref=commit-msg -->

Commit subjects follow Conventional Commits with a type from the project's
enumerated set and a subject line of 72 characters or fewer. Emoji,
marketing language, and AI-attribution trailers are refused at the commit-msg
boundary.

### IV. Provable Enforcement

<!-- gates:enforce surface=ci ref=gates -->

Each enforcement class emits evidence of what it checked and ships a canary
that plants a known violation and requires the real entry point to reject it.
A new gate is not done until its canary and attestation surface exist, so a
gate that silently stops gating is caught by a red proof step.

### V. One Policy Many Boundaries

<!-- gates:enforce surface=policy ref=attestation.parity -->

A single policy file is the source of enforcement truth, and the same entry
point runs it at every boundary — local, commit, and CI. Parity is checked on
each run, so the boundaries an actor could rewrite are backstopped by the ones
it cannot, all provably running the same policy.

### VI. Fail Closed

<!-- gates:enforce surface=prose -->

When the enforcement layer meets something it cannot read, parse, or
demonstrably execute, it fails the run and names the cause at `file:line`. A
malformed rule, an unreadable criterion, or a missing tool the policy enables
is an enforcement gap that blocks — it is never reported as a pass.

### VII. Secret Rotation

<!-- gates:enforce surface=prose -->

A credential that appears anywhere it should not — a diff, a log line, a
paste in an issue — is considered compromised. The response is to revoke and
reissue it, then purge the copy. Deletion without rotation is theater.

### VIII. Constitution Immutable

<!-- gates:enforce surface=agent-hook ref=protect-files.sh -->

The constitution is amended only through a reviewed change with explicit
human approval. Automated tooling and agents may propose amendments but may
not apply them; the protected-files boundary refuses edits to the
constitution outside that flow.

### IX. Policy Change Approval

<!-- gates:enforce surface=agent-hook ref=protect-files.sh -->

Changes to the enforcement policy require prior human approval and land as a
reviewed diff. Machine-generated artifacts (specs, plans, tracking files) are
never hand-edited to pass a gate; the input that produced them is corrected
instead.

### X. Worktree Safety

<!-- gates:enforce surface=prose -->

Scripted git operations name their target explicitly with `git -C <abs-path>`
and verify branch and worktree state before writing. No step assumes it is
running in the intended checkout; a wrong assumption here corrupts the wrong
repository silently.

### XI. Rebase Before Pr

<!-- gates:enforce surface=prose -->

Before opening or updating a pull request, the branch is rebased onto the
current `main`. Before resuming work on an existing branch, its merge status
is checked — continuing on an already-merged branch is a common source of
lost or duplicated changes.

### XII. Changed Files Scoped

<!-- gates:enforce surface=ci ref=gates -->

Quality gates evaluate the files a change actually touches. Pre-existing
violations in untouched code are grandfathered and tracked separately, so a
small change is never blocked by debt it did not introduce and the gate stays
worth keeping on.

### XIII. Pre Pr Verification

<!-- gates:enforce surface=git-hook ref=pre-commit -->

The same checks CI runs are run locally and pass before a pull request is
opened. Test plans reflect tests actually executed, not intended. CI exists
to catch environment drift and the occasional escape, never as the first
place a failure is discovered.

### XIV. Fail Loudly

<!-- gates:enforce surface=prose -->

Failures are made visible and traced to their root cause before work
continues. The system does not silently swallow an error, retry into a
degraded state, or present fabricated or placeholder values as if they were
real results.

### XV. Tracking File Immutability

<!-- gates:enforce surface=agent-hook ref=protect-files.sh -->

Files that record generated state — task status, coverage ledgers, readiness
scores — are updated only by the tooling that owns them. Hand-editing a
tracking file to flip a status is prohibited; the underlying work is done so
the tool records the change itself.

### XVI. Fix Regressions First

<!-- gates:enforce surface=prose -->

When a change breaks existing behavior, the regression is fixed before new
work continues. Each fix ships with a regression test that fails against the
pre-fix code, so the same break cannot recur unnoticed.

### XVII. Test Coverage Per Behavior

<!-- gates:enforce surface=prose -->

New behavior is not considered done until it carries automated test coverage,
and each bug fix carries a regression case. Test suites are registered in the
project's canonical runner so coverage is executed, not merely claimed.

### XVIII. Single Chokepoint

<!-- gates:enforce surface=prose -->

Every instance of a cross-cutting concern — data access, auth refresh, output
sanitization — passes through a single function or module. Callers use the
chokepoint or do not perform the operation; there is no second path that
skips the invariant it enforces.

### XIX. Out Of Scope Boundary

<!-- gates:enforce surface=prose -->

The constitution states what this repository deliberately does not own, and
for each excluded concern names the sibling repository or service that does.
A change that would cross one of those boundaries is redirected to its owner
rather than absorbed here.

### XX. Projection Not Dependency

<!-- gates:enforce surface=prose -->

Enforcement and shared tooling are projected — copied — into the repository
rather than symlinked or resolved from an external install. The runtime works
on a fresh clone, offline, and after the tool that installed it is gone;
drift between source and copy is managed explicitly, not wished away.

### XXI. Codeowners Governance

<!-- gates:enforce surface=prose -->

The directories that define how the project is governed — CI configuration,
hook scripts, the enforcement policy, and the specifications — require review
from designated owners. A change that weakens a gate cannot merge on the same
authority as an ordinary code change.

### XXII. Stop Hook Discipline

<!-- gates:enforce surface=agent-hook ref=verify-quality.sh -->

The session-stop boundary refuses to conclude while lint or tests are
failing. Finishing requires a green local run, so a session hands off a clean
tree rather than deferring known failures to the next person or the next
pipeline run.

### XXIII. Spec Is Boundary

<!-- gates:enforce surface=ci ref=gates -->

Enhancements run as numbered specifications through the specify → plan →
tasks → implement flow, and their success criteria land as executable
acceptance checks. A feature marked complete is held to those checks on every
run: an unchecked task or a failing criterion blocks, so completion is proven
rather than declared.

### XXIV. No Coding Before Spec

<!-- gates:enforce surface=prose -->

Implementation does not begin until the feature has an agreed specification
and plan. The workflow is sequential — specify, then plan, then tasks, then
implement — so the design decisions are made and reviewed before code commits
the project to them.

### XXV. Unix single-purpose steps

<!-- gates:enforce surface=prose -->

Each pipeline step is an independent, single-purpose command-line tool.
Steps exchange a stable text or JSON contract over stdin and stdout, so any
step can be run, inspected, and re-run on its own. A step's inputs and
outputs are plain files a person can read, and re-running a step is safe
rather than a hidden state change: no step depends on another's in-memory
state.

### XXVI. Typed Python through uv

<!-- gates:enforce surface=prose -->

trovium is implemented in Python, with static type checking on every public
surface. Formatting, linting, and tests run through `uv` (ruff and pytest) as
a single canonical command, and CI runs that same command, so a green local
run is the same signal as a green pipeline.

### XXVII. One client adapter

<!-- gates:enforce surface=prose -->

Every interaction with a download client passes through one adapter boundary,
not scattered across steps. qBittorrent is the first implementation; adding or
replacing a client is a change in exactly one place, and no pipeline step
talks to a client's API directly.

## Governance

This constitution supersedes other practice documents where they conflict.
Amendments are made by pull request that edits this file, records the change,
and is approved by the project's maintainers. Every review verifies compliance
with the principles above; the enforcement annotations bind each principle to
the boundary that proves it.

**Version**: 1.0.0 | **Ratified**: 2026-10-16 | **Last Amended**: 2026-10-16
