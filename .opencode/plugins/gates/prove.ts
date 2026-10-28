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

import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { evaluateAction, gatePath, HOOKS_REL, resolveBash, type Effect } from "./gates"

const root = process.cwd()
const bash = resolveBash()

function makeBrokenHookSandbox(): string {
  const sandbox = mkdtempSync(join(tmpdir(), "trovium-adapter-broken-"))
  const dir = join(sandbox, HOOKS_REL)
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, "validate-bash.sh"), "#!/bin/bash\nexit 1\n", { mode: 0o755 })
  return sandbox
}

function makeLocalRuleSandbox(projectRoot: string): string {
  const sandbox = mkdtempSync(join(tmpdir(), "trovium-adapter-local-"))
  cpSync(join(projectRoot, HOOKS_REL), join(sandbox, HOOKS_REL), { recursive: true })
  cpSync(join(projectRoot, ".specify", "gates"), join(sandbox, ".specify", "gates"), {
    recursive: true,
  })
  const rules = join(sandbox, ".specify", "gates", "hooks.local.d", "validate-bash")
  mkdirSync(rules, { recursive: true })
  writeFileSync(
    join(rules, "10-canary.sh"),
    'if grep -q gates-local-canary; then echo "canary rule refused" >&2; exit 1; fi\n',
  )
  return sandbox
}

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

const localRuleRoot = existsSync(gatePath(root, "validate-bash.sh"))
  ? makeLocalRuleSandbox(root)
  : undefined
if (localRuleRoot) {
  const sandbox = localRuleRoot
  process.on("exit", () => rmSync(sandbox, { recursive: true, force: true }))
}

const brokenHookRoot = makeBrokenHookSandbox()
process.on("exit", () => rmSync(brokenHookRoot, { recursive: true, force: true }))

const localRuleCase: Case | undefined = localRuleRoot
  ? {
      name: "shell local rule",
      action: "shell",
      resources: ["echo gates-local-canary"],
      expect: "block",
      root: localRuleRoot,
    }
  : undefined

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
  ...(localRuleCase ? [localRuleCase] : []),
  { name: "shell git add <path> (explicit)", action: "shell", resources: ["git add src/trovium/ingest.py"], expect: "allow" },
  { name: "shell commit --no-verify", action: "shell",
    resources: ["git commit --no-verify -m x"], expect: "ask" },
  { name: "shell ls -la", action: "shell", resources: ["ls -la"], expect: "allow" },

  // --- no gate for this action ----------------------------------------------
  { name: "read action is ungated", action: "read", resources: ["src/trovium/ingest.py"], expect: "allow" },

  // --- regression: the macOS-default bash 3.2 still blocks (upstream #83) ----
  { name: "bash 3.2 hook still blocks", action: "shell",
    resources: ["rm -rf /"], expect: "block", bash: "/bin/bash" },

  // --- regression: a broken hook must never silently allow ------------------
  { name: "broken hook (exit 1) -> ask, not allow", action: "shell",
    resources: ["ls -la"], expect: "ask", root: brokenHookRoot },

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
