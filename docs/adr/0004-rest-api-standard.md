# 0004. REST API standard

- Status: accepted
- Date: 2026-09-27
- Deciders: José Henrique Roquette

## Context and Problem Statement

In Phase 2 a FastAPI package (`agent_hub.api`) serves the web app: portfolio, live sessions, session timeline and
knowledge views (see the [SPEC](../SPEC.md)). The web client must never drift from the server, live sessions need
server-pushed updates, and the CLI, the API and the collector must behave the same for the same operation. Which API
style and conventions do we fix now, before the first route exists?

## Considered Options

- **Resource-oriented REST** with the FastAPI-generated OpenAPI as the contract.
- **GraphQL**: one endpoint, client-shaped queries.
- **RPC style**: one endpoint per action (`/getSessions`, `/approveGate`).

## Decision Outcome

Chosen option: **resource-oriented REST**, because the views map onto a few resources (projects, sessions, events,
learnings), FastAPI generates the OpenAPI contract for free, and a generated client removes hand-written types.

- Every route is under the `/api/v1` prefix. Resources are plural kebab-case nouns (`/api/v1/workflow-runs`).
- The OpenAPI document FastAPI generates is the contract. The web TypeScript client is generated from it, and CI fails
  when the committed spec or client is stale.
- Errors are RFC 9457 Problem Details (`application/problem+json`).
- Lists use cursor pagination.
- Live sessions stream over Server-Sent Events (SSE).
- JSON fields are snake_case; timestamps are ISO 8601 in UTC; ids are UUIDv7 (`uuid.uuid7`, stdlib since Python 3.14).
- Routes are thin: validate the input, call ONE core use case, map the result to the response. The CLI, the API and the
  collector call the same use cases ([ADR 0002](0002-lean-hexagonal-architecture.md)).
- Implemented in Phase 2, with `packages/api`. The OpenAPI staleness step joins `make check` then.

### Consequences

- Good: one contract file for server and client; a breaking change shows up as a diff in review.
- Good: UUIDv7 ids sort by creation time, which suits cursor pagination.
- Bad: some views need several requests where GraphQL would need one.
- Bad: SSE is one-way; actions (approve a gate, start a workflow) are ordinary POST requests.

## More Information

- [API.md](../API.md): the rules above, with examples.
