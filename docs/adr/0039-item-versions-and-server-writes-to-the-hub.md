# 0039. Item versions stored in the event database, and the server writing into a hub's tree

- Status: proposed
- Date: 2026-10-17
- Deciders: José Henrique Roquette
- Relates to: [ADR 0019](0019-metadata-only-events-and-redaction.md) (metadata-only events; not superseded, it stays
  about events), [ADR 0024](0024-learning-actions-from-the-app.md) (the app's writes go through a temporary clone; this ADR
  adds the first writes into a hub's working tree), [ADR 0036](0036-live-playground-and-auto-mode.md) (routes that need the
  launch cookie fail on the playground's 5173)

## Context and Problem Statement

The Studio and Edit with Claude publish a skill, agent or hook by having Claude copy a draft over the item in the hub, and
workflows are edited by hand. Nothing keeps the previous content, so a bad publish or a bad edit cannot be compared or
undone from the app, and the owner avoids editing the items that matter most. Where are earlier versions kept, when are they
recorded, who writes the item on Publish and on Restore, and how are those writes gated?

## Considered Options

1. Store each version's content in agent-hub's own SQLite database (a new `item_versions` table), recorded when the app
   reads an item and just before it overwrites it; the server writes the item on Publish and Restore.
2. Commit each change to the hub's git repository.
3. A file watcher in `hub web` that records every change as it happens.
4. A `PostToolUse` hook in the hub that records every write Claude makes.
5. Option 1, but Claude keeps writing the item on Publish (the server only records).

## Decision Outcome

Chosen option: 1.

- **Storage.** Table `item_versions` (migration `0005`) in the database `hub web` already opens: id (UUIDv7), project,
  hub-relative unit path, kind, a gap-free `seq` per unit (unique with project and path), origin (`publish`, `restore`,
  `external`), `first`, author name and email (null for `external`), `recorded_at` (UTC), `content_hash` (`sha256`; for a
  folder, over the sorted lines of path, executable bit and file hash), size, the content, and for a restore the version it
  restored. Append-only: the `ItemVersionStore` port has no update or delete. No retention yet.
- **Units.** A skill's whole folder (every file with its executable bit), an agent's file, a hook's whole file
  (`.claude/settings.json`, `.claude/settings.project.json` or a plugin's `hooks/hooks.json`, never `settings.local.json`),
  a hub workflow's file. Keyed by path, so a rename starts a new history; an item reached through a link is versioned once,
  at its target; built-in workflows are not versioned.
- **Capture.** The Toolkit and Workflows reads compare each unit with its last version and record an `external` version when
  it differs (the first one marked `first`); Publish and Restore do the same for every unit they touch before they write.
  A per-unit memo of the listing's stat tuples keeps warm reads free of file opens and database writes. Nothing is captured
  in the background.
- **Content is stored, gated by the secret rules.** Versions hold full file text, which events never do. A unit in which a
  rule of `r1` (`agent_hub.core.redaction`) matches is never stored, its history says so, and Restore is refused while the
  on-disk content matches; Publish still writes it and says it was not versioned. Bounds: 256 KiB per file and the Toolkit's
  200 bundled files per skill; past them a unit is not versioned.
- **The server writes into a hub's working tree.** Publish (copy a Studio draft over the item, or place a new item in the
  project's plugin) and Restore (write a version back) run in `hub web` through one write step: per process one lock; the
  on-disk content recorded first; the write never through a link (`O_NOFOLLOW` per path segment); a file through a temporary
  file and a rename; a skill folder staged whole beside the target and swapped in with two renames, the old folder put back
  on any failure. Claude only edits the draft. No git command runs.
- **Gates.** The publish and restore routes are strict writes (this server's `Origin`, a same-origin fetch, a JSON body) and
  need the launch cookie; the version reads need neither. A managed unit (per `hub.lock`) needs an explicit confirmation
  because `hub sync` rewrites it. In the container, where hubs are mounted read-only and no launch token exists, the writes
  answer 409 `hub_read_only`; so does a hub folder that is not writable.
- **Layers.** Core holds the ports (`ItemVersionStore`, `HubItemWriter`, and `HubFileReader.read_unit`), the rules and the
  use cases; `storage` implements the store, `generator` the reader and the writer; `api` composes. The adapters do not
  import each other.

### Consequences

- Good: every change to a skill, agent, hook file or hub workflow made through the app, and every change made outside it
  that the app later reads, can be compared and restored, and a restore is itself a version.
- Good: no git state of the hub changes (no commit, branch, stash or index change), and nothing runs between reads.
- Good: Publish no longer depends on Claude following a prompt and printing a marker; it is one request with one answer.
- Bad: the database now holds file content, not only metadata. It grows with every change until retention exists, and a
  copy of the database carries the hubs' skills and agents.
- Bad: the secret rules are text patterns. A false positive leaves a unit unversioned and unrestorable until its text
  changes; a false negative stores a secret. The shipped base plugin is tested to have no match.
- Bad: two edits between reads become one version, an edit that keeps size and modification time is noticed only at the next
  real change, and a change made while the app is not read is recorded with the time it was seen, not made.
- Bad: a GET of the Toolkit or Workflows may now write to the database, so a database locked past its busy timeout answers
  503 on a read that never wrote before.
- Bad: the first API code that writes into a hub's working tree. Between the two renames of a folder swap a reader may find
  no folder, and a second `hub web` on the same hubs is not locked out of the files.
- Bad: Publish and Restore need the launch cookie, so they fail on the playground's 5173 (ADR 0036's consequence).

## More Information

- AGH-295: spec, research and plan in the hub (`brain/features/item-versions/`).
- Option 2 was rejected because it changes the hub's git history and index, which belong to the owner, and fails on a
  checkout with work in progress; option 3 because it needs a long-running process per hub and records half-written files;
  option 4 because it records only Claude's writes, not the owner's edits, `git pull` or `hub sync`, and runs in every
  session; option 5 because a recorded version would not be what Claude then wrote, and Publish would keep depending on a
  marker in Claude's reply.
- Contract: `docs/API.md` (the version routes, their errors and gates), `docs/ARCHITECTURE.md` (ports, adapters, table).
