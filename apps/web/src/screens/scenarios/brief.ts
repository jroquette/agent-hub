/* What Claude reads about the scenario format before it writes or changes a scenario: the New
 * scenario form and the scenario page hand it over in the Discuss panel, and the builder's
 * Describe ends with it. Its format lines are those of the scenario's own format: a graph of
 * nodes (`version: 1`) or stages of blocks (`version: 2`). */

const FILES =
  "Scenarios are YAML files at `scenarios/<pack>/<name>.yaml` in this hub folder, with `kind: scenario`. The actions they call are `actions/<pack>/<name>.yaml`, with their scripts under `actions/<pack>/scripts/` (docs: the hub's scenarios design, ADR 0041).";

const GRAPH = [
  "A scenario is a workflow document (schema v1: `version: 1`, `kind: scenario`, `name` = the file stem, `description`, `revision: 1`, `inputs`, `nodes`) that holds only `action`, `expect`, `approval`, `wait`, `loop_group` and `include` nodes. It may declare `environment: <name>`.",
  "`action` node: `action` (`<name>` in its pack or `<pack>/<name>`), `with`, `capture` ({name: ref} → `$CTX.<name>` downstream), `retry`, `timeout`. `expect`: the same plus `every` and `timeout` (both required) and `until_when`.",
];

/** How a scenario written as blocks names a block: by its address. */
export const BLOCK_ADDRESS =
  "A block is named by its address: its stage's number, then its place in the stage, counting from 1 (`2.3`); inside a block that holds blocks, `then` or `else` for an If's lists, `p<n>` for a Together's n-th path and nothing for a Repeat's steps, then the place there (`2.3.then.1`, `2.3.p2.1`, `4.1.2`). A stage alone is its number (`2`).";

const TREE = [
  "This scenario is written as blocks: `version: 2`, `kind: scenario`, `name` = the file stem, `description`, `revision: 1`, `inputs` and `stages`, named stages of blocks in the order they run (docs: the hub's scenarios design § Tree format, ADR 0049).",
  BLOCK_ADDRESS,
];

const ACTIONS =
  'An action declares `version`, `name`, `description`, `effect` (`read`, `write`, `destroy`), `runtime` (`sh` or `python`), `script`, `timeout`, `inputs` (string, integer, number, boolean or service) and `output_format` (a JSON Schema). Its script reads one JSON object on stdin (`mode` plan|run, `inputs`, `endpoint`) and prints one JSON value; in plan mode `{"summary": "..."}`, changing nothing.';

const CHECKS =
  "Reuse the actions that already exist (`./hub action list`) before writing new ones; prefer `read` effects. Never put a credential or secret value in a file. Check the result with `./hub scenario list` (and `./hub scenario plan <name> --env <env>`) until it reports no problem. A new action stays a draft until it is committed. Then say in two or three lines what the scenario does, step by step.";

/** The brief for a scenario written as a graph, or as blocks (`tree`). */
export function scenarioBrief(tree = false): string {
  return [FILES, ...(tree ? TREE : GRAPH), ACTIONS, CHECKS].join("\n");
}

/** The brief for a scenario written as a graph (`version: 1`). */
export const SCENARIO_BRIEF = scenarioBrief();
