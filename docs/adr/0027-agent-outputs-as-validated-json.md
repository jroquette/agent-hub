# 0027. Agent outputs as validated JSON: reviewer findings and evaluator verdicts

- Status: proposed
- Date: 2026-10-14
- Deciders: José Henrique Roquette (D1-D17 of the AGH-139 spec, approved 2026-10-13, with the plan's amendments
  E1-E19; the implementation choices in "More Information" approved with the AGH-139 plan)

## Context and Problem Statement

`/feature` decides its two gates by reading prose. After each task the main session reads the spec-reviewer's
`PASS`/`FAIL` and the quality-reviewer's `APPROVE`/`CHANGES` with `blocker`/`should-fix`/`nit` lines, and after the
evaluator it reads the verdict in `evals/<delivery>.md`. Prose is not a wire format: a verdict that contradicts its own
findings (a `FAIL` with no blocking finding, a `SHIP` over a failing AC or a red gate), a finding without a path, or a
reply cut short is read as whatever the main session guesses, and nothing checks that the evaluator's body agrees with
its frontmatter. The two reviewers also use two vocabularies, which `/fix`, `/refactor` and `/review` each read
differently. What should the agents emit, who checks it, and what does `/feature` do with an output that fails?

## Considered Options

1. **A.** Pydantic models in core as the single source of truth; a core validator that checks shape and cross-field
   rules (against the feature record when there is one) and reports every violation at its JSON path; a thin CLI
   command `hub validate-output review|eval FILE`; JSON Schemas exported from the models and shipped to every hub by
   `hub sync`; files saved next to the AGH-136 records.
2. **B.** Hand-written JSON Schema files as the source of truth, validated with a runtime `jsonschema` dependency.
3. **C.** Validation only in `hub doctor --only features.outputs`.
4. JSON only in the agent's final message, nothing on disk.
5. Shape-only validation, without cross-checks.
6. Reviewers given the Write tool to save their own JSON.
7. Consumers beyond the main-session loop now: `hub web` (Eval tab, golden path), `/retro` metrics, replacing the
   records' frontmatter.

## Decision Outcome

Option 1 (A).

- **Consumer (D1):** only the `/feature` main-session loop. It parses the reviewers' and the evaluator's JSON to route
  fixes back to the implementer and to decide the review and ship gates. `hub web`, doctor read models beyond a light
  check, `/retro`, `features.json` as a schema'd output and `/review`'s flow are out of scope.
- **Files (D2):** the evaluator's `brain/features/<slug>/evals/<delivery>.json` beside `evals/<delivery>.md` (same
  delivery name, same `-rN` rule, never overwritten); the reviewers'
  `brain/features/<slug>/reviews/<ticket>/<reviewer>-r<N>.json` (`reviewer` = `spec` | `quality`, `N` = the review
  round, from 1). `/feature` acts only on validated files.
- **Writers (D3):** the reviewers stay read-only and end their reply with exactly one fenced JSON block; the main
  session saves it verbatim, runs `./hub validate-output`, and on failure re-asks that reviewer once with every
  problem line (no repair, no guessing). The evaluator (which has Write) writes its own JSON and runs the command.
- **Strictness (D4, D11):** a review `verdict` is `FAIL` iff at least one `blocking` finding. `SHIP` needs every
  in-scope AC result and every gate `pass` (and non-empty lists); `SHIP-WITH-OWNER-STEPS` needs non-empty
  `owner_steps` and may carry a failing result or gate; `SHIP` may carry `owner_steps`; `NO-SHIP` is otherwise allowed;
  `red_on_parent[].failed_on_base: false` blocks no verdict. The eval JSON's `verdict`, `delivery`, `tickets`, `acs`
  and `commit` equal its sibling `.md` frontmatter; a missing sibling is an error.
- **Source of truth (D5):** frozen, `extra="forbid"`, strictly typed pydantic models in core; no new runtime
  dependency. Each document names its schema (`"schema": "agent-hub/review/1"` / `"agent-hub/eval/1"`); a reader
  refuses a version it does not know. The exported JSON Schemas ship as core package data and are rendered verbatim,
  generic and managed, to `plugin/hub-workflow/schemas/review.v1.json` and `eval.v1.json`, locked by drift tests. They
  state shape only; the cross-checks live in the validator. The doctor's `features.tracker` rule warns (no new rule
  id) on a JSON output with no sibling record or one that fails validation. Records without JSON stay valid; nothing
  is migrated.
- **Shapes (D6):** review `{schema, reviewer, ticket, task, round, commit, verdict: PASS|FAIL, findings: [{id, kind,
  severity: blocking|minor, path, line, acs, what, expected}]}` with `kind` one of `missing, extra, test, assertion,
  contract, invariant, security, idempotency, quality`; eval `{schema, delivery,
  verdict: SHIP|SHIP-WITH-OWNER-STEPS|NO-SHIP, commit, tickets, acs (list or "all"), results: [{ac, command,
  exit_code, status: pass|fail|not-run, summary}], gates: [{repo, name, exit_code, status}], red_on_parent: [{test,
  failed_on_base}], owner_steps: [...]}`. Every key is required; sizes are bounded (512 KiB per file, list and text
  caps aligned with the AGH-136 readers). Every text field is non-empty (`minLength: 1` in the schemas): a finding's
  `what`, `expected` and `path`; an eval's `command`, `summary`, each `owner_steps` item, `red_on_parent[].test`, and
  each gate's `repo` and `name`.
