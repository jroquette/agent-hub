# API standard

The rules for the agent-hub HTTP API. The decision is [ADR 0004](adr/0004-rest-api-standard.md).

**Status: implemented in Phase 2**, with `packages/api` (`agent_hub.api`, FastAPI) and `apps/web` (React). Neither exists
yet; this document fixes the standard now so the first route follows it.

The sections up to "Thin routes" are the decided rules ([ADR 0004](adr/0004-rest-api-standard.md)). The last section,
"Proposed defaults", holds choices the decision does not make yet; they are confirmed or changed when the first route is
written in Phase 2.

## Style and naming

- Resource-oriented REST. Resources are nouns, not actions: `GET /api/v1/sessions`, not `GET /api/v1/getSessions`.
- Every route is under the `/api/v1` prefix.
- Collection names are plural kebab-case nouns: `/api/v1/projects`, `/api/v1/sessions/{session_id}`,
  `/api/v1/workflow-runs`.
- Names follow the SPEC glossary ([CONVENTIONS.md](CONVENTIONS.md)): a Session is never a "run", "job" or "execution".

## Contract

- The OpenAPI document that FastAPI generates from the routes and their Pydantic models is the contract. There is no
  hand-written spec.
- The web TypeScript client is generated from that OpenAPI document; nobody writes client types by hand.
- CI fails when the generated client is stale. This step is added to the Makefile when `packages/api` exists.

## Payloads

- JSON fields are `snake_case`, in requests and responses.
- Timestamps are ISO 8601 strings in UTC with an explicit offset: `"2026-09-27T14:03:12Z"`.
- Ids are UUIDv7 strings, generated with `uuid.uuid7()` (stdlib since Python 3.14). They sort by creation time.
- Request and response bodies are Pydantic models in `core` or in the API package; no bare dicts.

## Errors

Errors are RFC 9457 Problem Details, with media type `application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "No session with id 01923f1e-7c4a-7d2e-9b1a-3c5d8e2f4a6b.",
  "instance": "/api/v1/sessions/01923f1e-7c4a-7d2e-9b1a-3c5d8e2f4a6b"
}
```

- `type` is `about:blank` (the RFC 9457 default, meaning the problem is just the HTTP status, with `title` its reason
  phrase) until a specific problem type is defined; `detail` is specific to this occurrence.

## Pagination

Lists use cursor pagination: the client pages through a collection with an opaque cursor, never an offset (offsets skip
or repeat items while sessions are being written).

## Live updates

Live sessions stream over Server-Sent Events (SSE). SSE is one-way; actions (approve a gate, start a workflow) are
ordinary HTTP requests.

## Thin routes

A route does three things and nothing else:

1. validate the request (FastAPI and the Pydantic models do this);
2. call ONE core use case, with the adapters it needs;
3. map the use case's result, or its domain exception, to the response.

No business logic, queries or tracker calls in a route. The CLI, the API and the collector call the same use cases, so
the same operation behaves the same from every entry point ([ARCHITECTURE.md](ARCHITECTURE.md)).

## Proposed defaults (to confirm in Phase 2)

Not decided yet. Each is a starting point for the first route and becomes a rule here, or an ADR if it is hard to
reverse, once confirmed.

- **Versioning:** a breaking change goes to a new version prefix (`/api/v2`); `v1` keeps working until it is retired.
- **Paths and methods:** nested paths only for ownership (`/api/v1/sessions/{session_id}/events`). Methods keep their
  HTTP meaning: `GET` reads, `POST` creates or triggers an action on a resource (`POST /api/v1/workflow-runs`), `PATCH`
  updates part of a resource, `DELETE` removes it.
- **Committed contract:** the generated OpenAPI document and client are committed, and `make check` regenerates them and
  fails on a diff, so a contract change shows up in review.
- **Error mapping:** each named domain exception maps to one problem in one place in the API package; unexpected
  exceptions become a generic `500` problem that never leaks internals or secrets. Specific problem `type` URIs, if any,
  are defined then. The module that builds Problem Details is `rfc9457.py` (no `_<digits>` ending, see
  [TESTING.md](TESTING.md)).
- **Pagination shape:** `GET /api/v1/sessions?limit=50&cursor=<opaque>` returns
  `{"items": [...], "next_cursor": "<opaque>"}`; `next_cursor` is `null` on the last page.
- **SSE shape:** `GET /api/v1/sessions/{session_id}/events/stream` with `Accept: text/event-stream`. Each SSE message
  carries one canonical event as JSON with its UUIDv7 id as the SSE `id`, so a client that reconnects resumes from
  `Last-Event-ID`.
