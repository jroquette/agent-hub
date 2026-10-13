# 0025. Reading the tracker from the app through a read-only `TrackerReader` port

- Status: accepted
- Date: 2026-10-13
- Deciders: José Henrique Roquette (D1 to D5; design delegated to the lead for AGH-136)

## Context and Problem Statement

`hub web` shows a feature's tickets as bare ids ("—" as title), because the app never reads the tracker: Linear is
"not connected in this version" ([SPEC.md](../SPEC.md)), the server is local only, and its one network exception is the
learning decisions' explicit `POST` ([ADR 0024](0024-learning-actions-from-the-app.md)). The owner wants each ticket's
title, status, assignee, link and "blocked by" edges, what can start now and in which order (decision D1: Linear's API,
read-only, with the `LINEAR_API_KEY` the tracker adapter already uses, a short cache, and a visible fallback to the plan
without a key or network; D2: order and parallelism from explicit dependencies). [ADR 0014](0014-tracker-port-linear-graphql.md)
gives the CLI a `TrackerClient` with writes and says ordering and dependencies belong to the runner;
[ADR 0015](0015-linear-mcp-tracker-transport.md) adds an MCP transport that spends tokens per call;
[ADR 0017](0017-api-second-composition-root.md) lets `api` import the adapter packages. How does the app read the
tracker without write power, tokens, a CSP change or a stored copy?

## Considered Options

1. The browser calls Linear (CSP `connect-src` widened, the key in the browser).
2. The server reads Linear through the existing `TrackerClient` (the app holds write methods; `Issue` lacks state type,
   assignee and relations, and widening it changes both adapters and the CLI).
3. The server reads Linear through the MCP transport (a model call per page view, tokens, a child process).
4. A read-only core port `TrackerReader`, a GraphQL adapter in `tracker_linear`, wired only by `api`, called on one
   read route behind an in-memory cache, with a fallback to the plan.
5. An explicit "Refresh from Linear" `POST` action, as in ADR 0024 (status stays stale until the owner clicks).
6. Brain files only (no live status).

## Decision Outcome

Option 4.

- **Port.** `TrackerReader` (`agent_hub.core.tracker.tracker_reader`): `issue_summaries(ids) -> TicketSnapshot`, at most
  200 ids per call. An `IssueSummary` holds `id`, `title`, `state {name, type}`, `assignee` (display name or null),
  `url`, `priority` (0 to 4 or null), `estimate` (or null), `blocks`, `blocked_by` and `relations_truncated`; the
  snapshot adds `missing` (ids Linear did not return, and malformed ids, never sent) and `external` (blockers outside
  the ids, read from the same relation nodes). No description, comment or attachment is ever requested. Failures are
  `TrackerError` with a `kind` (`not_connected`, `unauthorized`, `timeout`, `rate_limited`, `unavailable`,
  `unexpected`, `unreachable`, `too_many`, `other`) and, when Linear answered, its `http_status`. A fake,
  `InMemoryTrackerReader`, and the suite `TrackerReaderContract` live in core; `TrackerClient` is unchanged.
- **Adapter.** `LinearGraphqlTrackerReader` (`agent_hub.tracker_linear.graphql_reader`) shares ADR 0014's transport,
  moved to `graphql_transport.py`: `urllib`, the fixed endpoint, no redirects, the key from `LINEAR_API_KEY` at call
  time and never in a message, answers of at most 4 MiB checked field by field. One query per team and page of 50
  (`team.key` and `number in`), 10 s per request and 20 s per read. "Blocked by" is an inverse relation of type
  `blocks`. It never uses the MCP transport: a hub with `tracker.transport: "mcp"` reads as not connected
  ([SPEC.md](../SPEC.md) "Defined directions" 1).
- **Composition.** `api` depends on `agent-hub-tracker-linear` and builds the reader in `build_app` only; `cli` keeps
  its own `resolve_tracker_client`. Whether the app is connected is decided on every read, without a request: not
  connected when `LINEAR_API_KEY` is unset or empty where `hub web` runs, or when the hub's `tracker.transport` is
  `"mcp"`, so a key set while `hub web` runs takes effect at once. The layers of ADR 0017 are unchanged (`api` already
  sat above the adapters).
- **Cache.** In memory only (`agent_hub.api.ticket_snapshots`): per project and feature id set, 60 s, single flight,
  at most 256 entries. After a failure the last snapshot is served for at most 15 minutes, marked stale with its
  `as_of`; a 429 pauses reads of that entry for 60 s. Nothing from Linear goes to the event database, the brain or a
  log.
- **HTTP.** `GET /api/v1/features/{project}/{slug}/tickets` is the only route that may call Linear. For a known
  feature it always answers 200: `source` (`linear` or `plan`), `stale`, `as_of`, a `notice` when the data is from
  the plan or stale, and a `tracker_problem` (RFC 9457 members, `type` `urn:agent-hub:problem:tracker-<kind>`) naming
  the cause, whose `status` is Linear's 4xx or 5xx status when it answered one, else 504 for a timeout, 502 for an
  answer of an unexpected shape and 503 otherwise. The Features list and detail use only a warm cache, else the plan.
  Titles and names are redacted with `r1`; a `url` outside `https://linear.app/` is dropped. The CSP
  stays `connect-src 'self'`; the browser never contacts Linear.
- **Planning.** Order, parallel layers, waiting tickets, cycles, external blockers and the critical path are a pure core
  fold over the plan's `blocked_by` and Linear's relations, labelled derived. This refines ADR 0014's "ordering and
  dependencies belong to the runner": the app shows a recommendation and never acts on it; the runner still decides.

### Consequences

- Good: the owner sees titles, status, links and blockers; the app has no write method and spends no tokens.
- Good: Linear down, no key or the MCP transport never fails a feature route; the plan is shown with a reason.
- Bad: a second documented exception to "local only": a read, on page view, to `api.linear.app`, with the user's key.
- Bad: `hub web` needs `LINEAR_API_KEY` in its own environment (and passed into the container) to show live status.
- Bad: Linear's field names are proven in CI only against a recorded synthetic answer; the real schema is checked by
  the by-hand `live` test, as in ADR 0014.

## More Information

Ticket planning spec (AGH-136, in the private hub) D1 to D5, S1, S2, S4, AC-136.1 to AC-136.7, AC-136.35;
[ADR 0014](0014-tracker-port-linear-graphql.md), [ADR 0015](0015-linear-mcp-tracker-transport.md),
[ADR 0017](0017-api-second-composition-root.md), [ADR 0024](0024-learning-actions-from-the-app.md);
[API.md](../API.md) "Feature tickets"; [design/feature-records.md](../design/feature-records.md).
