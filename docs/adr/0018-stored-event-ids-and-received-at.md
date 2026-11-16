# 0018. Storage-minted event ids, `received_at` and read queries on the event store

- Status: accepted
- Date: 2026-10-11
- Deciders: José Henrique Roquette (delegated to the lead for AGH-200)

## Context and Problem Statement

SSE needs a stable id per event (`id:` and `Last-Event-ID`), Raw events shows ingestion latency, and read models need
queries by project, session, type and time. The canonical `Event` has neither an id nor a receive time, and the
`EventStore` port has only `append` and `read_all`. `domain-model.md` says the platform mints no ids in Phases 1-2.

## Considered Options

1. Add `id`/`received_at` to the canonical `Event` (sources would have to send them).
2. Storage fields minted at append (`event_id` UUIDv7, `received_at` UTC), returned beside the event as `StoredEvent`.
3. Use the SQLite autoincrement `events.id` as the public id.

## Decision Outcome

Option 2. Migration `0003` adds `event_id` (unique, NOT NULL; legacy rows get a UUIDv7 minted by the migration) and
`received_at` (nullable; NULL for legacy rows) and indexes `(project, session, id)`, `(project, type, timestamp)`,
`(project, timestamp)`. Identity stays `(source, source_id)`; duplicates keep the first row's `event_id`. The append
sequence (`events.id`) is exposed as `seq` for ordering and SSE resume, never as an identity. The port gains
`query(EventQuery)`, `find(event_id)` and `high_water_mark()` (read-only; no update or delete), proven by
`EventStoreContract` on the fake and SQLite. Amends `domain-model.md`: storage ids and hub registry ids are minted.

### Consequences

- Good: `Event` and the JSONL contract stay unchanged; SSE ids are opaque and stable; latency is visible.
- Bad: `event_id` differs between two databases holding the same event; links across databases use `(source, source_id)`.

## More Information

Control-plane feature spec (AGH-200) D5, D12, D13; [ADR 0003](0003-persistence-sqlalchemy-core-and-alembic.md);
[domain-model.md](../design/domain-model.md); [event-derivations.md](../design/event-derivations.md).
