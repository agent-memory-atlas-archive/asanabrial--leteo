# A local HTTP API

## Now

The store answers two interfaces: MCP over stdio, and the CLI. A script or a
plugin that wants one of its memories has to be an MCP client or shell out to
`leteo` and pay a process per call. There is no long-lived process to hold the
store open and answer over the loopback.

Engram ships one — `engram serve`, on `127.0.0.1:7437` — and its absence was
found in the comparison of 2026-10-07 that also found serverless sharing.
`replication.md` records the half of that comparison that was turned down; this
proposal records the half that was accepted. It is built by #223.

## Proposed

A `leteo serve` process, binding the loopback by default, that answers the
store's operations over HTTP so a script can read and write memories without MCP
and without a new process per call.

- **Same store, same rules.** A write over HTTP normalises, indexes, redacts and
  enqueues for replication exactly as the MCP and CLI paths do; no behaviour
  lives only here. This is the invariant `replication.md` already states for
  every path, applied to a third caller of the same write functions rather than
  a second implementation of them.
- **Loopback by default.** `127.0.0.1`, and a bind that is not loopback is an
  explicit opt-in that says so in its reply, because the store holds everything
  the agent has remembered.
- **The tools are the vocabulary.** The endpoint set mirrors the MCP tool
  surface — `mem_save`, `mem_search`, `mem_get_observation`, and the rest — so
  there is one name and one argument shape for a memory operation, not a second
  REST vocabulary to keep in step.

The transport — JSON-RPC over HTTP against the same tool names, or a REST
mapping — and the endpoint list are the follow-up issue's to fix. What this
proposal fixes is only that the capability is wanted and that it is a caller of
the store's existing write paths.

## Cost

A long-lived process holding the store open, so the store's single-writer and
lock discipline must be stated for a caller that is not a one-shot CLI. The
dependencies are already in the tree — `axum` and `tokio` ship unconditionally
for the cloud server — so the new weight is small; the surface is what grows,
because a listening socket is a thing to secure, document and keep answering.

## Specs to edit

- `cli.md` — the `serve` subcommand, its loopback default and its opt-in bind.
- `mcp-tools.md` — that the same operations answer here, under their own names.
- `replication.md` — a link, since an HTTP write takes the same replicated path.
