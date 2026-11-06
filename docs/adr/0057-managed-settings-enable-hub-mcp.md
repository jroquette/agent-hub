# 0057. The managed settings enable the `hub` MCP server, which takes effect in a trusted folder

- Status: proposed
- Date: 2026-11-06
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0044](0044-team-memory-git-source-local-index-and-hub-mcp.md), only the sentence of its
  "Configuration" bullet that reads "the managed settings do not pre-approve it, because a committed project setting
  cannot approve its own repo's servers in an untrusted folder", and only for trusted folders (the AGH-688 check
  below); the rest of ADR 0044 stands, the `.mcp.json` declaration and the untrusted-folder rule included. ADR 0044
  is not edited.

## Context and Problem Statement

[ADR 0044](0044-team-memory-git-source-local-index-and-hub-mcp.md) declares `hub mcp` in a managed `.mcp.json` and
leaves its approval to each developer: "Locally each developer approves it once, as Claude Code asks for any project
server; the managed settings do not pre-approve it, because a committed project setting cannot approve its own repo's
servers in an untrusted folder." So a local session can start without the server when the developer misses or
declines the prompt. Agents then work without the brain (AGH-688: a session read the brain with `cat` and `ls` and
never used `hub mcp`).

Claude Code's docs say a committed `enableAllProjectMcpServers` or `enabledMcpjsonServers` "is ignored in an
untrusted folder", and that approvals in user, managed or `--settings` settings still apply. They do not say what a
committed key does once the folder is trusted.

Checked on 2026-11-06 with Claude Code 2.1.318: `claude mcp list` with its own `CLAUDE_CONFIG_DIR` per case, on a
project whose `.mcp.json` declares `hub`:

| Folder | Committed `.claude/settings.json` | `hub` |
|---|---|---|
| trusted (`hasTrustDialogAccepted: true`) | `"enabledMcpjsonServers": ["hub"]` | `√ Connected` |
| untrusted | `"enabledMcpjsonServers": ["hub"]` | `⏸ Pending approval` |
| trusted | no key | `⏸ Pending approval` |

ADR 0044's reason holds for untrusted folders only. Should the managed settings enable `hub` for trusted folders?

Decision drivers:

- An agent in the hub gets `hub mcp` without a step a developer can miss.
- A cloned hub still cannot approve its own server before its folder is trusted (Claude Code's rule; nothing is
  added around it).
- No new `hub.json` field and no new module.
- `hub doctor`'s settings rules (`settings.valid`, `settings.weakening`, `permissions.bypass`, `lock.drift`) stay
  silent on a freshly synced hub.

## Considered Options

- **`"enabledMcpjsonServers": ["hub"]` in the managed `.claude/settings.json` of every hub.** It names only the
  server the managed `.mcp.json` declares.
- `"enableAllProjectMcpServers": true`. It has the same effect today, since `.mcp.json` is managed and holds only
  `hub`. But it would also approve any server a later `.mcp.json` declares, which is broader than needed.
- Keep the per-developer approval (ADR 0044 as written). Each developer approves the server once, and a missed or
  declined prompt leaves the session without the brain.
- A `hub.json` switch for the key. It adds a schema field that nothing needs today.

## Decision Outcome

Chosen option: **`"enabledMcpjsonServers": ["hub"]` in the managed `.claude/settings.json` of every hub**, because
it removes the approval step in a trusted folder, names only the managed server, and leaves untrusted folders as
they are.

- `managed_settings` (`generator/built_json.py`) adds the key, with the same server name as `.mcp.json`. No module
  and no `hub.json` field turns it on or off.
- In an untrusted folder, Claude Code ignores the key and asks as before. A session started in a trusted hub loads
  `hub mcp` with no prompt.
- `.claude/settings.project.json` merges by adding only, so a hub cannot drop `hub` from the list. A developer who
  does not want the server sets `"disabledMcpjsonServers": ["hub"]` in their own `.claude/settings.local.json`, as
  Claude Code's docs describe. This repo does not test that.

### What this supersedes

- [ADR 0044](0044-team-memory-git-source-local-index-and-hub-mcp.md), in part: in a trusted folder, the managed
  settings now enable the `hub` server. The rest of ADR 0044 stands: `.mcp.json` declares the server, an untrusted
  folder still asks, a cloud session on the hub alone loads it without a prompt, and the app repos get no MCP
  configuration.
- ADR 0044 stays unedited, as accepted ADRs are never edited.

### Consequences

- Good: a developer's local session in the hub has `search`, `read` and `propose` from the start, so the brain
  guidance in `AGENTS.md`, the skills and the server's instructions applies.
- Good: a clone that has not been trusted cannot approve the server itself.
- Bad: the effect of the key in a trusted folder comes from a check of one Claude Code version (2.1.318), not from
  the docs. If a later version changes it, the key does nothing and developers are asked again, which is the
  ADR 0044 behaviour. AGH-688's AC-7 checks it again on the release that ships it.
- Bad: a hub cannot opt out in its committed settings. Only a developer's local settings can.

## More Information

- [ADR 0044](0044-team-memory-git-source-local-index-and-hub-mcp.md): `hub mcp` and its `.mcp.json`.
- [SPEC](../SPEC.md): Defined directions 5.
- [hub-generator](../design/hub-generator.md): the `.claude/settings.json` row.
