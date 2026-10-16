// spec-gates -> OpenCode adapter (proof of concept).
//
// Enforcement seam: OpenCode's permission `evaluate` hook. It runs for every
// `allow`/`ask` decision before the action executes, exposes `action` +
// `resources` (the tool's normalized inputs), and lets a plugin set
// `effect` to "deny" (block, with `message` shown to the model) or "ask".
//
// Why not `ctx.tool.hook("execute.before")`? That seam documents "inspect or
// replace input" and has no documented reject API; `permission.evaluate` is
// the documented block/ask mechanism, so the two map 1:1 with gates' exit
// codes. See ./README.md for the full hook-by-hook mapping and the gaps.
//
// Scope of this PoC: protect-files (edit/write/patch) + validate-bash (shell),
// the two gates that need no post-processing. format/post-edit/verify-quality
// (the Stop-hook analogue) are not wired yet.

import { Plugin } from "@opencode/plugin"
import { appendFileSync } from "node:fs"
import { join } from "node:path"
import { evaluateAction, resolveBash, type Decision } from "./gates"

export default Plugin.define({
  id: "spec-gates",
  async setup(ctx) {
    const root = ctx.location.project?.canonical ?? ctx.location.directory
    const bash = resolveBash()
    const logFile = join(root, ".specify", "gates", "opencode-adapter.log")

    const note = (line: string) => {
      try {
        console.error(`[gates] ${line}`)
      } catch {
        /* no console */
      }
      try {
        appendFileSync(logFile, `${new Date().toISOString()} ${line}\n`)
      } catch {
        /* logging is best-effort */
      }
    }

    note(`adapter loaded (bash=${bash}, hooks=${join(root, ".claude", "hooks", "gates")})`)

    const registration = await ctx.permission.hook("evaluate", async (event) => {
      try {
        const decision: Decision = evaluateAction(root, event.action, event.resources ?? [], bash)
        if (decision.effect === "block") {
          event.effect = "deny"
          event.message = `gates: ${decision.reason ?? "blocked by policy"}`
          note(`DENY  ${event.action} ${JSON.stringify(event.resources)} :: ${decision.reason}`)
        } else if (decision.effect === "ask") {
          event.effect = "ask"
          event.message = `gates: ${decision.reason ?? "confirm this action"}`
          note(`ASK   ${event.action} ${JSON.stringify(event.resources)} :: ${decision.reason}`)
        }
      } catch (err) {
        // Never let an adapter bug break the agent loop.
        note(`adapter error (allowing): ${(err as Error)?.message ?? String(err)}`)
      }
    })

    return async () => {
      await registration.dispose()
    }
  },
})
