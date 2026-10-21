# 0044. Team memory: Git stays the source, each developer keeps a derived search index, agents reach it through `hub mcp`

- Status: accepted
- Date: 2026-10-21
- Deciders: José Henrique Roquette
- Relates to: [ADR 0019](0019-metadata-only-events-and-redaction.md) (metadata-only events; not superseded),
  [ADR 0024](0024-learning-actions-from-the-app.md) and [ADR 0037](0037-learning-decisions-unpushed-notes-and-edits.md)
  (hub pull requests through `hub_git`), [ADR 0039](0039-item-versions-and-server-writes-to-the-hub.md) (file content
  in the app's database), [ADR 0017](0017-api-second-composition-root.md) (a second composition root)

## Context and Problem Statement

A hub's memory is its `brain/` folder, versioned in Git (SPEC, Defined directions 2). Measured in this project's hub on
2026-10-21: `features/` holds 651 files (20 MB), `_inbox/` about 80 unreviewed proposals (364 KB), `learnings/` 6,
`decisions/`, `domain/` and `system/` one each.

- Git works well as the source of truth for authoritative knowledge: versioned, reviewed in pull requests, readable
  with grep, available in cloud sessions.
- The review queue is stuck: every learning waits for a manual curation step.
- Many inbox notes are procedural rules a machine can check (numeric AC ids, spec verify paths that must pass the
  layout rules). As notes, they work only when an agent remembers to read them.
- `features/` is process history, not memory. On the agent's read path it is noise.
- Retrieval is by path only (`brain/index.md`); there is no search besides `/recall` over local transcripts.

The question is where each kind of knowledge lives and how an agent finds it, without breaking local-first (`hub web`
on loopback, one SQLite per developer, no login; hosted only with a second organization).

## Considered Options

1. Keep the brain as is and rely on `brain/index.md` and grep.
2. A central knowledge service (hosted database, shared index, accounts).
3. Git as the source; each developer builds a local, derived full-text index (SQLite FTS5) from the checkout; agents
   reach it through a local stdio MCP server, `hub mcp`.
4. As 3 with embeddings (vector search) from the start.

## Decision Outcome

Option 3. Embeddings (option 4) wait until full-text search proves not enough; hosting (option 2) waits for a second
organization, as the SPEC's "Where it runs" already says.

### Knowledge by kind

| Kind | Where it lives |
| --- | --- |
| Procedural ("always do X") | A check (`hub doctor` rule or hook), a skill line or the repo's `AGENTS.md`; it leaves the brain |
| Authoritative (decisions, domain, playbooks, learnings) | `brain/` in the hub repo: small, reviewed in pull requests |
| Historical (`features/`, journal) | `brain/` in Git, off the agent's read path, reached through search |
| Personal | `brain/auto/workspace/`, gitignored (unchanged) |
| Session transcripts | Each developer's machine only (`~/.claude/projects`, the app's own redacted copies); never shared, never indexed |

### Git is the source of truth

The team shares knowledge by `git pull` of the hub repo. Nothing else is authoritative: the index below can be deleted
at any time and rebuilt from the checkout without loss.

### A derived local index

- **Where:** the database `hub web` and `hub collect` already use (`--db`, `AGENT_HUB_DB`, else the default
  `agent-hub.db`), in new tables created by an Alembic migration: one row per indexed file and an FTS5 virtual table
  over its title and body. A missing FTS5 module in the interpreter's SQLite is a clear error, never a fallback.
- **What:** per registered hub, the files Git tracks or would track (`git ls-files --cached --others
  --exclude-standard`) under the hub's `brain/` (except `brain/auto/`) and, for each repo in `hub.json`, under its
  `docs/` (ADRs included). Markdown only; a regular file reached without a link, at most 256 KiB, UTF-8. A file that
  matches a secret rule of the guard is skipped and reported by path, never indexed.
- **Each row keeps:** hub, path, kind (from the folder: `decision`, `domain`, `learning`, `playbook`, `system`, `inbox`,
  `feature`, `journal`, `adr`, `doc`), title (first heading, else file name), the frontmatter's `status` and
  `provenance` when present, size, mtime, `sha256` and the text.
- **Freshness:** every search first syncs the index with the checkout: files whose size or mtime changed are re-read
  and re-indexed when their hash differs, vanished files are dropped, new files are added. `hub brain reindex` drops a
  hub's rows and rebuilds them. A change to what is indexed or how (tokenizer, kinds) bumps an index version stored
  with the rows, and a stale version rebuilds on the next search.
