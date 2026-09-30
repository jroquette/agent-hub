# Design docs

One file per subject. For a task, open the one file it touches plus the ADRs that file links; do not read them all.
The product and its phases are in [SPEC.md](../SPEC.md). Phase 1 is designed as contracts; Phases 2 to 4 are sketches.

| File | Subject | Load it when |
|---|---|---|
| [project-config.md](project-config.md) | the `hub.json` contract: fields, validation, versioning, readers, tracker | a change reads or adds a config key |
| [hub-generator.md](hub-generator.md) | `hub init`, `hub sync`, `--adopt`, `hub.lock`, plugin and hooks, commands, releases | generating or syncing hub files, a hook, a `hub` command that replaces a script |
| [hub-doctor.md](hub-doctor.md) | the `hub doctor` rule interface, rule set, output and exit codes | adding or tuning a check |
| [domain-model.md](domain-model.md) | the nine entities: identity, attributes, relations, phase (sketch) | modeling an entity in core; for Session, WorkflowRun or Learning read [event-derivations.md](event-derivations.md) too |
| [event-derivations.md](event-derivations.md) | how Session, WorkflowRun and Learning are folded from events, and what events may hold (sketch) | a derived entity (with [domain-model.md](domain-model.md)), a projection or a view over events; a source adapter: its "Sources and privacy" part (redaction before append) and the SPEC's [canonical event](../SPEC.md#data-sources-and-event-model) |
| [workflow-schema.md](workflow-schema.md) | the declarative workflow document (sketch, Phase 4) | workflow steps, gates or the executor |

## Rules for these files

- Every subject file has exactly the sections Purpose, Contract, Invariants, Decisions and Open questions, in that
  order, and stays at or under 150 lines.
- `hub-generator.md` may reach 160 lines: it holds three commands (`hub init`, `hub sync`, `--adopt`).
- A contract is stated once, in its subject file, and linked from elsewhere. The reasons live in the ADRs.
- A sketch is rewritten as a contract when its phase starts.

## Decisions behind them

- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md): each generated file is managed or seeded; a lock guards sync.
- [ADR 0010](../adr/0010-hub-json-config-contract.md): `hub.json` stays JSON, validated by a core model and a schema.
- [ADR 0011](../adr/0011-templates-as-package-data.md): hub templates ship as package data in a generator package.
- [ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md): hub logic moves into the CLI, except the hooks.
- [ADR 0013](../adr/0013-release-by-git-tags.md): the CLI is released by semver git tags and pinned per hub.
