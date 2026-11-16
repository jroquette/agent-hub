# 0011. Hub templates as package data in a generator package

- Status: accepted
- Date: 2026-09-28
- Deciders: José Henrique Roquette

## Context and Problem Statement

`hub init` and `hub sync` render a hub from a set of generic templates: the base workflow plugin, the base rules
(`AGENTS.md`, `CLAUDE.md`), the base hooks, the Makefile, the CI workflow and the brain skeleton. These templates are
what the platform ships; only project-owned material (brain content, project rules, project workflows, the project
plugin) stays in each hub (SPEC "Defined directions" 2). The templates must be versioned and tested under agent-hub's
gates and must reach the installed `hub` command. The architecture already fixes that `core` holds use cases and
ports, adapter packages implement them, and `cli` is the only composition root
([ADR 0002](0002-lean-hexagonal-architecture.md), [ADR 0008](0008-cli-as-composition-root.md)). Where do the templates
and the code that renders and writes them live, and how do they ship?

## Considered Options

- **A new package `packages/generator`** (`agent-hub-generator`, `agent_hub.generator`) holding the templates as
  package data, the renderer and the file adapter.
- **Templates inside `agent_hub.cli`**, next to the commands.
- **A separate templates repository**, fetched by the CLI at a pinned revision.
- **Reading the templates from an existing hub**, treating one hub as the reference copy.

Two sub-choices go with it: the renderer (the standard library or **Jinja2**), and whether the template source and the
hub file tree sit behind **new core ports** (`TemplateSource`, `HubTree`) or are plain adapter code.

## Decision Outcome

Chosen option: **a new package `packages/generator`**, because the templates then ship inside a wheel that is built,
tested and versioned with the rest of the workspace, and `cli` stays a thin composition root.

- The templates are package data under `agent_hub.generator`, read with `importlib.resources`, never with paths relative
  to the source tree. A test builds the wheel and proves that the non-`.py` files are inside it.
- Split by layer:
  - `core` holds the `HubConfig` model ([ADR 0010](0010-hub-json-config-contract.md)), the pure planners for sync and
    adopt (render, lock and disk state in; a list of writes, skips and conflicts out) and the doctor rules.
  - `generator` holds the templates, the renderer, and the adapter that reads the hub tree and applies a plan to disk.
  - `cli` runs the pipeline, as ADR 0008 prescribes: it calls `generator` to render the templates and read the disk,
    passes that plain data to the core planner, then hands the resulting plan to `generator` to apply. Core never
    calls `generator`, and no port is involved.
- No new port. The planners are pure functions over plain data, and nothing expects to swap the template source or the
  file system, so ADR 0002's rule (a port only where a swap is expected) is kept as written. If a second template
  source appears later, a port is introduced then, with its own ADR.
- Rendering uses the standard library, so the output is deterministic and no new dependency is added. JSON files are
  built as dicts in code and serialized with sorted keys. Text files use a `string.Template` subclass whose delimiter
  is `@@` (placeholders `@@name` or `@@{name}`), because the plain `$` delimiter collides with text the templates must
  keep verbatim: `$(MAKE)` in the Makefile, `${{ … }}` in CI workflows and `$HOME` in shell scripts. Rendering always
  calls `substitute`, never `safe_substitute`, so an unknown or misspelled placeholder fails the render. A unit test
  renders every template for the synthetic project and asserts that no unresolved placeholder (the `@@name` or
  `@@{name}` pattern) is left in the output; a literal `@@` in a template is written `@@@@`.
- The new package joins the independent sibling layer below `cli` in the `.importlinter` layers contract
  (`agent_hub.storage | agent_hub.collector | agent_hub.generator`) and is added to the forbidden list of core. This
  extends ADR 0008 without superseding it: its rule (`cli` wires, siblings never import each other) is unchanged, and
  registering a package is the routine step described in [ARCHITECTURE.md](../ARCHITECTURE.md) ("Adding a package").

### Consequences

- Good: a template change is a normal code change: reviewed, covered by the synthetic generation tests, released with
  a tag ([ADR 0013](0013-release-by-git-tags.md)).
- Good: the planners are unit-tested in core with in-memory inputs; only the adapter touches the disk.
- Good: no hub content is copied into agent-hub; generation tests use a synthetic project.
- Bad: one more distribution to register in `mypy.ini`, both import contracts and the coverage list.
- Bad: `string.Template` has no loops or conditionals; files that vary by module are chosen in code, not in the
  template text, which moves some logic out of the templates.
- Neutral: templates inside `cli` were rejected because they would make the composition root carry product content
  and grow with every template; a separate repository was rejected because it splits one release into two versions
  that must be kept in step; reading templates from an existing hub was rejected because it makes one project's hub
  the product and puts project-owned files at risk of leaking into other hubs. Jinja2 was rejected as a dependency the
  template set does not need. New ports for the template source and the hub tree were rejected because nothing swaps
  them; they would need a superseding ADR for ADR 0002 and add indirection to a pipeline of plain data.

## More Information

- [design/hub-generator.md](../design/hub-generator.md): the template classification, rendering and the sync steps.
- [ADR 0009](0009-hub-sync-by-file-ownership.md): managed and seeded files and `hub.lock`.
