/** What Claude reads about the scenario format before it writes or changes a scenario: the New
 * scenario form and the scenario page hand it over in the Discuss panel. */
export const SCENARIO_BRIEF = [
  "Scenarios are YAML files at `scenarios/<pack>/<name>.yaml` in this hub folder, with `kind: scenario`. The actions they call are `actions/<pack>/<name>.yaml`, with their scripts under `actions/<pack>/scripts/` (docs: the hub's scenarios design, ADR 0041).",
  "A scenario is a workflow document (schema v1: `version: 1`, `kind: scenario`, `name` = the file stem, `description`, `revision: 1`, `inputs`, `nodes`) that holds only `action`, `expect`, `approval`, `wait`, `loop_group` and `include` nodes. It may declare `environment: <name>`.",
  "`action` node: `action` (`<name>` in its pack or `<pack>/<name>`), `with`, `capture` ({name: ref} → `$CTX.<name>` downstream), `retry`, `timeout`. `expect`: the same plus `every` and `timeout` (both required) and `until_when`.",
  'An action declares `version`, `name`, `description`, `effect` (`read`, `write`, `destroy`), `runtime` (`sh` or `python`), `script`, `timeout`, `inputs` (string, integer, number, boolean or service) and `output_format` (a JSON Schema). Its script reads one JSON object on stdin (`mode` plan|run, `inputs`, `endpoint`) and prints one JSON value; in plan mode `{"summary": "..."}`, changing nothing.',
  "Reuse the actions that already exist (`./hub action list`) before writing new ones; prefer `read` effects. Never put a credential or secret value in a file. Check the result with `./hub scenario list` (and `./hub scenario plan <name> --env <env>`) until it reports no problem. A new action stays a draft until it is committed. Then say in two or three lines what the scenario does, step by step.",
].join("\n");
