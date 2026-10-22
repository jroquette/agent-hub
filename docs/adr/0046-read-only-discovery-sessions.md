# 0046. Read-only discovery sessions: Claude proposes environments and services

- Status: proposed
- Date: 2026-10-20
- Deciders: José Henrique Roquette
- Extends: [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md) (driving Claude Code sessions from the app)
  with a tool profile the server alone picks; [ADR 0038](0038-declared-environments-and-blocked-words.md) (declared
  environments) with a way to fill them

## Context and Problem Statement

A project declares its environments and each repo's services in `hub.json`, one by one, from the Hub config screen or
`hub env`. The facts are already in the repos (`serverless.yml`, CDK stacks, SAM templates, docker-compose files,
Terraform, `package.json` scripts, `.env.example`), but a person has to find and copy each address. Claude can read
those files, yet an ordinary session can also write, run commands and reach the network, and anything it writes into
`hub.json` would set an environment's access. How does `hub web` let Claude find the services of the picked repos
without letting it change anything, and without letting it decide what an agent may do where?

## Considered Options

1. **A read-only session that returns a proposal.** `hub web` starts a session limited to reading files; its final
   reply ends with one JSON block the server checks and the web app shows item by item; the person applies the rows
   they pick through the existing batch edit.
2. A session that may run `hub env propose` through Bash, with a command allowlist.
3. The Discuss chat only: Claude says what it found in prose.

## Decision Outcome

Chosen option: 1.

- **Tool profile.** A session carries `tool_access`, `all` (every session the browser starts) or `read_only`. Only
  the server picks `read_only` (a discovery); `POST /agent-sessions` cannot set it. A `read_only` session gets
  `Read`, `Grep` and `Glob` as its whole tool set and allowed outright (the SDK's `tools` and `allowed_tools`), every
  tool that writes, runs a command, reaches the network or starts an agent removed (`disallowed_tools`: `Bash`,
  `Edit`, `MultiEdit`, `Write`, `NotebookEdit`, `WebFetch`, `WebSearch`, `Task`, `Agent`, ...), and no MCP server
  (`strict_mcp_config`). The permission bridge denies at once, never parks, any other tool request with "This session
  can only read files.". The setting sources are unchanged, so the project's guard hooks still run. The profile is
  stored with the session, so a session reopened by a later message stays read-only. The picked repos are attached
  (`add_dirs`) so reading them needs no permission.
- **Proposal in the final reply.** The server builds the prompt (the repos and their paths, the environments to look
  for, where to look, never open `.env` files, never print a secret) and asks for one fenced JSON block at the end of
  the final reply. The server takes the last such block (at most 512 KiB), parses it strictly and checks every item
  with `hub.json`'s own shapes (names, kinds, URLs, resources, profiles, env files, secret shapes); evidence must name
  a file inside a picked repo. An invalid item or field is dropped with its reason, never the whole proposal.
- **Access from presets.** Claude names a preset (`local`, `staging`, `production`, `mine`, `other`); the server sets
  `access` and `production` from it (`write`, `ask`, `read` and production, `write`, `read`). Claude never sets access.
- **Nothing written until applied.** A discovery is one file under `<hub>/.agent-runs/env-discoveries/`; each read
  compares the proposal with the effective config of now (`new`, `differs`, `declared`). The person applies the rows
  they pick through `POST /projects/{project}/config/environments` (a batch), which checks the result as every edit is
  checked. There is no apply route.

### Consequences

- Good: services found in seconds, each with the file and line it came from; the person reviews every row.
- Good: a discovery cannot change a file, run a command or reach the network, whatever the reply says.
- Bad: no progress per repo; the screen shows "reading" until Claude's final reply.
- Bad: Claude reads code, not the cloud: an address built at deploy time is listed as missing, not found.
- Neutral: the guard still applies to the reads (a blocked word or a secret file is refused as in any session).

## More Information

- Code: `agent_hub.core.environment_discovery` (models, prompt, proposal checks, use case),
  `agent_hub.claude_sessions.options` and `permission_bridge` (the profile), `agent_hub.api.discovery_files` and
  `routes/environment_discoveries.py`.
- Option 2 was rejected: an allowlisted Bash still allows chaining and quoting tricks, and the session could run the
  write itself. Option 3 gives no per-item review and nothing the screen can apply.
