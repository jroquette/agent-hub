# 0056. Screen-shaped reads beside the resource routes

- Status: proposed
- Date: 2026-10-31
- Deciders: José Henrique Roquette
- Complements [ADR 0004](0004-rest-api-standard.md) without superseding it; ADR 0004 is not edited.

## Context and Problem Statement

[ADR 0004](0004-rest-api-standard.md) chose resource-oriented REST: plural kebab-case nouns under `/api/v1`, the
generated OpenAPI document as the contract, thin routes that call one core use case. It accepted a cost: "some views
need several requests where GraphQL would need one".

[ADR 0053](0053-interactive-path-latency-budgets.md) then set a page budget: ready in 800 ms with at most 5 API calls
counted during the load, every `/api/v1/` request included, the Server-Sent Events streams too, as `make perf` counts
them (`apps/web/e2e/perf.spec.ts`).

Today the app shell alone makes 6 calls on every screen: `/hubs` for the no-hub redirect (asked by `App.tsx` before
its router starts, so that with no hub the gate's answer is in before the page's code and only the redirect draws,
AGH-614; the gate shares that request), `/projects` for the project switcher, `/features` and `/live-sessions` for
the sidebar badge, `/workflow-runs?limit=1` for the runs item, and the global stream. Home makes 10, Project overview
17, Sessions 13 and Session detail 13, as `make perf` counts them. Project overview also loads 200 sessions (about
778 KB) only to derive five "recent" rows.

`hub web` is one process with one interpreter lock: requests that arrive together are served one after the other, and
each request pays the same fixed cost (routing, validation, serialization, the event index's snapshot). Fewer calls
are faster calls.

How does a page reach 5 calls without losing what ADR 0004 gives: one generated contract, thin routes, resource routes
that the CLI, the MCP server and the other screens share?

Decision drivers:

- ADR 0053's page budget, counted the way `make perf` counts it.
- One contract: the OpenAPI document and the generated TypeScript client stay the only source of types.
- Thin routes: one core use case per route; no business logic in a route.
- The resource routes keep working unchanged for their other callers.
- A failure in one part must not blank a whole screen: today each region shows its own error.
- No wider access: a screen read never gives a request data that the resource route would refuse it (the
  agent-session routes need the launch cookie and this server's own pages,
  [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md)).
- No new dependency; no HTTP caching (`/api` stays `Cache-Control: no-store`).

## Considered Options

### (a) Screen reads beside the resource routes

One `GET` per screen whose first view would otherwise need more than 5 calls, under one path family. Each is built in
core from the existing read use cases, and its parts reuse the resources' schemas. The resource routes stay.

- Good: each page drops to 4 calls as `make perf` counts them (more in the cases under Consequences: a live
  session's stream, the Sessions reads that need a machine able to drive sessions, and the agent-session reads without
  the cookie, in the container or while the driver probes `claude`); the parts are the same models, so the TypeScript
  types match the resources'.
- Bad: a second shape of the same data to keep in step; each screen read follows its screen's first view.

### (b) A generic expansion parameter on the resource routes (`include=` or `expand=`)

For example `GET /projects/{project}?include=findings,runs,now,features,repos,config`.

- Good: one mechanism for every resource.
- Bad: every resource grows a parameter matrix, and its response becomes a union of optional parts (weak generated
  types). Cross-resource screens have no owning resource: the shell needs hubs, projects, a badge count and a runs
  probe; Home needs projects, what needs you and the activity feed.

### (c) A backend-for-frontend layer

A separate package or app that serves screen endpoints by calling the API, in process or over HTTP.

- Good: the API stays purely resource-shaped.
- Bad: a new composition root and a second contract; in-process HTTP hops cost the very per-request overhead this
  ADR is meant to remove.

### (d) GraphQL

One endpoint, queries shaped by the client.

- Good: one request per view by design.
- Bad: a new runtime dependency, a second schema beside OpenAPI, a different error model from RFC 9457, and it reverses
  ADR 0004's choice (a superseding ADR).

### (e) Stop counting the long-lived streams as page calls

- Good: one call fewer per screen, with no API change.
- Bad: it reads ADR 0053's "API calls counted during the load" differently. The owner kept the count as written, and
  the shell would still make 5 calls before any screen loads.

## Decision Outcome

Chosen option: **(a) screen reads beside the resource routes**, because it meets ADR 0053 with the fewest new parts:
no dependency, no new layer, the same models, and the resource routes untouched.

Rules:

- **Paths.** One family, `GET /api/v1/screens/<screen>`, named after the screen in the sitemap
  ([01-navigation.md](../design/control-plane/specs/01-navigation.md)): `screens/shell` (the app shell),
  `screens/portfolio` (Home), `screens/project-overview/{project}`, `screens/sessions` (the inbox) and
  `screens/session-detail/{session_id}`. They are listed in `agent_hub/api/openapi_paths.py` (`SCREEN_PATHS`) and in
  [API.md](../API.md) ("Contract" and "Screen reads"). Query parameters are the resource routes' own (`project`,
  `sort`, `from`), validated the same way.
