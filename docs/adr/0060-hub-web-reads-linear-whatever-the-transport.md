# 0060. `hub web` reads Linear through GraphQL whenever a key is set, whatever the transport

- Status: proposed
- Date: 2026-11-11
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0025](0025-reading-the-tracker-from-the-app.md), for its not-connected rule only (the
  sentences "a hub with `tracker.transport: "mcp"` reads as not connected" and "or when the hub's
  `tracker.transport` is `"mcp"`"; 0025 is not edited)

## Context and Problem Statement

ADR 0025 counts a hub with `tracker.transport: "mcp"` as not connected for `hub web`, so the app never reads Linear
through MCP and never spends tokens. A hub on the MCP transport whose owner connected Linear in Settings then showed
"Linear is not connected for hub web" on a feature's Tickets tab: the key was there, but the transport decided.

The transport says how the hub's agents reach Linear ([ADR 0015](0015-linear-mcp-tracker-transport.md)). It does
not say whether `hub web` may read Linear with a key it already holds.

## Considered Options

- **Keep the rule.** An MCP hub never shows Linear's status in `hub web`, even with a key.
- **Read through GraphQL whenever a key is set.** The transport no longer decides; the key does.
- **Read through MCP for an MCP hub.** Spends tokens on every read (AGH-716 tracks an MCP reader for the conductor).

## Decision Outcome

Chosen: **read through GraphQL whenever a key is set.** `hub web` is not connected only when `LINEAR_API_KEY` is
unset or empty where it runs (the environment, then Settings' key file), whatever the hub's `tracker.transport`. The
reader stays GraphQL only, so the app still never spends tokens. The not-connected notice points to Settings first.
The ticket warmer (AGH-613) still leaves MCP hubs out, so it reads what it read before; their feature pages read on
demand.

### Consequences

- Good: an MCP hub with a key shows the same ticket status as an API hub.
- Good: one rule for "connected": a key is there.
- Neutral: an MCP hub with a key now makes GraphQL reads from `hub web`, within ADR 0025's cache and limits.
- Bad: until the warmer includes MCP hubs, their Features list shows the plan while their feature page shows Linear.

## More Information

AGH-816 (playground snapshot `20261111T002716Z`). Criteria: AC-816.1 to AC-816.3 in
[17-features.md](../design/control-plane/specs/17-features.md).
