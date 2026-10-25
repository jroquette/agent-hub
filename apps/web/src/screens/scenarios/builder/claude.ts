import { SCENARIO_BRIEF } from "../brief";
import type { LibraryAction } from "./useScenarioDraft";

/* What the builder asks Claude, through the Discuss panel (the owner's click sends it; nothing
 * talks to an agent on its own). Claude only ever proposes: a scenario proposal goes into a file
 * the builder reads and shows as suggested blocks, never into the scenario file; a new action is
 * written as a draft that never runs until the owner commits it. */

export type DescribeScope = "whole" | "after";

function library(actions: readonly LibraryAction[]): string {
  if (actions.length === 0) return "The hub has no actions yet.";
  return [
    "The hub's actions (reuse them before writing new ones):",
    ...actions.map(
      (item) =>
        `- ${item.action.ref} (${item.action.effect ?? "?"}${item.action.draft ? ", draft" : ""}): ${item.action.description ?? ""}; inputs: ${
          item.action.inputs
            .map((input) => `${input.name}${input.required ? "*" : ""}:${input.type}`)
            .join(", ") || "none"
        }; output fields: ${item.output_fields.map((field) => field.path).join(", ") || "none"}`,
    ),
  ].join("\n");
}

/** Abstracts a description in the owner's words into the scenario structure, as a proposal. */
export function describeMessage({
  text,
  scope,
  after,
  scenario,
  pack,
  draftYaml,
  proposalPath,
  actions,
  tree = false,
}: {
  text: string;
  scope: DescribeScope;
  /** The block the new steps go after (scope "after"): a step's id in a graph, a block's
   * address in a scenario written as blocks; null for the end. */
  after: string | null;
  scenario: string;
  pack: string;
  draftYaml: string;
  proposalPath: string;
  actions: readonly LibraryAction[];
  /** The scenario is written as blocks (`version: 2`, stages), not as a graph of nodes. */
  tree?: boolean;
}): string {
  const at = after
    ? tree
      ? `right after block ${after}`
      : `right after the step \`${after}\``
    : "at the end";
  const where =
    scope === "whole"
      ? "Turn it into the whole scenario: replace the steps below with the flow it describes."
      : `Turn it into new steps ${at}; keep every other step as it is.`;
  return [
    `I describe what the scenario \`${scenario}\` (pack \`${pack}\`) should do, in my own words:`,
    "",
    "<description>",
    text,
    "</description>",
    "",
    where,
    "",
    "Abstract it into our scenario structure:",
    ...(tree ? treeStructure(pack) : graphStructure(pack)),
    "",
    library(actions),
    "",
    "The scenario as it is in the builder now (unsaved changes included):",
    "```yaml",
    draftYaml.trim(),
    "```",
    "",
    `Write your proposal, the WHOLE scenario document ${tree ? "(version: 2, kind: scenario, name, description, inputs, stages)" : "(version, kind: scenario, name, description, inputs, nodes)"}, to \`${proposalPath}\` in this hub folder. Do NOT write \`scenarios/${pack}/${scenario}.yaml\`: I review your proposal in the builder, block by block, and save it myself. Then answer in a few lines: the steps you made, the actions you reused, and the new draft actions you wrote (they need a commit before they can run).`,
    "",
    SCENARIO_BRIEF,
  ].join("\n");
}

/** The structure of a graph scenario (`version: 1`), as the prompt teaches it. */
function graphStructure(pack: string): string[] {
  return [
    '- One step per thing that happens. A message to a queue, an API call, a DB change or a script in a container is an `action` step; "wait until X is Y" or "check that X" is an `expect` step (a read action polled `every` until `until_when` holds, up to `timeout`); something I do by hand is an `approval` step (set `capture_response: true` when I type a value back, such as an id, and read it later as `$<step>.output.text`); a fixed pause is a `wait` with `duration`; "run X until Y" is a `loop_group` with `max_iterations` and `until_when`; "if approved … otherwise …" is two steps after the same one, each with a `when` (the second with the condition negated), and the step after both gets `trigger_rule: none_failed_min_one_success`.',
    "- Values that later steps need are kept with `capture: {name: $self.output.<field>}` and read as `$CTX.<name>`; scenario inputs (ids, environments' services) go in `inputs` and are read as `$INPUTS.<name>`.",
    "- Use kebab-case ids that say what the step does (`send-message`, `record-processed`).",
    reuse(pack),
  ];
}

/** The structure of a scenario written as blocks (`version: 2`), as the prompt teaches it. */
function treeStructure(pack: string): string[] {
  return [
    "- The scenario is `version: 2` with `stages`: an ordered list of named stages (`name`, optional `description`, `steps`), each an ordered list of blocks. Position is order: a block runs after the one before it, a stage after the stage before it. No `nodes`, `depends_on`, `trigger_rule` or `when`.",
    '- One block per thing that happens, each one key: `do: <action>` with `with`, `capture`, `retry`, `timeout` (a message to a queue, an API call, a DB change, a script in a container); `wait_until: <read action>` with `until`, `every`, `timeout` ("wait until X is Y", "check that X"); `you: <what to do by hand>` with `decisions` and `capture_response: true` when I type a value back (read later as `$<id>.output.text`); `wait: {duration: 30s}` for a fixed pause; `include: <scenario>` with `with`.',
    '- Blocks that hold blocks: `repeat: {max, until, steps}` ("run X until Y", no Repeat inside a Repeat); `if: <condition>` with `then` and an optional `else` (its complement, computed for you; an If with no `else` never opens a list of blocks); `together: [[...], [...]]` for paths at the same time, joined by the next block.',
    "- Values that later blocks need are kept with `capture: {name: $self.output.<field>}` and read as `$CTX.<name>`; scenario inputs (ids, environments' services) go in `inputs` and are read as `$INPUTS.<name>`.",
    "- Give a block an `id` (kebab-case) only when another block reads its output (`$<id>.output.<field>`, a Repeat's `until`); without one it gets an id from its place.",
    reuse(pack),
  ];
}

function reuse(pack: string): string {
  return (
    "- Reuse the hub's actions below. When none fits, write a new action as a draft in `actions/" +
    pack +
    "/` (its YAML and its script under `scripts/`, following the plan/run contract), and use it."
  );
}

/** Writes one new action, as a draft, for a step of the scenario. */
export function createActionMessage({
  text,
  pack,
  step,
  readOnly,
}: {
  text: string;
  pack: string;
  step: string | null;
  readOnly: boolean;
}): string {
  return [
    `Write a new action in \`actions/${pack}/\` for ${step ? `the step \`${step}\` of this scenario` : "this scenario"}:`,
    "",
    "<description>",
    text,
    "</description>",
    "",
    readOnly
      ? "It only reads (effect: read): a check polls it until a state holds, so it prints the fields the check compares."
      : "Pick its effect honestly: read (only reads), write (changes data) or destroy (deletes or replaces data).",
    'Write its YAML (version 1, name = the file stem, description, effect, runtime python or sh, script under scripts/, timeout, inputs, output_format as a JSON Schema object with the fields it prints) and its script. The script reads one JSON object on stdin ({mode: plan|run, inputs, endpoint}); in plan mode it prints {"summary": "<one line>"} and changes nothing (no credential is available); in run mode it does the work and prints one JSON value matching output_format. Never put a secret in a file: credentials come from the environment\'s env file at run time.',
    "Check it loads with `./hub action list`. It stays a draft until I commit it. Answer with its name, effect, inputs and output fields.",
  ].join("\n");
}