- **When.** A screen read is added only when the page would make more than ADR 0053's 5 calls without it; one per
  screen, and one for the shell.
- **What.** Each is one core use case (`agent_hub.core.screens.ScreenReads`) composed of the existing read ports. It
  adds no data source and no rule, writes nothing, and never calls the tracker: the per-feature tickets route stays
  the only read that may reach Linear. A value the browser already derives stays in the browser, unless the server
  must derive it to bound the payload. The shell's badge count is the one value moved to the server: the shell would
  otherwise load every feature and live session on every screen. The shell read keeps the feature list behind that
  count for 30 s (the Features list's own refresh), so its 5 s poll re-reads the live tiles but not every feature
  folder; the app's own writes of feature records forget that list, and a `make perf` route row measures it.
- **Access.** Each part keeps its resource's access rule. The agent-session parts (the agent sessions and the driver
  capabilities) are filled only for a request that passes the agent-session read checks of
  `agent_hub/api/session_access.py` (sessions on, the launch cookie, this server's `Origin` and a `Sec-Fetch-Site` of
  `same-origin` or `none` when sent); that middleware marks such a request (a `GET` or `HEAD` only, since the read
  rules let a missing `Origin` pass; every other request is marked false), and a request without the mark gets those
  parts as `null` with no agent-session read made. The driver capabilities are taken only when they answer within
  about 50 ms (the driver keeps them 60 s, then probes `claude` for up to 5 s); else that part is `null` while the
  probe goes on and fills the driver's cache, so a probe never holds a screen's first paint. The other parts come from
  routes that need no cookie, so they answer as their routes do. A later part that comes from a guarded route follows
  the same rule.
- **Shape.** A part the web writes under a resource's key is that resource's own model with the resource's own
  bounds (a first page only; further pages come from the resource route), and for the same parameters it equals what
  the resource route answers; the API tests pin that equality. A derived part (the shell's values, the overview's
  recent sessions and `has_sessions`) is never written under a resource's key: it reuses the resource's item model
  where one exists, and its own tests pin it.
- **Resources stay.** Every resource route keeps working unchanged for the CLI, the MCP server and the other screens.
- **Web.** The web app writes each part into its query cache under the key of the resource that the screen's
  components already read, so the components stay as they are. The screen's queries for those keys wait for the screen
  read, fetched once per visit. When it fails or does not answer within 5 s, each region reads its resource route as
  before, so a failure stays in its region. Parts are written only from a fetch that has just succeeded, and never
  over an entry updated after that fetch started. A part that is not exactly the resource's answer (the overview's
  recent sessions) is never written under the resource's key, and a `null` part is not written at all: its region
  reads its resource route, so the route's own answer (401 without the cookie, 404 in the container) shows as today. A
  screen whose current view its read does not cover (Sessions with a filter set) keeps the read's provider mounted with
  its coverage switched off, so the screen's own state survives the change. A screen opened on such a view reads its
  regions from their routes until the next visit, even once the view is one its read covers: a provider covers nothing
  for a visit that began without its coverage. The app asks for the shell read before it creates its router, with the
  scope from the URL or the stored choice, as it asked for the hub list, so the first-run gate still redirects before
  the page's code arrives, and the shell and the gate share that one request.
