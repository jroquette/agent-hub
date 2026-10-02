# 0015. Linear MCP transport for the tracker port

- Status: proposed
- Date: 2026-10-02
- Deciders: José Henrique Roquette

## Context and Problem Statement

[ADR 0014](0014-tracker-port-linear-graphql.md) gave the `TrackerClient` port one adapter, Linear's GraphQL API keyed
by `LINEAR_API_KEY`, and deferred an MCP transport to a new decision that adds `tracker.transport` (default `"api"`)
and addresses prompt injection, a real live check and a short timeout. `hub next` and `hub run` (AGH-27) now use the
port. A machine without a Linear API key, such as a cloud session or a laptop that only has the Linear MCP server in
Claude Code, has no tracker at all. How does such a machine reach Linear through the port, without reopening the
risks ADR 0014 named?

## Considered Options

- **A second adapter, `McpTrackerClient`, chosen by an explicit `tracker.transport` key; each operation is a few short
  headless `claude -p` calls, each allowed only the Linear tools that call needs.**
- **The same adapter with one call per write that holds read and write tools.**
- **Pick the transport implicitly** (API when `LINEAR_API_KEY` is set, else MCP).
- **API only**; a machine without a key stays without a tracker.

## Decision Outcome

Chosen option: **`McpTrackerClient` behind an explicit `tracker.transport`, with per-call tool lists**, because it
gives keyless machines the same port, keeps the default deterministic and token-free, and never lets a model that can
write read untrusted issue text. One call per write with both kinds of tool was rejected because that model reads the
issue (untrusted) while holding a write tool. The implicit choice was rejected for ADR 0014's reason: a stray key would
switch behaviour silently. API only was rejected because it leaves cloud sessions without `hub next` and `hub run`.

- `hub.json` gains the optional key `tracker.transport`, a closed list `"api"` | `"mcp"`, default `"api"`
  ([project-config.md](../design/project-config.md)); `schema_version` stays 1. The CLI uses only what the key says,
  never the environment. Resolution itself reads no environment value. Landing with the commands (PR 3 of AGH-27):
  `hub next` and `hub run` refuse `"api"` without `LINEAR_API_KEY` (exit 1) and name the variable and the alternative
  `tracker.transport: "mcp"`, and each command prints one stderr line naming the transport.
- `McpTrackerClient` lives in `packages/tracker_linear` (`mcp.py`, with `mcp_protocol.py` and `claude_process.py`). It
  imports only core ([ADR 0008](0008-cli-as-composition-root.md)) and starts `claude` with the standard library's
  `subprocess` in the caller's process group; a timeout kills the child. It reads no `hub.json`.
- Caps are constructor parameters with these defaults: model `haiku`, `--max-turns 6`, `--max-budget-usd 0.3`,
  `effortLevel` `medium`, a 120 s timeout per call. The working directory is the hub root. The child environment is the
  caller's minus `LINEAR_API_KEY`. `last_cost_usd` (not a port method) is the sum of the `total_cost_usd` of the last
  port operation's calls (one for a read, two for a write), added whenever a result reports it as a number, an error
  result included; it is a lower bound when a call ran but reported no cost (a timeout, an output over the 1 MiB cap,
  output that is not its JSON result, an OS error after `claude` started). **Changed from the draft
  approved at the plan gate, which said "the last call's `total_cost_usd`": a write is two calls, and `hub run` adds
  both to its cost.**
- A prompt is fixed text plus one JSON request line built by the adapter: the operation and its arguments (issue id,
  team, label or state name, comment body). It never holds an issue title, a description or a tool prefix: every `_` of
  the request line is written `\u005f` (the same JSON value), so an argument holding a tool name cannot put `mcp__`
  into a prompt. A team, state or label name over 256 characters is refused before any call. **Changed from the draft
  approved at the plan gate, which had neither the `_` escaping of the request line nor the 256-character refusal.**
  A reply is one line of strict JSON (no repeated key, no lone surrogate) of a fixed shape per call, checked field by
  field: every issue id matches the issue id pattern, every state or label name is at most 256 characters; anything
  else is a `TrackerError`.
