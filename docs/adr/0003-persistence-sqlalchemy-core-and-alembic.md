# 0003. Persistence with SQLAlchemy Core and Alembic

- Status: accepted
- Date: 2026-09-27
- Deciders: José Henrique Roquette

## Context and Problem Statement

The collector writes a stream of events per session and the control plane queries them (see the events model in the
[SPEC](../SPEC.md)). v1 is local-first on SQLite; Postgres comes when there is more than one user. Events can arrive
twice (hooks and transcripts overlap), and the canonical event is still a draft, so its payload will change. How do we
store events so the domain stays independent of the database, writes are idempotent and the schema can evolve?

## Considered Options

- **SQLAlchemy 2.0 Core (no ORM) + Alembic migrations.**
- **ORM / SQLModel**: mapped classes that double as domain or API models.
- **Raw `sqlite3`**: the standard library driver and hand-written SQL.

## Decision Outcome

Chosen option: **SQLAlchemy 2.0 Core + Alembic**, because it gives a dialect-neutral schema and query builder (SQLite now,
Postgres later) and versioned migrations, without mapping the domain onto tables.

- The domain stays Pydantic, in `core`. The storage adapter maps table rows to domain models and back, in one place.
- Tables are declared only in `agent_hub.storage.db.metadata`. Alembic's `env.py`, `script.py.mako` and `versions/` live
  in `packages/storage/src/agent_hub/storage/migrations/` inside the installed package, with the Alembic config built in
  code by `agent_hub.storage.migration.alembic_config` (no `alembic.ini`); migrations run in batch mode on SQLite.
- The database lives at `~/.local/share/agent-hub/agent-hub.db` (XDG data dir), never inside a repo.
- SQLite runs in WAL mode, so the collector can write while the API reads.
- Events are idempotent: a unique key on `(source, source_id)`.
- The payload is a JSON column; only the fields we filter on get their own columns (project, session, type, timestamp).
- Postgres later through configuration (the database URL), not through a code change.
- Implemented with the events table (the collector issue). This foundation ships only the empty baseline revision `0001`.

### Consequences

- Good: the same metadata drives migrations and `alembic check`, which `make migrations` runs, so a table change without a
  migration fails `make check`.
- Good: `core` never imports SQLAlchemy (import-linter forbids it).
- Bad: row-to-model mapping is written by hand in the adapter.
- Bad: JSON payload fields are not indexed; a field that becomes a filter needs its own column and a migration.
- Neutral: tests never touch the XDG path; integration tests use SQLite files under pytest's `tmp_path`.

## More Information

- [TESTING.md](../TESTING.md): migration tests (upgrade to head, downgrade to base, `alembic check`).
- [CONTRIBUTING.md](../CONTRIBUTING.md): how to add a migration.
- Amended 2026-09-27 (AGH-1): the migrations moved from the storage package root into the installed package, with the
  config built in code (`agent_hub.storage.migration`), so an installed hub can create and upgrade its own database;
  the events table is revision 0002.