- **Versioning.** `v1` only grows ([API.md](../API.md) "Versioning and methods"): a screen read keeps its fields until
  `/api/v2`, like any other route.

### Consequences

- Good: as `make perf` counts them (the session cookie, no `claude` on its `PATH`), Home, Project overview, Sessions
  and Session detail load in 4 calls, the shell in 2 (its read and its stream); a live Session detail makes 5 (its
  stream). On a machine that can drive sessions, Sessions also asks for its workdirs (5) and, when the CLI offers cloud
  sessions, for its cloud starts (6): those reads stay their own calls, as today. Project overview no longer loads the
  project's 200 newest sessions, only those of the issues worked on in the last 7 days (at most 200; none on the
  `make perf` fixture).
- Good: the resource contract and its callers do not change. A failed screen read degrades to today's behaviour.
- Bad: two shapes of the same data. They share their models, so the generated types cannot drift, but a screen read
  must change when its screen's first view does.
- Bad: without the session cookie, or in the container where session control is off, the agent-session parts are
  `null` and their regions read their routes: Sessions then makes 6 calls and Session detail one more. `make perf`
  opens pages with the cookie, as the owner does. While the driver probes `claude` (at most once per 60 s), the
  capabilities part is `null` too, and its read is one call more.
- Bad: one failing part fails the whole screen read. Each region then reads its own route, but the shell has no
  region of its own: the project switcher, the sidebar badge and the Workflow runs item hide together until the next
  poll (they read the same registry, so today they mostly fail together too).
- Bad: the badge's predicate exists twice: in TypeScript for the Features list (`reasonOf` in
  `apps/web/src/screens/features/groups.ts`, with its own tests) and in Python for the shell read
  (`agent_hub/core/features/owner_needs.py`). The Python tests take over the cases of the web badge tests that go with
  the shell's old hook, and each module's docstring names the other; nothing checks the two stay equal, so a change
  to one must change the other.
- Bad: the shell's badge can lag the Features list. The shell read keeps the feature list 30 s and the shell polls
  every 5 s, while the list refetches every 30 s and right after a feature's tickets are read again: after a change
  the app did not write (a feature folder edited outside the app, a ticket snapshot refreshed), the badge and the list
  can disagree for up to about 35 s. The app's own writes of feature records (a change-request decision, an owner
  sign-off) forget the kept list, so the next poll counts them.
- Bad: the web cache keys must match the components' keys exactly. A mismatch shows as an extra request in the
  page-call tests (`calls()` in `apps/web/src/testing/builders.ts`). The app's early shell read is asked under the
  shell's key, so that key must match too; an `App`-level count checks it.
- Neutral: ADR 0004's "Bad: some views need several requests" now has a bounded answer. ADR 0004 itself is not
  edited.

## More Information

- [ADR 0004](0004-rest-api-standard.md): resource-oriented REST, complemented here.
- [ADR 0053](0053-interactive-path-latency-budgets.md): the page budget and how calls are counted.
- [ADR 0017](0017-api-second-composition-root.md): `build_app` wires the screen reads like every other port.
- [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md): the session cookie and the agent-session routes'
  access rules that the agent-session parts keep.
- [API.md](../API.md) "Screen reads": the paths, their parts and the rules above.
- Tickets: AGH-623 (this ADR, the screen reads), AGH-608 (`checked_at` in the parts that show health), AGH-613 (the
  Features page, which reaches 5 calls without a screen read).
