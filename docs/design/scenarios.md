# Scenarios: actions, scenarios and the access policy

## Purpose

How a project drives its own system through the workflow engine: **actions** (scripts with a declared effect),
**scenarios** (workflow documents of `kind: scenario`), the access policy checked before each action, credentials only
an action gets, and the two run modes. Why: [ADR 0041](../adr/0041-scenarios-actions-and-enforced-access.md). Format:
[workflow-schema.md](workflow-schema.md). Environments and `access`: [environments.md](environments.md).

## Contract

All optional and project-owned; a hub without `scenarios/`, `actions/` and `environments` behaves as before. Actions are
`actions/<pack>/<name>.yaml`, scripts under `actions/<pack>/scripts/` (by real path, no symlink); scenarios are
`scenarios/<pack>/<name>.yaml` with `kind: scenario` (each root refuses the other kind). Both load as workflows do
(strict YAML, 256 KiB, unknown keys refused, errors name file, line and key), ≤ 200 files per root. `hub init` writes
one example, each file only where absent: the read action `actions/demo/demo-get-status.yaml` (a Python script that
GETs one path of a `service` input's endpoint; plan mode prints the URL) and the scenario `demo-service-up`, written
as blocks (`version: 2`: one stage, a Wait until `/health` answers 200, then one Do, with the ids `service-up` and
`read-root`), so a fresh hub has no `scenarios.graph_format` warning. They are the project's files: `hub sync` never
adds them, `hub.lock` does not list them, and the init report does not count them.

### Kind and node keys

- `kind`: `workflow` (default: documents load as before) or `scenario`. A scenario holds only `action`, `expect`,
  `approval`, `wait`, `loop_group` and `include` nodes; any other type (an included one too) fails the load, naming it.
- `action` node: the common keys, `action` (`<name>` in its pack, or `<pack>/<name>`), `with`, `capture`, `retry`,
  `timeout`; one JSON value out. `expect`: the same, plus `every`, `timeout` (both required), `until_when`.
- `capture: {<name>: <ref>}` gives `$CTX.<name>` to downstream nodes; a name not captured upstream, or by two nodes, is
  a load error, as is `$CTX` in a capture. `$self.output[.path]` (own output) reads only in `until_when` and `capture`.
- A process workflow may declare `environment: <name>` (`--env` overrides it): `shell`, `script` take `effect` (default
  `write`), `until_bash` is a `read`, an `action` needs one. Ids ending `__ask` or `__investigation`, `self`, are reserved.

### Tree format (version 2)

**Partly built** ([ADR 0049](../adr/0049-scenario-blocks-and-run-control.md), AGH-507): core loads a `version: 2`
scenario and translates it to the node graph at load, with its block map and its problems on the tree's key paths
(the format, bounds, addresses, ids and translation below), and `generator`'s canonical YAML writer, which the API's
builder routes use: validate and Save take a `version: 2` document as well as a `version: 1` one, and Save of an
unchanged document writes nothing. Built too: doctor's `scenarios.graph_format` warning, and `hub init` seeds its
example as `version: 2`. Proposed, not built yet: `hub scenario migrate`, which that warning's fix names, and a
builder screen that edits `version: 2`. Hub web's builder reads and writes `version: 1` files only, so a `version: 2`
file, the seeded example among them, opens in Build read-only (the steps core translates it to, and its file) and is
edited as text or with Claude until the builder reads `version: 2` (see the ADR's delivery notes).

A scenario may be written as ordered blocks ([ADR 0049](../adr/0049-scenario-blocks-and-run-control.md)):
`version: 2` and `stages:` in place of `nodes:`, with `kind: scenario` (a version-2 document without it fails at
`version`; one with `nodes`, `depends_on` or `trigger_rule` fails the load; version 1 loads as before, with doctor's
`scenarios.graph_format` warning).

- A stage is `name`, optional `description`, and `steps`. Its slug is the name in lowercase, each run of other
  characters one `-`; a slug that does not start with a letter (`1. Fetch`, `Étape`), or two stages with the same
  slug, fail the load naming the stage. Position is order: a block runs after the one before it, a stage after the
  stage before it.
- A step is one of `do: <action>` with optional `with`, `capture`, `retry`, `timeout` (an `action` node),
  `wait_until: <action>` with `until`, `every`, `timeout` and optional `with`, `capture`, `retry` (an `expect` node),
  `you: <message>` with optional `decisions`, `capture_response` (an `approval`), `wait:` with `duration`, `until` or
  `attention`, and optional `options` (a `wait`) and `include: <scenario>` with `with` (an `include`). Every block takes an optional
  `description`, and every block but an If and a Together (they have no node) an optional `id`.
- A container is `repeat: {max, until, steps}` (a `loop_group`, holding no Repeat or Include), `if: <cond>` with `then`
  and an optional `else` (neither empty), or `together: [[…], […]]` (two or more paths, none empty).
- Conditions use the `when:` grammar. An If's condition must parse and holds at most 8 atoms and 1,024 characters;
  its else is its complement (each operator's opposite, `&&` and `||` swapped, expanded to or-of-ands: at most 18
  terms). An atom with a number literal over a value that is not a number skips its node rather than reading false
  (workflow-schema.md), so an If whose two branches both reach such an atom skips both, and the blocks after it.
- Bounds: at most 64 stages, containers nested 3 deep (an If in a Together in a Repeat), 512 nodes after
  translation (the cap of an expanded document), and 262,144 characters of conditions written by translation in all
  (a branch's condition counts once for each entry node it is written to). The load fails at the block whose node,
  or the If whose condition, passes a cap, and translation stops there; nothing inside a refused container is read.
- **Addresses.** A stage is `<s>` (from 1); a block in it `<s>.<n>`; inside a block, `then.<n>` and `else.<n>` (an
  If), `p<k>.<n>` (path k of a Together) and `<n>` (a Repeat's steps), e.g. `2.3`, `2.3.then.1`, `2.3.p2.1`, `4.1.2`.
- **Ids.** A block without `id` gets `<stage slug>--<address in the stage, dots as ->`: `fetch-order--2`,
  `payment--3-then-1`, `fix-shipping--1-p2-1`. A slug never holds `--`, so two derived ids never meet; an explicit
  `id` (the node id rules) that equals another block's id fails the load.
- **Translation.** Core turns the tree into nodes at load; an included version-2 scenario is translated the same way
  when the include resolver reads it, before includes are expanded. Each block has entry and exit nodes: a block's
  entry nodes depend on the exit nodes of the block before it **in the same step list**: the stages' steps form one list, in
  order, and each branch, path and Repeat body is a list of its own, whose first block depends on what its container
  depends on (a Repeat body's on nothing inside the body). An If puts
  its condition on every entry node of the first block of `then`, and the complement on those of `else`; when such
  an entry node already carries a condition (an If or a Together inside the branch), the two are joined by
  distributing `&&` over the or-of-ands form, at most 64 terms. The If's exit nodes are both branches' last nodes,
  or, with no `else`, the last node of `then` and the exit nodes of the block before the If in its list; so an If
  with no `else` must not be the first block of a list: not the scenario's first block, nor the first of a branch, a
  path or a Repeat body (write the `else`, or put a block before it). A Together's paths start on the previous block
  and its exit nodes are each path's last node. The block after an If, or after a Together a path of which ends with
  one, takes `trigger_rule: none_failed_min_one_success` (a run may skip some of their exit nodes). The **block map**
  gives each address its kind, label, node ids (a Repeat body's as recorded, `<group>__<id>`), entry nodes (in a
  run's plan, the `<step>__ask` gate in front of a gated step and an include's first nodes), exit nodes and key path.
  A problem on a generated node, at load or by planning, is reported on the tree's key path; one on a joined
  condition, on the `if` of the If whose condition holds the reference it names. The scenario plan's problems
  (`hub scenario plan|run`) name the block, `block <address> (<key path>)`, as `block 1.2 (stages[0].steps[1].until)`,
  never a generated node id; one on an If's condition names the If once, as `block 1.2 (stages[0].steps[1].if)`,
  though the condition is on each branch's first node.
- **Canonical YAML**, written by `generator`'s scenario writer (`scenario_yaml.render_document`) and shared by hub
  web's Save and `hub scenario migrate`: PyYAML's safe dumper (no key sorting, Unicode kept, width 100, so a long
  `until` folds; a text the strict loader would read as a JSON number, boolean or null, such as `1e5`, is put in
  quotes), with keys in this order: `version`, `kind`, `name`, `revision`, `description`, `inputs`, `stages`; a stage's
  `name`, `description`, `steps`; a step's kind key first, then `id`, `description`, `with`, the kind's own keys
  (`until`, `every`, `timeout`; `decisions`, `capture_response`; `max`, `until`, `steps`; `then`, `else`), `capture`,
  `retry`; any other key after them, in the order given. A `version: 1` graph keeps its order: `version`, `kind`,
  `name`, `revision`, `description`, `environment`, the other keys, `nodes` last, and a node's `id`, `type`,
  `description`, `depends_on`, `when`, `trigger_rule` first. Save writes nothing, and keeps `revision`, when the
  canonical bytes with the file's own `revision` equal the file's.
- `hub scenario migrate [NAME…] [--check]` writes a graph scenario as a tree (one stage named after the scenario, each
  id kept as `id:` where it differs from the derived one) when the graph is series-parallel with only `all_success`
  joins, `when` branches and the joins an If makes; otherwise nothing is written and each node it cannot map is named
  with why (exit 1). The new file translates to the same nodes, edges and conditions. hub web's builder opens a graph
  scenario read-only, with a Migrate action.

### Debugging

**Partly built** ([ADR 0049](../adr/0049-scenario-blocks-and-run-control.md), AGH-507): the engine pauses a run
before a node through its run-control port, and the resume goes on with the pass it stopped
([workflow-engine-rules.md](workflow-engine-rules.md) § Run control); core's `run_record` folds the record lines
below (the run view's debug pause, breakpoints and commands, a `debug.pause` line read back for its resume, and the
values to inspect). The CLI is built: `breakpoints.json`, `hub scenario run --break`, `break`, `step` and `continue`
(`cli/scenario_debug.py`, the run control over that file and the record), which write those lines and emit the
`debug.*` events, and the production refusal. Proposed, not built yet: the API routes, the route that reads the
values, and hub web's debugger. Today's builder reads and writes `version: 1` files and Save goes through the API
(see the ADR's delivery notes).

A scenario run may pause before a block: by a **breakpoint**, or by **Step** ([ADR
0049](../adr/0049-scenario-blocks-and-run-control.md)). It is not a gate and Approvals does not list it.

- Breakpoints are block addresses of the run's pinned tree, kept in the run folder: `breakpoints.json`
  (`{"addresses": […]}`, in the tree's declaration order), written whole (a temporary file in the run folder, then a
  rename), at most 64 KiB and 512 addresses, read as each layer of nodes starts, never through a link; a file that
  cannot be read or parsed, or names a block the tree does not hold, counts as no breakpoint and adds one
  `debug.breakpoints_unreadable` line (`reason`) per reason and process. They are set by `hub scenario run --break
  ADDR` (repeated for more), `hub scenario break RUN ADDR… [--off]` (adds or removes), `hub scenario break RUN --set
  [ADDR…]` (replaces the set; none clears it) or hub web; each prints the set written (`run <id>: breakpoints 2,
  3.1`, or `run <id>: no breakpoints`). An address the pinned tree does not hold is refused, naming it, and nothing
  is written. A change takes the breakpoints lock (`breakpoints.lock`) and, while no process runs the run, its run
  lock; one set while the run runs takes effect from the next layer of nodes (so not between the paths of a Together
  that already started). They are never in the document.
- Before a block means before its first node and before its `<step>__ask` gate; for a stage, before its first block;
  a Repeat, before the group (a body block's breakpoint pauses in every iteration); an If, before its condition is
  read; a Together, before any path. An Include is one block: nothing inside the scenario it includes takes a
  breakpoint. The pause answers no gate.
- `hub scenario step RUN` runs exactly the next leaf block (Do, Wait until, You, Wait, and an Include as one block)
  and pauses before the one after it, entering containers; the run stays in step mode until `hub scenario continue
  RUN`, which runs to the next breakpoint or the end. A gate met meanwhile pauses as before; once answered, a
  stepping run pauses before the next block. Both are resumes, recorded with who sent them (the account, refused
  when none is known, as a gate decision's approver), and only a run in a debug pause takes them; one the resume
  would refuse (a snapshot that no longer matches its `content_hash`) records nothing.
- "Next" is the order the run visits blocks: layer by layer, in declaration order inside a layer, not the order of
  the file. So a Together's paths interleave: with two blocks in each path, the Steps run `p1.1`, `p2.1`, `p1.2`,
  `p2.2`. A leaf the run visits and skips (such as the first block of a branch whose condition is false) still
  takes a Step: that Step runs nothing, and the run pauses before the leaf it visits next. Only an Include's first
  nodes pause: its other nodes run as the run reaches them, so they may run during another path's Step.
- How the run control reads that: step mode is on while the record's last `debug.command` is `step`; then each leaf
  block pauses before its entry nodes (`step`), except the leaf the Step released: the first leaf, in declaration
  order, from the block the run paused before, so a Step from before a stage, an If, a Together or a Repeat visits
  the first leaf inside it (for an If, the first leaf of `then`, which the run skips when the condition is false). A
  node pauses for a breakpoint when it is an entry node of a block the file names (the outermost such block is
  reported; in step mode a leaf's entry node pauses as `step`, at the leaf); the pause a run resumes from has taken
  up the breakpoints of every block its node enters, at that node's first visit, so a Continue from a Step into a
  Together's first path does not pause again at its second.
- A gate decision (`hub workflow approve|reject|respond`) on a gate the stopped pass left open, sent while the debug
  pause is the run's, is recorded and resumes the run as `hub workflow run --resume` does, with no `debug.command`
  line: the stopped pass goes on, then pauses on that gate, and the next `hub workflow run --resume` takes up the
  answer (a second decision is refused: the gate is already decided).
- A debug pause records its lines and event, prints `run <id>: paused before <address> (breakpoint|step)` and exits
  0. A version-1 run has no block addresses: `--break`, `break`, `step` and `continue` refuse it.
- With a breakpoint or step mode on, a layer holding a block to pause at runs one node at a time in declaration
  order; without either, the engine runs as before. A pause changes when a run stops, never what it does: Step and
  Continue go on with the pass the pause stopped, so a block that failed is not run again
  ([workflow-engine-rules.md](workflow-engine-rules.md) § Run control).
- While a run is paused, hub web may read its inputs (the effective ones, environment values included) and each
  finished block's rendered inputs, status and last output (a Wait until's last poll and its count), from its record,
  through a route that needs the launch cookie; never for a run on a `production: true` environment.
- Breakpoints, Step, Continue and a start with breakpoints are refused, recording nothing, when the run's environment
  is `production: true` in the effective config as read at that moment; clearing breakpoints (a change that leaves
  none) and cancelling a run stay allowed. A run that resumes there (an approval, `hub workflow run --resume`) gets no
  run control: no breakpoint or step mode pauses it, though it still goes on with a pass a debug pause stopped. Runs
  without breakpoints keep the policy above there.
- Nothing is rewound: no captured value is edited, no finished block re-run or skipped.
- Record lines (`records.jsonl`, folded by core's `run_record`): `debug.breakpoints` (`addresses`, the set as written;
  the latest line holds the run's breakpoints); `debug.breakpoints_unreadable` (`reason`: why the file counted as no
  breakpoint); `debug.pause` (`node`, `block`, `reason` `breakpoint` or `step`,
  `number` from 1 in the run, then what the resume goes on with: `pass` (`layer`, `ends` and `before` by node with
  `state`, `output` and an end's `skip_cause`, `origin`, `failure_kind`, `changed`, `stale`, `gate`) and `gates` (each
  open gate's `attempt` and `due`); held groups stay in the `held` line written beside it); `debug.command` (`command`
  `step` or `continue`, `approver`, and the `node` and `number` of the pause it resumes). A pause is the run's while no
  `resume`, `start` or `end` line follows it: then the debugger is why the run is paused, not a gate an earlier pass
  left open (no investigation is open), and a resume rebuilds the stopped pass from that line, so it goes on exactly
  as the run would have without leaving the process. A `debug.pause` line that cannot be read refuses the resume.
- The values to inspect are read from lines the record already holds: the `inputs` line, and for each node with an
  end its last `step_end` (`status`, `output`; a `prior_success` reuse keeps the end it reused), the `inputs` of its
  last `action` line, and for an expect its polls (its `action_start` lines with a `poll`, as the engine counts them)
  and the last `expect.poll` line's `output`.

### Actions and the script contract

An action declares `version`, `name` (its file stem), `description`, `effect` (`read`, `write`, `destroy`), `runtime`
(`sh`, or `python` run by `uv run`), `script`, `timeout` (≤ 1 h, default 5 m), `inputs` and `output_format` (a JSON
Schema). An input is `string`, `integer`, `number`, `boolean` or `service`; a `service` value names a service in
`repos[].services`, resolved to its endpoint in the bound environment (none: `plan` fails naming both). The script reads
one JSON object on stdin, `{"mode": "plan" | "run", "inputs": {…}, "endpoint": {"<input>": {"url": …, "resource": …}}}`,
and prints one JSON value: in `run` mode the output matching `output_format` (else the step fails `output_contract`); in
`plan` mode `{"summary": "<one line>"}`, changing nothing, with no credential. An action is **committed** when its
document, script and its pack's other `scripts/` files (no other action's script, `__pycache__` or dot name) each match
the hub's `HEAD` (a local commit suffices); else it is a **draft**, listed but never run (outside a git checkout, all
are). A run pins each action's `content_hash` (`sha256:` over each file's path, length, bytes) and runs that snapshot.

**Run values.** A scenario input is a value of the run, set once when it starts. An action input a step leaves out of its
`with` takes the scenario input of the same name, at plan and at run time (`with_run_values`); a value the step gives
always wins, and an input with neither, or whose run value is empty (an optional input with no default), takes the
action's default. Included steps take the run's own inputs too: an include's `with` reaches only the `$INPUTS`
references written in the included steps, so a child step that should take the include's value names it in its
`with`. So a value every step needs (an
account, a stack name) is declared once as a scenario input, not repeated as `name: $INPUTS.name` in each step, and one
run cannot start in one account and end in another. The builder shows such an input as "from the run" and offers to
drop the repeats.

### Policy

`decide(effective access, production, effect, origin)` in core returns `allow`, `ask` or `deny`; the effective access is
`hub.json`'s tightened by `hub.local.json`, so a local file never loosens a decision:

| Environment | `read` | `write` | `destroy` |
|---|---|---|---|
| not declared | deny | deny | deny |
| `production: true`, any access | allow | deny | deny |
| access `read` | allow | deny | deny |
| access `ask` | allow | ask | ask |
| access `write` | allow | allow | ask |

Origin is `author` (a committed document), `human` (a person in a terminal) or `agent` (an investigation read or a
workaround); `agent` turns an `allow` of a write or destroy into `ask`. A draft action is `deny` (`draft action: commit
it to run`). A `deny` at plan time refuses the start. An `ask` is an `approval` node the planner inserts before the step
(`<step>__ask`), approved or rejected (reject cancels) in Approvals or with `hub workflow approve|reject`. Two
gate-needing steps that do not depend on each other are a plan error naming both. The same policy applies to the
`action`, `shell` and `script` nodes of a process workflow that declares `environment`.

### Credentials

- **Inputs from the environment:** a declared scenario input the request does not give takes the value of the same
  name in the environment's `values` ([environments.md § Values](environments.md)), typed as the input declares, before
  its declared default: given input > environment value > default. Core's `with_environment_values` holds the rule;
  the CLI's `plan` and `run` and hub web's plan and start call it before the defaults are filled, so the run record
  keeps the effective inputs. Values are never secrets: credentials stay in the `env_file` below.

- An environment's `credentials` (or an endpoint's, which wins when the action's endpoints declare exactly one set; two
  differing sets are a plan problem) may name `env_file`: a dotenv file relative to the workspace holding the hub and
  its repos (`demo-api/.env.staging`), ≤ 200 characters, no `..`, `~`, leading `/` or secret shape, in `hub.json` or
  `hub.local.json` (own environments), set by `hub env add|set --env-file`; AGENTS.md and the brief never show it.
- hub web may list the file's variable **names** (`GET /projects/{project}/env-file-keys?path=`), never a value: a
  regular file of at most 64 KiB held by the hub or a declared repo by real path and reached through no link, `NAME=`
  and `export NAME=` lines (a quoted value spanning lines is skipped), at most 200 names; it also says whether git
  ignores the file there.
- One loader, shared by `hub action run` and the engine's action executor, reads it when an action starts: in the hub
  or a declared repo by real path, reached through no link, a regular file, ≤ 64 KiB and 200 variables, `NAME=value`
  lines (`#` comments, optional `export `, quotes, no interpolation). It injects **every** variable, `AWS_PROFILE` from
  `aws_profile` and the `credentials.env` names from the developer's environment into that action's process only. A
  file missing, unreadable, too large, not regular, outside the hub and its repos, behind a link or not dotenv fails
  the action before its process starts: `environment <env>: env file <path> is <reason>`, a broken line by number,
  never a value. Plan mode never reads it. Injected values (≥ 4 characters) become `<credential NAME>` in its output.
- Declared `credentials.env` names and an `AWS_PROFILE` naming a declared profile are removed from every agent session
  (hub web's driven sessions included), shell, script and `until_bash` environment.
- The guard denies, in every session, a file tool on a declared env file (by real path: a symlink or `..` is caught),
  a `Grep` or `Glob` that can reach one, and a Bash command or WebFetch URL naming one (rule `env_file`, reason `env
  file: <tool> names the env file of <env>`). Doctor's `environments.env_file` warns when a declared file is missing,
  not ignored by the git checkout that holds it, outside the hub and every declared repo, or reached through a link.

### Plan and modes

`hub scenario plan <name> --env <env> [--input k=v]… [--json]` shows each step's action, args (run-time values as
`<$CTX.<name> from <node>>`), effect, service → endpoint, content hash, draft state and decision. It calls a script in
`plan` mode, with no credential, only when all its args are known (else `runs with values known at run time`), and
starts no run-mode process, agent, event or run; exit 1 on a `deny`. A required input that no `--input`, value of the
environment or default fills exits 2, naming the input and the environment. `hub scenario run` (same arguments,
`--mode interactive|regression`, interactive by default, `--break ADDR` for a breakpoint, § Debugging) refuses a plan
problem or `deny` (exit 1, no scenario run), pins its action files and gates, labels events `workflow:
scenario:<name>`, and decides each action again as it runs.

- **Regression:** no agent, no token. A divergence (a failed action, an `expect` timeout, an output contract failure)
  fails the scenario run and prints `step <id>: <reason>`. Policy asks and `approval` nodes still pause it.
- **Interactive** (the default): a divergence of an `action` or `expect` step (not a `config` failure) pauses it at an
  investigation gate, `<step>__investigation` (`human_gate`, reason `investigation`), recorded instead of the run's end;
  independent steps run first; the CLI prints the screen's link. Past 10 investigations it fails as in regression.

### Investigation, answers and workarounds

Opening a paused run in hub web starts one session per gate (none if the hub or a declared repo is `/`, home or above), held by
a PreToolUse hook: reads only in the hub and its declared repos, never an env file, `Write` only under `actions/<pack>/`, Bash
only for `./hub action …` and `./hub scenario propose`; `hub action run --run <id>` needs an open investigation and runs only
`read` actions with its environment's env file. The agent records findings and options (a summary, `{action, with}` steps) with
`propose` (secret shapes redacted), each shown with its plan. The answer is `pick` (`--text <option id>`), `retry` or `stop`:
`hub workflow respond`, `decide` (hub web) or the Scenarios screen (Approvals sends the gate there). An option holding a `deny`,
a draft action or a plan changed since shown is refused, nothing recorded. A pick answers its steps' asks: `workaround.start`,
its actions (origin `agent`), `workaround.end`, then the diverged step as a new attempt; a failed or cut-short workaround (never
re-run) opens a new investigation. `retry` skips it; `stop` ends it `cancelled`, findings kept; nothing is rewound. `hub
scenario findings <run>` lists them; `--issue <id>` creates a tracker issue after a terminal `y` (MCP: `save_issue` only);
`--inbox <id>` writes a `brain/_inbox/` note (`provenance: agent-from-external`). A `finding-<id>.issue` marker shared with hub
web makes it once: a named issue or a running create refuses both; only a warned terminal retries a failed or unfinished one.

### Events and bounds

Metadata only ([ADR 0019](../adr/0019-metadata-only-events-and-redaction.md)), each with a `payload_keys` row:
`action.start`/`action.end` (`action`, `content_hash`, `environment`, `service`, `effect`, `origin`, `decision`,
`approver`, `status`, `failure_kind`), `policy.decision` (`action` or node, `environment`, `effect`, `origin`,
`decision`, `reason_kind`), `expect.poll` (`poll`, `held`), `context.capture` (`name`), `finding` (`finding_id`,
`step`), `workaround.start`/`workaround.end` (`workaround_id`, `option`, `steps`, `status`); `gate.request` gains
`reason`. With AGH-507, defined with their rows but emitted by nothing until the debug commands are built:
`debug.pause` (`node`, `block`, `reason`), `debug.command` (`command`, `approver`), `debug.breakpoints` (`count`). Args, outputs, captures, findings, chat stay in the run record. Bounds: `expect` `every` ≥ 5 s, `timeout` ≤ 24
h, ≤ 1000 polls (retries, resumes too); action stdout ≤ 512 KiB; plan mode ≤ 60 s; ≤ 64 `--input` values of ≤ 64 KiB; a
proposal ≤ 256 KiB, 20 findings, 5 options of ≤ 10 steps; ≤ 10 proposals per investigation; API record reads ≤ 8 MiB.

### Known limits

1. Agent nodes of a process workflow get a best-effort guard check (`environment_endpoint`); a hidden host passes.
2. The guard and the investigation hook are not a sandbox: a process outside the guarded tools can read an env file, and
   the hook judges the path it is given, not the links a recursive walk inside a root may follow.
3. A process that fakes a terminal bypasses `hub action run`'s terminal rule.
4. After a divergence, independent steps still run in that pass; a `loop_group` body step is not investigated.
5. Local only: cloud sessions have no `hub.local.json`, no env files and no credentials.
6. Policy gates (`<step>__ask`) of a process workflow run show in the run's steps but not in its graph.
7. Redaction replaces each injected value of 4 characters or more exactly as written; a shorter one, or an encoded or
   transformed form (base64 as in a Basic auth header, URL-encoded, escaped in stderr, split across strings), passes.
8. Investigation sessions run unheld with no link or run folder, or as a `resume_session_id`/`fork`; one per `hub web`.

## Invariants

- No document key and no flag turns an `ask` into an `allow`; a production write or destroy never runs.
- Credential values reach only the action's process; everything else holds names; output redaction is exact (limit 7).
- Agents run read actions only before a pick; a person picks every write. A run runs the action content it pinned.
  "Run" alone means a WorkflowRun; a scenario run is always qualified.

## Decisions

- [ADR 0049](../adr/0049-scenario-blocks-and-run-control.md): the tree format translated at load, the run-control
  port, breakpoints as run data, debugging off production only.
- [ADR 0041](../adr/0041-scenarios-actions-and-enforced-access.md): actions and scenarios on the engine, policy in
  core, env-file credentials, read-only investigation, no built-in action; partially supersedes ADR 0038 on `access`.

## Open questions

- Later deliveries: branching from a step, `observe` on `expect`, scenarios authored from a session, variations.
