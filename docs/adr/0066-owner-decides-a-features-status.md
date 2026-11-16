# 0066. The owner decides a feature's status in its record, `status.md`

- Status: proposed
- Date: 2026-11-14
- Deciders: José Henrique Roquette (validated in the playground, snapshot `20261114T171258Z`; AGH-842)
- Supersedes: nothing. It adds one file to the ones [ADR 0040](0040-hub-web-keeps-local-settings-writes-hub-files-and-runs-checks.md)
  lets `hub web` write into a hub, uncommitted.

## Context and Problem Statement

A feature's phase is derived from its records ([design/feature-records.md](../design/feature-records.md)). Some
records are never closed: an agent that stops at In Review, a plan whose tickets were never listed, owner checks
nobody will run. Such a feature stays in progress on the Features list forever, and the owner has no way to say it is
done, dropped or set aside. The Features list keeps growing with work that will not move.

Where does the owner's decision on a feature live, and how does the hub read it?

Decision drivers:

- The decision is project knowledge: it belongs in the hub, reviewed in a hub PR, like the owner's sign-off.
- The derived phase stays the default; the decision only overrides it, and can be undone.
- No new storage and no migration.

## Considered Options

1. **`brain/features/<slug>/status.md`**, written by `hub web`, uncommitted, read with the feature's records.
2. A field in the feature's `features.json`.
3. A row in `hub web`'s own database.

## Decision Outcome

Chosen option: **1**.

- **The file.** `status.md` has a frontmatter with `type: feature-status`, `feature`, `status` (`shipped`, `closed`,
  `paused` or `active`), `decided_at` and `provenance: owner`, then a heading in words and the owner's optional note
  (at most 2,000 characters). `active` reopens the feature: the file stays, so the history of the last decision is
  in git, but the derived phase speaks again.
- **The write.** `POST /features/{project}/{slug}/status` replaces the file through a fresh temporary file renamed
  over it, never through a link, and answers 204, or 404 when the feature has no folder. It is an item write, as the
  owner sign-off is (`ITEM_WRITES`): this server's `Origin`, a JSON body and the launch cookie
  ([ADR 0065](0065-shared-launch-token-file-and-one-launch-cookie-rule.md)), and 409 `hub_read_only` in the
  container. Nothing is committed: the owner opens the hub PR, as after a sign-off.
- **The read.** The feature reader reads at most 4 KiB of `status.md` beside the other records. `FeatureView` carries
  `owner_status` (the decision, its date and note; none when absent, reopened or unreadable) and `last_activity_on`
  (the newest date of the spec's `last_verified`, the evals and the decision).
- **What it changes.** On the Features list a decision wins over the derived phase: shipped and closed go to Shipped
  and closed, paused to Paused. A decided feature never counts as needing the owner, in the list or the shell's badge.
  Owner checks on finished code (an owner sign-off waiting) count as Ready to close, not as needing the owner.

### Consequences

- Good: the owner can end what the records never will, one feature at a time or several at once, and undo it.
- Good: the decision is reviewed and kept in git with the feature's other records.
- Bad: a hub checkout can hold one more kind of uncommitted file made by the app; the dialog says the file is left
  uncommitted for the next hub PR.
- Bad: the decision does not touch the tracker. A feature marked shipped may still have open tickets there.

### Why not the others

- 2: `features.json` is the agents' record of the ACs, written by agents; mixing in the owner's decision would let an
  agent overwrite it.
- 3: the decision would stay on one machine, away from the team's hub.

## More Information

- AGH-842, the playground's v0.35.1 work, part 3. Code: `core/features/owner_status.py` (`SetOwnerStatus`,
  `status_note`), `core/features/feature_status.py` (`owner_status`, `STATUS`), `api/owner_status_files.py`
  (`HubStatusWriter`), `apps/web/src/screens/features/ownerStatus.tsx`.
- Related: [ADR 0040](0040-hub-web-keeps-local-settings-writes-hub-files-and-runs-checks.md) (the owner sign-off,
  written into the hub uncommitted), [ADR 0056](0056-screen-shaped-reads.md) (the shell's needs-you count).
