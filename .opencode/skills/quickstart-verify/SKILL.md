---
name: Quickstart Verify
description: Dispatch a fresh subagent to manually drive the real app or CLI through every scenario in a feature's quickstart.md and report pass/fail/unverified back, flagging anything this environment cannot independently verify. Use when asked for a by-hand or independent-agent pass through a feature's quickstart.md scenarios, or before closing out work whose specs/NNN-slug/quickstart.md needs manual verification beyond the automated test suite. Do not use for routine "does it work" checks that the automated suite can answer, or for reviewing code or pull requests.
compatibility: Requires a specs/<feature>/quickstart.md layout
---

# Verify Quickstart

Runs the by-hand checklist in a feature's `quickstart.md` against the real
running app or CLI, via one fresh agent with no memory of how the feature was
built. The output is a pass / fail / not-independently-verified report per
scenario, produced in the conversation — not a file written to the repo.

Use this for requests shaped like "start a fresh agent and go through the
quickstart scenarios, report back any issues" — the independent pass catches
"works when the author runs it" gaps that the automated suite does not model.

## User Input

Text supplied with the request is optional: a feature number or slug
(e.g. `005`, `005-mobile-preview-crashes`). Empty is the normal case — resolve
from the current branch instead (see Spec Resolution).

## Spec Resolution

1. **User-provided identifier**: if one is given, match it against the
   `specs/` directory — a bare number like `005` matches `specs/005-*/`;
   a full slug matches exactly.
2. **Current branch** (the normal case): spec-kit branches are named
   `NNN-slug` and match `specs/NNN-slug/`. Resolve from
   `git branch --show-current`.
3. **Neither resolves**: list every `specs/*/quickstart.md` that exists and
   ask which one. Never guess silently.

Set `QUICKSTART = specs/<resolved-dir>/quickstart.md`.

## Prerequisites

- `QUICKSTART` must exist. If the resolved feature directory has no
  `quickstart.md`, say so and stop — there is nothing to run. A directory in
  a lighter format may still carry one alongside its own docs; check before
  concluding there is nothing to verify.
- Identify the project's documented way to **launch and drive** the thing
  under test (a driving skill, a README "Usage"/"Development" section, or a
  project script). The dispatched agent needs it; do not dispatch without
  confirming a documented path exists. If none exists, ask the user how the
  app/CLI is meant to be driven.
- `git status`: not a hard blocker. Note any uncommitted changes relevant to
  this feature in the dispatch prompt so the agent knows what it is actually
  testing. Do not dispatch against your own in-progress edits in the same
  session without saying so.
- Note whether a long-running service the driving instructions expect is
  already up (a dev server, a local daemon, a configured endpoint), so the
  prompt can tell the agent to reuse it rather than start a competing one.

## Execution

1. **Dispatch one fresh agent** — a new subagent session with no inherited
   conversation context. Do not use a context-forking variant; the point is
   an agent that approaches the app with no prior belief that the outcome is
   correct.

2. **Send a self-contained prompt** — a fresh agent has zero context, so
   include everything. Fill the brackets and send essentially this, verbatim:

   ```text
   You are working in the repo at [ABSOLUTE_PROJECT_PATH] (on branch
   [BRANCH]; working tree [clean / has uncommitted changes — note what and
   why if not clean]). Do not switch branches and do not touch git.
   [ONE-SENTENCE PROJECT DESCRIPTION — what kind of app or CLI this is, and
   how it is built/run.]

   [ONE OR TWO SENTENCES OF CONTEXT: what work this quickstart is verifying
   — a bugfix, a feature, what it changed — and why an independent manual
   pass is wanted on top of the automated suite, which is already green.]

   **Your task**: read `[QUICKSTART]` in full, then manually execute every
   numbered scenario in it, and report back pass/fail/not-independently-
   verified for each, with specifics.

   **How to drive it**: follow [DRIVING_INSTRUCTIONS — the documented path:
   a driving skill at PATH/SKILL.md, the README's usage section, or a
   project script]. Use it exactly as documented, including its own
   first-run/discovery flow if launching does not just work. [If a service
   was already found running: note it and tell the agent to connect to it
   instead of starting a new one.]

   **Limitations to flag, never silently skip**: [list anything the
   quickstart calls for that this environment genuinely cannot do — a
   specific browser, a real device, hardware the driving tool does not
   control, an external service that is unavailable]. For each: do what you
   can with what is available, but explicitly mark that scenario NOT
   INDEPENDENTLY VERIFIED for the part you could not actually test. Never
   claim a pass for a part you did not run.

   Work through the scenarios in order. For each, note: what you did, what
   you expected (per the quickstart document), what you actually observed,
   and PASS / FAIL / NOT INDEPENDENTLY VERIFIED. Capture screenshots or
   command output where useful for anything surprising. At the end, give a
   short overall summary: anything that looks like a real regression or
   problem, versus everything that checked out.

   Do not modify any files, do not commit anything, do not touch git. This
   is a read-only, drive-and-observe verification task. Report your findings
   back in full detail.
   ```

3. **Synthesize the report** — do not relay a long raw report verbatim.
   Extract what passed, what failed, what was not independently verified, and
   any suspected regressions, in the same shape as the agent's own summary.

4. **Offer to update a PR checklist, if the project uses one** — if open pull
   requests here carry a collapsible quickstart-scenario checklist, offer to
   update it to match what was actually confirmed. Check a box only for a
   scenario genuinely run and passed; leave anything marked NOT
   INDEPENDENTLY VERIFIED unchecked with a note. Never check a box on the
   agent's behalf for something it flagged as unverified.

## Guardrails

- The dispatched agent must be told explicitly not to modify files, commit,
  or touch git — this is a read-only verification pass.
- Never upgrade "not independently verified" to a pass, either in the
  agent's report or in your synthesis. If a scenario cannot be tested from
  this environment, say so in the final report; do not omit it.
- A regression the agent finds is a new bug, not something to quietly patch
  over in the same breath. Surface it plainly and let the user decide whether
  to fix it now or track it separately.
- Never fabricate scenario results for a `quickstart.md` that does not exist,
  and never invent scenario numbers that are not in the file.
- Keep this skill agnostic: do not assume a language, package manager, port,
  browser, or agent runtime. Resolve all of those from the project's own
  documented driving path.