- **Search:** the query is plain words, each quoted before it reaches FTS5 (no FTS syntax from the caller, no syntax
  errors), all words required, ranked by `bm25` with the title weighted above the body. Every result carries its
  source: hub, path, kind, title, status and a short snippet. Optional filters: kind and hub. At most 50 results.
- **Shape:** a port in `core` (`KnowledgeIndex`: sync a hub's documents, search), its SQLite adapter in `storage`, the
  checkout walk in the composition roots; `hub search QUERY [--kind K]… [--hub NAME] [--json]` and
  `hub brain reindex` in the CLI.

### `hub mcp`: agents reach the index through a local stdio server

- `hub mcp`, run from a hub, serves the Model Context Protocol over stdio for one Claude Code session. It opens no
  port. It lives in a new package, `packages/mcp_server` (`agent_hub.mcp_server`), a third composition root like `api`
  ([ADR 0017](0017-api-second-composition-root.md)): it may import `storage` and `hub_git`, and `cli` reaches it only
  through `mcp_command`. Its MCP library is the official Python SDK, pinned in the lockfile.
- Tools:
  - `search(query, kind?, limit?)`: the search above, after the sync; results always with path and snippet.
  - `read(path)`: one file's text, only under the hub's `brain/` (except `brain/auto/`) or a hub repo's `docs/`, by
    path relative to the hub (`brain/…`, `<repo dir>/docs/…`); the same file rules as the index, each path segment
    checked with `lstat` so no link leads out.
  - `propose(title, body, kind, external)`: a new inbox note. `hub_git` gains a third action next to accept and
    reject: in a temporary clone of `origin`, as for accept (the developer's checkout, index, refs and worktrees stay
    untouched), it writes `brain/_inbox/<date>-<slug>.md` with frontmatter (`status: proposed`, `provenance: agent`, or
    `agent-from-external` when `external` is true; `created`; the session id when known), commits it as the hub's
    author on a new branch `<branch_prefix>brain-inbox-<slug>` from `origin/<default_branch>`, pushes it and opens a
    pull request with `gh`. It never writes the default branch. A body that matches a secret rule, a note that already
    exists, or a hub not on GitHub is refused with the reason. The result is the pull request's URL.
- Every tool call passes through the hub's guard like any `mcp__*` tool (blocked words included).
- **Configuration:** `hub sync` renders the project's MCP configuration as a managed file at the hub's root,
  `.mcp.json`, declaring one stdio server, `hub`, whose command is `${CLAUDE_PROJECT_DIR:-.}/hub` with argument `mcp`.
  Claude Code reads project-scoped servers only from `.mcp.json` (`.claude/settings.json` can approve them but not
  declare them), and only from the directory the session starts in, not from `--add-dir` folders. Every developer of
  the hub gets the same server. Locally each developer approves it once, as Claude Code asks for any project server;
  the managed settings do not pre-approve it, because a committed project setting cannot approve its own repo's
  servers in an untrusted folder. A cloud session opened on the hub alone loads it without a prompt, as headless runs
  do; whether a multi-repo cloud session loads it is not documented, and the hub's hooks do not load there either
  (AGENTS.project.md). The app repos get no MCP configuration: an agent that opens only a code repo still does not
  receive the brain (Defined directions 2).

### Out of scope

Central hosting, Postgres, accounts, sharing transcripts, embeddings. A later move to hosted replaces only where the
index is stored; nothing is lost because Git stays the source.

### Consequences

- Good: an agent finds a decision, a playbook or an old feature's record by words, with its source, instead of by
  knowing the path.
- Good: `features/` can leave the agent's read path (`brain/index.md` stops pointing there) and still be one search
  away.
- Good: a learning reaches the owner as a pull request on its own; the inbox stops depending on someone committing it.
- Good: nothing new to run or host; the index is per developer and disposable.
- Bad: the database now holds the text of hub and docs files, not only metadata (as item versions already do since ADR
  0039). It is derived from files the developer already has, and `hub brain reindex` or deleting the database removes
  it; transcripts and session content never enter it.
- Bad: each developer's index is only as fresh as their checkout; two developers can get different results until both
  pull.
- Bad: `./hub mcp` starts through `uvx`; the first start after a `platform.version` bump downloads the release and may
  be slow enough for Claude Code to report the server as failed until it is cached.
- Bad: full-text search misses synonyms and paraphrases; embeddings stay an open option.

## More Information

[SPEC](../SPEC.md) "Defined directions" 5, "Knowledge" view and the command list; AGH-388 (epic), AGH-389 (this ADR),
AGH-391 (index and `hub search`), AGH-392 (`hub mcp`), AGH-393 (knowledge view).
