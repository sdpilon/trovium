---
name: PR Review Handoff
description: Review a pull request from a session that is not the one doing the development, then hand the findings over as one durable, self-contained artifact pinned to a commit - a PR comment signed with a stable reviewer ID and carrying a measured review-environment block, so the receiving session can tell which findings its CI already covers. Use when asked to review a PR (number, URL, branch, or commit) from a separate session, host, or agent, or to convey a review to a session with no shared filesystem or shared context. Do not use when the review and the fix happen in the same session and the user reads the output directly, when the user wants a quick read of a diff they already understand, or for reviewing uncommitted local changes.
compatibility: Requires an authenticated forge CLI (gh) for delivery; read-only otherwise
---

# PR Review Handoff

A review is only useful if it survives the session boundary. When the reviewer
is not the session doing the work, three things silently break the handoff: the
receiving session cannot see the reviewer's worktree or transcript, line
numbers drift, and both sides assume the other ran the test suite. This skill
produces one artifact that fixes all three: a PR comment pinned to a commit,
signed with a stable reviewer ID, with an honest account of what the reviewer
could and could not execute.

Use it when the request sounds like "review PR 15", "review this from a
different machine", or "how would you convey this to the other session".

## Reviewer identity

Every comment is posted from the same forge account, so the account name cannot
tell two reviews apart. Sign each one.

- Format: `OpenCode Reviewer <ID>`, where `ID` is six uppercase hex characters.
- Choose the ID once per reviewer session and reuse it for every comment that
  session posts. Never mint a new ID per finding, and never reuse an ID from a
  different session - the whole point is traceability.
- Derive it from something the session can reproduce (a worktree or session
  identifier) when possible; otherwise pick a stable random value and record it
  in the conversation so the user can correlate later.
- Footer, verbatim shape:

  ```text
  ---

  Posted by **OpenCode Reviewer <ID>** - an independent review session, not the
  development agent. Comments here all come from the same account; the ID
  identifies which reviewer session produced this one. <N> findings were raised
  against `<sha>`; if HEAD has moved, re-check the cited lines before acting.
  ```

## Inputs and resolution

Accept a PR number, PR URL, branch, or commit. Resolve before reviewing:

```sh
gh pr view <N> --json number,title,headRefName,headRefOid,baseRefName,additions,deletions,changedFiles
```

- Some `gh` builds fail `gh pr view` on GraphQL `projectCards` for old accounts.
  The `--json` form still works; prefer it and note the workaround in the
  environment block if it happened.
- Review the PR head SHA, not the branch name, and record the SHA.
- A branch or commit with no PR still works: pin the SHA and post the artifact
  as a PR comment only if a PR exists, otherwise hand the file over directly.

## Execution

1. **Pin the base.** Record the head SHA and its date. Every citation in the
   artifact is relative to that commit.

2. **Isolate before reading.** Create a worktree or a separate clone and check
   out the SHA detached. Never `git checkout` over the live working tree; the
   development session may be mid-edit, and gates block destructive checkouts.
   Read the changed files **in full** at that SHA - a diff alone hides the
   surrounding control flow that decides whether a finding is real.

3. **Review bugs first, then structure, then behaviour changes.** For each
   finding decide three things before writing it: severity, whether it is a
   defect or a product decision, and how it was verified. A finding that needs a
   design call gets an explicit `Needs a decision before coding` marker rather
   than a directive.

4. **Do not treat "tests are green" as coverage of the review.** Look for the
   claims a suite cannot make: a workflow step that has never run, a fixture
   that encodes the bug, an external URL shape, a contract sentence the code
   contradicts. Those are where a separate reviewer earns its keep.

5. **Confirm external claims empirically when it is cheap.** Two commands are
   usually enough: `curl -s -o /dev/null -w '%{http_code}\n' -L <url>` for URL
   shapes, and running the suspect CLI in a scratch directory for tool
   behaviour. Put the command and its observed output inside the finding.

6. **Measure the environment; do not describe it from memory.** Collect real
   values (see Environment Block) and state plainly which gates did not run.
   This is the difference between a review and a bug report that cannot be
   triaged.

7. **Compose one body file** under the approved temp directory, in this order:
   title with the pinned SHA, scope note, environment block, findings by
   severity, minor notes, checked-without-findings, signature footer.

8. **Deliver as a comment, not a verdict.** `gh pr comment` with `--body-file`
   is the default; `gh pr review --comment` behaves differently when the
   authenticated account is the PR author and implies a formal review. Then
   verify and report the URL:

   ```sh
   gh pr view <N> --json comments \
     --jq '.comments[-1] | {author: .author.login, url, chars: (.body|length)}'
   ```