- Allowed tools per call (all under the `mcp__Linear__` prefix of the `Linear` server, a constant):

  | Call | Allowed tools |
  |---|---|
  | `list_ready` | `list_issues`, `list_issue_statuses` |
  | `get_issue` | `get_issue` |
  | read before `move_state` | `get_issue`, `list_issue_statuses` |
  | read before `add_label`, `remove_label` | `get_issue`, `list_issue_labels` |
  | read before `comment` | `get_issue` |
  | write: `move_state`, `add_label`, `remove_label` | `save_issue` |
  | write: `comment` | `save_comment` |

  `--allowedTools` only adds to the user's, project's and local allow-lists, so each call also restricts: `--tools ""`
  (no built-in tool), `--disallowedTools` with every Linear tool the call is not allowed (a deny wins over any allow),
  and `--permission-mode dontAsk` (a permissive `defaultMode` in the user's settings cannot widen the call). The Linear
  tools are a snapshot of the working `Linear` server's 68 tools taken 2026-10-01 (`LINEAR_TOOLS`); each call denies
  that snapshot minus its own tools. The snapshot is refreshed when the server changes. **Changed from the draft
  approved at the plan gate, which passed only `--allowedTools`.**

  Each call also turns every hook off (`"disableAllHooks": true` in its `--settings` JSON, next to `effortLevel`) and
  saves no session (`--no-session-persistence`); the working directory stays the hub root. Run from the hub root, a
  call otherwise runs the hub's hooks: SessionStart injects the session brief into a write call's context, the Stop
  gate runs `check_fast` across worktrees (150 s, over the call's 120 s timeout, and its output can be fed back to
  the model) and SessionEnd leaves a session stub in the brain inbox per call. **Changed from the draft approved at
  the plan gate, which let the hub's hooks run.**

- A write is one read call, then the adapter decides: a change that changes nothing makes no write call; an unknown
  state or label name raises naming it, with no write call. Otherwise one write call carries the adapter's full payload
  and holds only its write tool. The write reply must echo the requested change. No write is retried; no label or state
  is ever created. A write call that ran and failed (a timeout, an error result, an unusable reply, a wrong echo) says
  to check the issue in Linear, since the write may have been made; it never says to retry. `list_ready` filters the
  reply again in the adapter (team, label, state type), and refuses a reply listing more than 100 issues, one saying
  more match, or one listing an issue twice, rather than return part of the list. **Changed from the draft approved
  at the plan gate, which had neither the write-failure wording nor the "more match" and repeated-issue refusals.**
- Testing: `TrackerClientContract` runs against the adapter with an injected runner that answers from the seeded
  backend; a process test runs a fake `claude` executable; neither reaches Linear. A live test marked `live("mcp")`
  runs only by hand with `AGENT_HUB_LIVE=1`, `AGENT_HUB_LIVE_ISSUE`, `AGENT_HUB_LIVE_LABEL` and `AGENT_HUB_LIVE_HUB`
  (the hub root its calls run from, as in production; a label that is the hub's ready label fails at setup), and does
  not need `LINEAR_API_KEY`. The owner runs it on a machine without the key before this ADR is accepted.

### Consequences

- Good: a machine with only the Linear MCP server in Claude Code runs `hub next` and `hub run`; the default stays
  deterministic and token-free, so [SPEC.md](../SPEC.md) "Defined directions" 1 holds unless a hub opts in.
- Good: both transports pass one contract suite; `hub run` adds the MCP calls' cost to its run record.
- Bad: `"mcp"` spends tokens on orchestration: a read is one call, a write two. That is an opt-in exception to Defined
  directions 1.
- Bad: through MCP, text fields are copied by a model into JSON and may be altered or cut; `"api"` is exact.
- Bad: each call starts Claude Code in the hub root with its hooks off and no session saved, but the rest still
  loads: the hub's CLAUDE.md and AGENTS.md (tokens in every call), the enabled plugins, and the user's, project's and
  local allow rules, which still apply to tools the call neither allows nor denies (other MCP servers' tools, Linear
  tools added after the snapshot). Skipping them is AGH-39.

### Residual risk (accepted)

- A read reply carries untrusted titles and descriptions; an injected model may misreport a read (wrong labels, a
  wrong state, an invented issue). The adapter's shape checks and its own filters bound what it accepts, not whether
  the values are true.
- A write-call model holds one write tool for up to 6 turns and could call it more than once, or on another issue.
  The reply is validated, but a misuse inside those turns is not seen by the adapter.
- A comment body (built from the implementing agent's summary) is untrusted text inside a write prompt.
- A label write sends the full label set read a moment before; a change made in Linear between the two calls is lost.
- What the flags do not turn off still loads in every call: the hub's CLAUDE.md and AGENTS.md, the enabled plugins,
  and the user-, project- and local-level allow rules. A tool the `Linear` server adds after the snapshot, and any
  other MCP server's tool, is neither allowed nor denied by a call, so only such an allow exposes it. Skipping those
  settings (`--setting-sources`, `--restricted`, `--bare`) is the follow-up AGH-39, which needs a live check first.

## More Information

- [ADR 0014](0014-tracker-port-linear-graphql.md) stays accepted; this is the decision its "More Information" section
  anticipated, not a replacement.
- Design: [project-config.md](../design/project-config.md) § Tracker; [ARCHITECTURE.md](../ARCHITECTURE.md).
- Tracker issue AGH-27 (AGH-28, the MCP transport issue, was closed as its duplicate).
