// spec-gates -> OpenCode adapter: the agent-agnostic gate core.
//
// Ports the Claude Code PreToolUse contract onto OpenCode's permission model
// WITHOUT modifying the gate scripts:
//
//   gates hook contract        ->  Decision
//   -------------------------      --------------------------------
//   exit 2, "BLOCKED: ..." (stderr)  { effect: "block", reason }
//   exit 0, ask JSON (stdout)        { effect: "ask",   reason }
//   exit 0, no output                { effect: "allow" }
//   anything else (e.g. exit 1)      { effect: "ask"   }  (never silent allow)
//
// This module intentionally has no OpenCode import, so it can be exercised by
// prove.ts in a plain Bun/Node process.

import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { isAbsolute, join } from "node:path"

export type Effect = "allow" | "ask" | "block"

export interface Decision {
  effect: Effect
  /** Human/agent-facing reason for a block or an ask. */
  reason?: string
  /** The gate script (or OpenCode action) that produced the decision. */
  gate: string
}

export interface GateRun {
  code: number
  stdout: string
  stderr: string
}

// Where `project.sh` projects the Claude-shaped hook scripts. A future upstream
// adapter would add an "opencode" projection target; until then we reuse the
// projected copies (the extension runtime copies are not executable, and the
// projection is what pins the version).
export const HOOKS_REL = join(".claude", "hooks", "gates")

// OpenCode permission action -> gates script that guards it. Mirrors the
// Claude Code PreToolUse wiring: validate-bash on Bash, protect-files on
// Edit/Write/Patch (which OpenCode all report as the "edit" action).
export const ACTION_GATES: Record<string, string> = {
  shell: "validate-bash.sh",
  edit: "protect-files.sh",
}

const STRENGTH: Record<Effect, number> = { allow: 0, ask: 1, block: 2 }

let cachedBash: string | undefined

// Prefer a bash >= 4. On stock macOS /bin/bash is 3.2, where the gate scripts'
// `grep()`/`sed()`/`tr()`/`awk()` wrappers trip `set -e` inside `if` conditions:
// validate-bash.sh then exits 1 with no output ON EVERY COMMAND (a silent
// allow). Running the scripts under a modern bash avoids that entirely.
export function resolveBash(explicit?: string): string {
  if (explicit) return explicit
  if (cachedBash) return cachedBash
  const candidates = [process.env.GATES_BASH, "bash", "/opt/homebrew/bin/bash", "/usr/local/bin/bash"]
  for (const c of candidates) {
    if (!c) continue
    const major = bashMajor(c)
    if (major !== undefined && major >= 4) {
      cachedBash = c
      return c
    }
  }
  // No bash >= 4: keep a bash (so a broken hook surfaces as an "ask", never a
  // silent allow) rather than failing closed for the whole session.
  cachedBash = "bash"
  return cachedBash
}

function bashMajor(bash: string): number | undefined {
  const r = spawnSync(bash, ["-c", 'printf %s "${BASH_VERSINFO[0]:-0}"'], { encoding: "utf8" })
  if (r.error || r.status !== 0) return undefined
  const n = Number.parseInt((r.stdout ?? "").trim(), 10)
  return Number.isNaN(n) ? undefined : n
}

export function gatePath(root: string, script: string): string {
  return join(root, HOOKS_REL, script)
}

// Run one gate script with a Claude-shaped payload. CLAUDE_PROJECT_DIR is how
// the scripts locate the projected runtime and the policy.
export function runGate(root: string, script: string, payload: unknown, bash = resolveBash()): GateRun {
  const file = gatePath(root, script)
  if (!existsSync(file)) {
    // The extension is not projected here: there is no policy to enforce, so
    // stay inert rather than nagging on every action. /speckit.gates.init wires
    // the hooks.
    return { code: 127, stdout: "", stderr: `${script} not projected` }
  }
  const r = spawnSync(bash, [file], {
    input: JSON.stringify(payload),
    env: { ...process.env, CLAUDE_PROJECT_DIR: root },
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  })
  return { code: r.status ?? -1, stdout: r.stdout ?? "", stderr: r.stderr ?? "" }
}

export function interpret(gate: string, run: GateRun): Decision {
  if (run.code === 2) {
    return { effect: "block", gate, reason: clean(run.stderr) || clean(run.stdout) || `${gate} refused the action` }
  }
  if (run.code === 0) {
    const reason = parseAsk(run.stdout)
    if (reason) return { effect: "ask", gate, reason }
    return { effect: "allow", gate }
  }
  if (run.code === 127) {
    // Hook not installed: inert, not a policy decision.
    return { effect: "allow", gate }
  }
  // Neither blocked nor allowed: undecidable. gates' own rule is "never a
  // silent allow", so surface it as an ask. This also catches the bash 3.2
  // wrapper/errexit bug (validation hook exits 1 with empty output).
  const detail = clean(run.stderr) || clean(run.stdout)
  return {
    effect: "ask",
    gate,
    reason: `${gate} exited ${run.code} without a decision${detail ? ` (${detail})` : ""}; confirm manually`,
  }
}

// Parse a Claude PreToolUse ask decision from stdout.
export function parseAsk(stdout: string): string | undefined {
  const line = stdout
    .split("\n")
    .map((l) => l.trim())
    .reverse()
    .find((l) => l.startsWith("{"))
  if (!line) return undefined
  try {
    const j = JSON.parse(line)
    const out = j?.hookSpecificOutput
    if (out?.permissionDecision === "ask") {
      return String(out.permissionDecisionReason ?? "confirm this action")
    }
  } catch {
    /* not JSON: fall through */
  }
  return undefined
}

function clean(s: string): string {
  return s
    .trim()
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join(" — ")
    .replace(/^BLOCKED:\s*/i, "")
    .trim()
}

// Build the Claude-shaped payload the scripts expect for one OpenCode resource.
function payloadFor(root: string, action: string, resource: string): unknown {
  if (action === "shell") {
    return { tool_name: "Bash", tool_input: { command: resource } }
  }
  const path = isAbsolute(resource) ? resource : join(root, resource)
  const toolName = action === "edit" ? "Edit" : action
  return { tool_name: toolName, tool_input: { file_path: path } }
}

// Evaluate one OpenCode permission check. OpenCode may report several resources
// for one decision (a compound shell command, a multi-file patch); the
// strongest outcome wins and a block short-circuits.
export function evaluateAction(
  root: string,
  action: string,
  resources: readonly string[],
  bash?: string,
): Decision {
  const script = ACTION_GATES[action]
  if (!script) return { effect: "allow", gate: action }

  let strongest: Decision = { effect: "allow", gate: script }
  for (const resource of resources) {
    const run = runGate(root, script, payloadFor(root, action, resource), bash)
    const d = interpret(script, run)
    if (STRENGTH[d.effect] > STRENGTH[strongest.effect]) strongest = d
    if (strongest.effect === "block") break
  }
  return strongest
}
