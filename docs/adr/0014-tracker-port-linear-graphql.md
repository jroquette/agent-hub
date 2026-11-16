# 0014. Tracker port with a Linear GraphQL adapter

- Status: accepted
- Date: 2026-10-01
- Deciders: José Henrique Roquette

## Context and Problem Statement

[ADR 0002](0002-lean-hexagonal-architecture.md) puts ports in core and promises a task-tracker port with Linear as the
first adapter. Until now the tracker was reached only by the hub runner's free-text prompts to a headless Claude
session limited to the Linear MCP tools: tool names tied to one connector prefix, unparsed replies, no tests. `hub next`
and `hub run` need a typed, tested tracker. Linear can be reached through its GraphQL API with a personal API key, or
through the Linear MCP tools of a Claude Code session, which need no key but cost a model call. How does agent-hub talk
to the tracker?

## Considered Options

- **A core port with a GraphQL adapter now; an MCP transport deferred to its own decision.**
- **A core port with both transports now, chosen by a `tracker.transport` key.**
- **A core port with an MCP adapter only.**
- **Pick the transport implicitly** (API when `LINEAR_API_KEY` is set, else MCP).

## Decision Outcome

Chosen option: **a core port with a GraphQL adapter, the MCP transport deferred**, because tracker reads and writes are
deterministic, and [SPEC.md](../SPEC.md) "Defined directions" 1 says orchestration spends no tokens and deterministic
work is a script step. An MCP adapter was also set aside for now because a contract run against a fake `claude` does
not prove the real model's behaviour, and a model holding Linear write tools while reading untrusted issue text is a
prompt-injection risk. The implicit choice was rejected because a stray key would switch behaviour silently.

- Core defines the `TrackerClient` port (`list_ready`, `get_issue`, `move_state`, `add_label`, `remove_label`,
  `comment`), the frozen `Issue` value object (its `id` is the tracker's identifier, such as `DEM-1`), `TrackerError`,
  an in-memory fake and the contract suite `TrackerClientContract`. Every adapter failure is a `TrackerError` naming the
  operation, the issue, the cause and the fix. No operation creates labels or states; no write is retried.
- "Ready" means: in the team, carrying the ready label, and in a workflow state whose type is not `completed`,
  `canceled` or `duplicate`. The result is unordered; ordering and dependencies belong to the runner.
- The package `packages/tracker_linear` (`agent-hub-tracker-linear`) holds the adapter. It imports only core and joins
  the independent adapter layer under `cli` beside `storage`, `collector` and `generator`
  ([ADR 0008](0008-cli-as-composition-root.md)'s rule, extended to a new member as
  [ADR 0011](0011-templates-as-package-data.md) did; 0008 is not superseded).
- The adapter calls Linear's GraphQL API over the standard library (`urllib`), with no third-party dependency. The key
  comes only from the environment variable `LINEAR_API_KEY`, read at call time, never from `hub.json`, never logged or
  shown. Mutations use Linear's internal ids, resolved from the identifier once per operation. Redirects are never
  followed, so the key never leaves the fixed endpoint. Responses are bounded (size, pages, labels); each socket
  operation times out after 30 s. State and label names match exactly (case-sensitive).
- The CLI composition root resolves the adapter from `tracker.kind` (`linear`). `hub.json` gains no key.
- Testing: the contract suite runs in CI against the fake and against the GraphQL adapter over an in-process fake of
  Linear's API; no network. A smoke test against real Linear, marked `live`, is never selected by `make check`; any
  other pytest run that collects it reaches Linear only when `LINEAR_API_KEY`, `AGENT_HUB_LIVE_ISSUE` and
  `AGENT_HUB_LIVE_LABEL` are set and `AGENT_HUB_LIVE=1`.

### Consequences

- Good: one port and one suite for every tracker use; deterministic calls with no model cost; CI stays hermetic; the
  key never enters the repository or the config.
- Good: a second tracker kind, or a second Linear transport, is a new adapter passing the same suite.
- Bad: every project that uses the port needs a Linear API key in its environment; the Claude Code connector alone is
  no longer enough for `hub next` / `hub run`.
- Bad: the adapter's facts about Linear (identifier lookup, page sizes) are checked only by the by-hand `live` run.

## More Information

- An MCP transport, if added, is a new decision: it adds `tracker.transport` (default `"api"`) and must address prompt
  injection, a real live check and a short timeout (AGH-28).
- Design: [project-config.md](../design/project-config.md) § Tracker; [ARCHITECTURE.md](../ARCHITECTURE.md).
- Tracker issue AGH-9. The `hub next` / `hub run` commands that use the port come with AGH-27.
