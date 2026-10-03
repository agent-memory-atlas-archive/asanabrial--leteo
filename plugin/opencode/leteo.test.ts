// Contract tests for the OpenCode plugin.
//
// OpenCode 1.x loads the `server` factory; 2.x loads `setup`. Those two shapes
// are what these tests hold the plugin to, because the failure this file exists
// to catch — a plugin that silently does not load on 2.x — is exactly a shape
// mismatch, and nothing else in the repository exercises either contract.
//
// Run with: `node --test leteo.test.ts` from this directory.
import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"

import plugin, { Leteo } from "./leteo.ts"

const HERE = fileURLToPath(new URL(".", import.meta.url))

test("the default export serves both majors", () => {
  assert.equal((plugin as any).id, "leteo")
  assert.equal((plugin as any).server, Leteo)
  assert.equal(typeof (plugin as any).setup, "function")
})

test("the 1.x factory binds the four hooks 1.x calls", async () => {
  const hooks = (await Leteo({ directory: HERE } as any)) as Record<string, unknown>
  for (const name of [
    "event",
    "chat.message",
    "tool.execute.after",
    "experimental.chat.system.transform",
  ]) {
    assert.equal(typeof hooks[name], "function", `${name} is bound`)
  }
})

test("the 2.x setup registers its hooks and subscribes to events", async () => {
  const registered: string[] = []
  let subscribed = false
  let released = 0
  const ctx = {
    location: { directory: HERE },
    event: {
      subscribe: () => {
        subscribed = true
        return (async function* () {})()
      },
    },
    session: {
      hook: async (name: string) => {
        registered.push(`session:${name}`)
        return {
          dispose: async () => {
            released++
          },
        }
      },
    },
    tool: {
      hook: async (name: string) => {
        registered.push(`tool:${name}`)
        return {
          dispose: async () => {
            released++
          },
        }
      },
    },
  }
  const cleanup = await (plugin as any).setup(ctx)
  assert.deepEqual(registered.sort(), ["session:context", "tool:execute.after"])
  assert.ok(subscribed, "the event stream is subscribed")
  await cleanup()
  assert.equal(released, 2, "cleanup disposes both registrations")
})

test("no Bun-only API on the hook path", () => {
  const source = readFileSync(new URL("./leteo.ts", import.meta.url), "utf8")
  // Comments may name Bun to explain why it is gone; only code counts.
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "")
  assert.ok(!/\bBun\b/.test(code), "the plugin must not use Bun")
  assert.ok(code.includes("node:child_process"), "the hook path spawns through Node")
})
