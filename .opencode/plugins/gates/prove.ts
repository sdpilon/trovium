// Proof harness for the spec-gates OpenCode adapter.
//
// Runs the SAME core the plugin uses (evaluateAction) against the REAL
// projected gate scripts, and asserts the resulting block / ask / allow
// decision. Proves the translation contract end-to-end without needing to
// (re)load the OpenCode server.
//
//   bun .opencode/plugins/gates/prove.ts            # from the project root
//
// Exit code is non-zero if any case does not match.

import { existsSync } from "node:fs"
import { evaluateAction, gatePath, resolveBash, type Effect } from "./gates"

const root = process.cwd()
const bash = resolveBash()

interface Case {
  name: string
  action: string
  resources: string[]
  expect: Effect
  /** Override the interpreter (used for the bash-3.2 regression case). */
  bash?: string
  /** Override the project root (used for the not-projected case). */
  root?: string
}

const cases: Case[] = [
  // --- edit / write / patch -> protect-files.sh -----------------------------
  { name: "edit .env", action: "edit", resources: [".env"], expect: "block" },
  { name: "edit credentials.json", action: "edit", resources: ["config/credentials.json"], expect: "block" },
  { name: "edit ordinary source", action: "edit", resources: ["src/trovium/ingest.py"], expect: "allow" },

  // --- shell -> validate-bash.sh --------------------------------------------
  { name: "shell rm -rf /", action: "shell", resources: ["rm -rf /"], expect: "block" },
  { name: "shell git push --force", action: "shell", resources: ["git push --force origin main"], expect: "block" },
  { name: "shell git push --delete", action: "shell", resources: ["git push origin --delete feature"], expect: "ask" },
  { name: "shell git add -A (bulk staging)", action: "shell", resources: ["git add -A"], expect: "block" },
  { name: "shell git add <path> (explicit)", action: "shell", resources: ["git add src/trovium/ingest.py"], expect: "allow" },
  { name: "shell commit --no-verify", action: "shell",
    resources: ["git commit --no-verify -m x"], expect: "ask" },
  { name: "shell ls -la", action: "shell", resources: ["ls -la"], expect: "allow" },

  // --- no gate for this action ----------------------------------------------
  { name: "read action is ungated", action: "read", resources: ["src/trovium/ingest.py"], expect: "allow" },

  // --- regression: a broken (bash 3.2) hook must never silently allow --------
  { name: "bash-3.2 broken hook -> ask, not allow", action: "shell",
    resources: ["rm -rf /"], expect: "ask", bash: "/bin/bash" },

  // --- not projected -> inert (no policy to enforce) ------------------------
  { name: "not projected -> inert allow", action: "shell",
    resources: ["rm -rf /"], expect: "allow", root: "/nonexistent-trovium-root" },
]

let failures = 0
const pad = (s: string, n: number) => s + " ".repeat(Math.max(0, n - s.length))

console.log(`root : ${root}`)
console.log(`bash : ${bash}   (gate scripts run under this interpreter)`)

const hookMissing = !existsSync(gatePath(root, "validate-bash.sh")) || !existsSync(gatePath(root, "protect-files.sh"))
console.log(`hooks: ${hookMissing ? "MISSING (run project.sh first)" : ".claude/hooks/gates/*.sh present"}`)
console.log()

for (const c of cases) {
  const d = evaluateAction(c.root ?? root, c.action, c.resources, c.bash)
  const ok = d.effect === c.expect
  if (!ok) failures++
  const who = c.bash ? ` [${c.bash}]` : ""
  console.log(`${ok ? "PASS" : "FAIL"}  ${pad(c.action, 6)} ${pad(JSON.stringify(c.resources[0]), 38)} -> ${pad(d.effect, 5)} (want ${c.expect})${who}`)
  if (d.reason && d.effect !== "allow") console.log(`              reason: ${d.reason}`)
}

console.log()
if (failures) {
  console.log(`${failures} case(s) FAILED`)
  process.exit(1)
}
console.log(`all ${cases.length} cases passed`)
