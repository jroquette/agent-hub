# 0058. The knowledge index keeps a file a secret rule matches, redacted, instead of skipping it

- Status: proposed
- Date: 2026-11-07
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0044](0044-team-memory-git-source-local-index-and-hub-mcp.md), only the sentence of its
  "A derived local index" section that reads "A file that matches a secret rule of the guard is skipped and reported
  by path, never indexed", and the same rule for `read`; the rest of ADR 0044 stands, `propose`'s refusal of a text
  with a secret included. ADR 0044 is not edited.

## Context and Problem Statement

[ADR 0044](0044-team-memory-git-source-local-index-and-hub-mcp.md) skips any file in which a secret rule matches.
AGH-391 took that rule to be the redaction set `r1` (`has_secret_match`: a file matches when `redact_text` would change
it), and AGH-392 made `hub mcp`'s `read` refuse the same files. `r1` accepts false positives (D9): it is built to
redact event payloads, where a false positive costs a few characters.

In a whole document, a false positive costs the whole file. Measured on 2026-11-06 in this project's workspace (886
Markdown files listed): 28 files were skipped for a secret rule, 1 for its size. Every one of the 28 was a false
positive, among them:

| File | What the rule matched |
|---|---|
| `agent-hub/docs/SPEC.md` (read before any task) | `?token=<token>`, `scheme://user:pass@` |
| `agent-hub/docs/API.md`, ADR 0031 | `?token=<token>` |
| `brain/playbooks/cloud-and-local.md` (the only playbook) | `GH_TOKEN=<fine-grained` |
| feature records | `tokenize='porter unicode61 …'`, `postgres://u:pw@`, `alice:s3cr3t@`, `lin_api_synthetic`, `TOKEN=hunter2-fixture-value` |

So `search` never returned SPEC.md and `read` answered `read: matches a secret rule` for it. Event ingestion uses the
same rules but keeps the event, with each match replaced by `[redacted: <kind>]` (ADR 0019, SPEC "Privacy").

How should the index treat a file in which a secret rule matches?

Decision drivers:

- No secret is stored in the index or served by `read`.
- A placeholder or a synthetic example never hides a whole document.
- The redaction rules stay the same for every use: one rule set `r1`, no exemption list to keep up.
- `propose` keeps refusing a text with a secret: it writes to Git, where a marker would be a wrong edit.

## Considered Options

- **Index and serve the redacted text**, as ingestion does: each match becomes its `[redacted: <kind>]` marker, and
  every field of the row comes from that text.
- Exempt obvious placeholders for docs only (`<…>` values, `user:pass` examples, known synthetic prefixes) and keep
  skipping a file on any other match.
- Keep skipping (ADR 0044 as written).

## Decision Outcome

Chosen option: **index and serve the redacted text**, because it is the only option that keeps every secret out of
the index and never drops a whole document.

The exemption option fails on today's files. Among the 28 files' matches, `alice:s3cr3t@`, `abc_123`,
`TOKEN=hunter2-fixture-value`, `GH_TOKEN=fake-token-value` and `sk-ant-api03-SYNTHETIC` have the shape of real
secrets. Exempting them would weaken the rules for real tokens; not exempting them keeps their files out. Each new
example in a doc would also need a new exemption.

- `document_rules.document_text` decodes the file and runs `redact_text` (`r1`) on it. `document_from` builds the
  title, the frontmatter's status and provenance, the body, the links and the `sha256` from that text. Without a
  match the text equals the file's, and so does the hash.
- A file is skipped only when it is over 256 KiB, not UTF-8, reached through a link, not a regular file or unreadable.
  The reason "matches a secret rule" no longer exists in the index.
- `hub mcp`'s `read` returns the same redacted text, so `read` and `search` still agree on what a file holds.
- `INDEX_VERSION` moves from 2 to 3, so the first search after the upgrade rebuilds every hub's rows and reads again
  the files that were skipped.
- `propose` and item versions keep `has_secret_match` as a gate: both write or restore files, where a marker would
  change their content.

### What this supersedes

- [ADR 0044](0044-team-memory-git-source-local-index-and-hub-mcp.md), in part: a file a secret rule matches is
  indexed with its matches redacted, and `read` returns that text. The rest of ADR 0044 stands: what is indexed, the
  other file rules, freshness, search, `hub mcp` and `propose`'s refusal of a secret.
- ADR 0044 stays unedited, as accepted ADRs are never edited.

### Consequences

- Good: SPEC.md, API.md, the playbook and the feature records are found by `search` and returned by `read`.
- Good: one rule set for events and the index, so the SPEC states one privacy rule for both.
- Good: rotating a token in a doc changes nothing the index stores (same redacted text, same hash), so the sync only
  moves the fingerprint.
- Bad: `read` no longer returns a file exactly as it is on disk when a rule matched: a placeholder such as
  `?token=<token>` comes back as `?token=[redacted: secret]`. An agent that needs the exact text reads the file from
  the checkout.
- Bad: a marker in the frontmatter reads as a YAML list, so that field (a status, a provenance) is dropped.
- Neutral: a marker can be longer than what it replaces, so the stored text can be slightly over 256 KiB.

## More Information

- [ADR 0019](0019-metadata-only-events-and-redaction.md): `r1` and redaction at ingestion.
- [ADR 0044](0044-team-memory-git-source-local-index-and-hub-mcp.md): the knowledge index and `hub mcp`.
- [SPEC](../SPEC.md): "Search and team memory" and "Privacy: metadata only, redacted".
- AGH-696: the issue, with the measurement above.