- **Every violation in one run (D7, D13):** every shape violation plus every cross-check whose inputs are well formed,
  each once, as `<json path>: <message>`, in a fixed order. Core returns them all; the command prints the first 200
  and then one line `… and N more problems (T in total)`, and one re-ask or re-dispatch passes every printed line. A
  test checks that the shipped schemas are valid Draft 2020-12 schemas.
- **Unified vocabulary (D8, D16):** both reviewers report `PASS`/`FAIL` with `blocking`/`minor` findings in prose and
  JSON, `PASS` iff no `blocking` finding; `APPROVE`/`CHANGES`, `blocker`, `should-fix` and `nit` are gone. `/fix`,
  `/refactor` and `/review` read the same words; the rules that had three levels read `minor` where they said `nit`
  or `should-fix`.
- **Evaluator failures (D9, D17):** a missing or invalid eval JSON makes `/feature` re-dispatch the evaluator once with
  the same scope, the failed delivery and every problem line; the re-dispatch is a new evaluation that writes the next
  free `evals/<delivery>-rN.md` + `.json` pair, the failed pair stays as evidence, and a second failure stops with no
  ship. Within its own run the evaluator may rewrite only the `.json` it created, until the command exits 0 (D14).
- **Feature record (D10, D14):** when `../features.json` exists, `validate-output eval` expands `acs: "all"` and a
  tickets-only scope to the live ACs (a plan key and its tracker id are one ticket) and requires `results` to name
  each exactly once; a withdrawn or unknown AC in `acs` or `results` is a problem. Without a record, document-only
  checks. `hub.json` is never read. Core stays pure (bytes in, problems out); the CLI reads the files.
- **Dependencies (D12):** `jsonschema` only in the workspace dev group, for the meta-schema test.

### Consequences

- Good: a gate decision rests on a file that was checked, and can be traced to it; a self-contradicting verdict, a
  finding without a path or a truncated reply never passes.
- Good: one definition (the models) yields the validator, the shipped schemas and the docs; agents can read the
  schema in their hub, and the command needs no `hub.json`, no network and writes nothing.
- Good: one re-ask carries the full problem list, so a fix converges in one round.
- Bad: the seven templates and two schema files are managed: every hub rewrites them on its next `hub sync` after the
  release, and the reviewer vocabulary changes for every caller (`/feature`, `/fix`, `/refactor`, `/review`) at once.
- Bad: the JSON Schema states shape only; a document that validates against it can still fail `validate-output`
  (the cross-checks), so agents are told to run the command, not a schema validator.
- Bad: the evaluator's `.md` and `.json` repeat the same scope fields, kept equal by the validator, not by
  construction; hubs on older releases keep prose-only gates until they bump and sync.

## More Information

AGH-139 spec D1-D17, S1-S12 and AC-139.1 to AC-139.30, with the plan's amendments E1-E19 (notably: problem lines
printed capped at 200 plus a total; echoes cut with `cut_echo` at 80 characters; the doctor check runs only for folders
with a listed `features.json`; size bounds applied in core because the doctor hands whole bytes; every text field
non-empty).

Implementation choices recorded with the plan: the private AGH-136 helpers (AC-id, commit and `-rN` patterns, ticket
aliases, scope expansion) move to a public core module `features/scope_rules.py` without behaviour change;
`MAX_RECORD_BYTES` moves to core so the CLI and the doctor agree; the `schema` key is a field alias (as `$schema` is
in `HubConfig`); the registry names its core-sourced verbatim entries in one helper; the CLI's reads go through the
generator's file adapter, opening each name from its folder's descriptor with `O_NOFOLLOW`.

Rejected options (D15): **B** keeps two sources in sync and adds a runtime dependency to core; **C** is whole-hub,
slower and noisier per review; JSON only in the final message is lost on compaction and leaves no audit; shape-only
validation lets a self-contradicting verdict pass; Write for reviewers loosens their read-only guarantee; the other
consumers are deferred as follow-ups.

Related: [ADR 0002](0002-lean-hexagonal-architecture.md) and [ADR 0008](0008-cli-as-composition-root.md) (core is pure;
the CLI is the composition root); [ADR 0009](0009-hub-sync-by-file-ownership.md) and
[ADR 0011](0011-templates-as-package-data.md) (managed files reach hubs through `hub sync`);
[ADR 0010](0010-hub-json-config-contract.md) (the `hub.schema.json` precedent: a model exported as a shipped schema);
[ADR 0026](0026-input-brief-contract.md) (the input side of the same workflow). The workflow engine's step-output
mechanism (`docs/design/workflow-schema.md`, open question "Step outputs") stays open. Reference consulted for two
ideas only (report every violation in one run; check the schema itself before use): Archon `coleam00/archon` at
`a5834f2`, nothing copied.