9. **Give the receiving session one relay line**, e.g.
   `gh pr view 15 --comments`, so it needs no further instruction.

## Environment block

A review without this cannot be triaged: the receiving session assumes the
suite was run, or opens with "does this reproduce on your machine?". Include:

- Relationship to the development session: separate session, separate host, no
  shared filesystem, disposable worktree.
- Host: OS and version, kernel, architecture.
- Toolchain **actually present** (interpreter, VCS, forge CLI, network client)
  and, explicitly, the build/test tools that are **absent**.
- What was therefore **not run**: the project's canonical check, linters, type
  checker, test suite.
- Which findings were reproduced versus read: name them by ID.
- Network egress, if used for a confirmation, with the UTC timestamp.
- The reviewed SHA and the fact that line numbers are from it.
- Forge CLI quirks that shaped the artifact (e.g. the `projectCards` failure
  meaning no inline line-anchored comments were possible).

Template:

```text
## Review environment

- Independent <agent> session on a host separate from the development session;
  no shared filesystem, so the worktree used for this review is machine-local
  and disposable.
- Reviewer host: <os and version>, <kernel>, <arch>.
- Toolchain present: <interpreter>, <vcs>, <forge cli>, <network client>.
- `<build tool>` is NOT installed here. `<canonical check>`, `<linter>`, and
  `<test suite>` were not run. <F-ids> were confirmed by direct reproduction
  (commands inline); <F-ids> come from reading the files, not from execution.
- Network egress was available; the checks in <F-ids> ran at <utc timestamp>.
- Reviewed commit: <full sha> (<date>). Line numbers are from that commit.
```

Redact before posting: hostname, login name, home-directory paths, IPs, and the
reviewer's absolute worktree path. It leaks machine layout and session IDs and
helps nobody triage. Every citation stays repository-relative (`install.sh:181`),
never absolute.

## Finding shape

Each finding answers, in this order and without preamble:

1. One-line symptom, with location and severity in the heading.
2. The mechanism: `path:line` and the smallest code or config excerpt that shows
   it.
3. The scenario that triggers it, in concrete terms (which input, which state,
   which environment). If a finding only bites on a rare path, say so here - the
   severity depends on it.
4. The effect, including the follow-on state if anything was already written.
5. How it was verified, with the command when it was reproduced.
6. The fix, or `Needs a decision before coding` plus the competing constraints
   and the test that currently encodes today's behaviour.

## Follow-up rounds

When the receiving session responds, re-review instead of closing out:

1. **Pin the new head** and compare it with the reviewed SHA:
   `git log --oneline <reviewed>..<new>` and
   `git diff --stat <reviewed>..<new>`. Read every changed file in full.
2. **Map each finding** to fixed, fixed differently, or deliberately deferred,
   and say which per finding in the addendum. A deferred low-severity item is a
   valid outcome; an unmentioned one is not.
3. **Re-run the cheap confirms** from the first round (the same `curl`, the same
   scratch-directory run) so a claimed fix is verified rather than assumed.
4. **Look for bugs the fix introduced.** A fix that adds a status branch, a new
   error path, or a new URL is new code: check it against the contract it was
   meant to satisfy.
5. **Check the rest of the state**: CI conclusions, whether the review got a
   reply, and whether a task or spec-status gate the PR documents is now
   unblocked.
6. **Post one signed addendum** that names both SHAs, reuses the ID, and does
   not restate the whole review.

## Guardrails

- Never push commits, open branches, or edit the PR branch from the reviewing
  session. The development session owns the branch; two-sided churn is how work
  is lost. Comment only.
- Never write review notes into the repository or the diff. They outlive their
  usefulness and pollute history.
- Do not rely on a shared filesystem, a pasted transcript, or the user relaying
  prose. If the artifact cannot be fetched by the other session, it is not a
  handoff.
- Never claim a canonical check, linter, or suite ran when it did not. The
  environment block is where that honesty is recorded, not buried in prose.
- Severity is not decoration: `high` means the feature's delivery path is broken,
  `medium` means a contract or user-visible behaviour is contradicted, `low` means
  a real but narrow defect. Do not inflate a style preference into a bug.
- Keep design calls separate from defects, and name the file and test that would
  have to change. Mixing them into one list makes the receiving session argue
  about the wrong thing.
- No emoji, no flattery, no "great work" preamble. State the issue and move on.
- One comment per review round. For a follow-up, edit the original or post a
  short addendum that names the new SHA; do not re-post the whole artifact.
- Never include secrets, credential values, or URLs carrying userinfo in the
  artifact, even when the finding is about secret handling.
