/* A scenario as a block program (the builder's Scratch-like view): stacks of blocks, where a block
 * snapped under another waits for it, and C-blocks that hold other blocks: Repeat (a
 * `loop_group`), If / else (the engine's `when` on the first block of each path, the else path
 * the condition negated, and the blocks after it joining with `none_failed_min_one_success`) and
 * At the same time (sibling paths that start together, joined by the next block).
 *
 * A graph scenario (`version: 1`): the program is a reading of the document, not a second
 * format: `programOf` reads the `nodes` of a scenario into a program, `nodesOf` writes a program
 * back to `nodes`, and nothing else is stored. What the blocks cannot show (a graph that is not
 * nested paths) stays as loose blocks, as written.
 *
 * A scenario written as blocks (`version: 2`, docs/design/scenarios.md § Tree format): its
 * `stages` are the program itself. `stagesOf` reads each stage and each step straight into an
 * item keyed by its block address (`2`, `2.3`, `2.3.then.1`, `2.3.p2.1`, `4.1.2`), and `treeOf`
 * writes them back, so no block is left loose and the same file gives the same keys. A block's
 * node carries the id it runs under: its own `id`, or the one its place gives
 * (`<stage slug>--<address in the stage>`), which is never written. */

import {
  dependsOn,
  formatCondition,
  parseCondition,
  without,
  type BuilderNode,
  type ConditionRow,
  type Json,
} from "./model";

/** A block of a program. In a scenario written as blocks every item has a `key` (its address),
 * `named` says whether a node's id is the block's own (written) or its place's, and `extra` holds
 * the keys of an If, a Together or a stage the builder does not edit (a `description`). */
export type Item =
  | { kind: "block"; node: BuilderNode; key?: string; named?: boolean }
  | { kind: "repeat"; node: BuilderNode; body: Item[]; key?: string; named?: boolean }
  | {
      kind: "if";
      key: string;
      condition: string;
      then: Item[];
      otherwise: Item[];
      extra?: Record<string, Json>;
    }
  | { kind: "parallel"; key: string; lanes: Item[][]; extra?: Record<string, Json> }
  | { kind: "stage"; key: string; name: string; steps: Item[]; extra?: Record<string, Json> };

/** A stage of a scenario written as blocks. */
export type StageItem = Extract<Item, { kind: "stage" }>;

export interface Program {
  main: Item[];
  /** Blocks the program cannot place (connected in a way nested paths do not show). */
  loose: BuilderNode[];
}

export const JOIN_RULE = "none_failed_min_one_success";

let counter = 0;
/** A key for a C-block that has no node of its own (an If or At the same time). */
export function freshKey(prefix: string): string {
  counter += 1;
  return `${prefix}-${String(counter)}`;
}

const NEGATE: Readonly<Record<string, string>> = {
  "==": "!=",
  "!=": "==",
  ">": "<=",
  "<=": ">",
  "<": ">=",
  ">=": "<",
};

/** The condition that holds exactly when `condition` does not (De Morgan, kept in the grammar's
 * or-of-ands shape); null when it is not in that shape. */
export function negateCondition(condition: string): string | null {
  const groups = parseCondition(condition);
  if (groups === null || groups.length === 0) return null;
  // not (g1 or g2 …) = (not g1) and (not g2) …; not (a and b) = (not a) or (not b). Distribute.
  const negated: ConditionRow[][] = groups.map((group) =>
    group.map((row) => ({ ...row, op: NEGATE[row.op] ?? row.op })),
  );
  let result: ConditionRow[][] = [[]];
  for (const choices of negated) {
    result = result.flatMap((partial) => choices.map((row) => [...partial, row]));
  }
  return formatCondition(result);
}

function same(a: string | null | undefined, b: string | null | undefined): boolean {
  const norm = (text: string | null | undefined) => (text ?? "").replace(/\s+/g, " ").trim();
  return norm(a) !== "" && norm(a) === norm(b);
}

function key(ids: readonly string[]): string {
  return [...ids].sort().join("\u0000");
}

/** Reads `nodes` (one level: the top or a repeat's body) as a program. */
export function programOf(nodes: readonly BuilderNode[]): Program {
  const used = new Set<string>();
  const byDeps = new Map<string, BuilderNode[]>();
  for (const node of nodes) {
    const k = key(dependsOn(node));
    byDeps.set(k, [...(byDeps.get(k) ?? []), node]);
  }
  const childrenOf = (after: readonly string[]) =>
    (byDeps.get(key(after)) ?? []).filter((node) => !used.has(node.id));

  const read = (after: readonly string[], depth: number): { items: Item[]; tails: string[] } => {
    const items: Item[] = [];
    let tails = [...after];
    for (let guard = 0; guard < 500 && depth < 40; guard += 1) {
      const children = childrenOf(tails);
      if (children.length === 0) break;
      const [first, second] = children;
      if (children.length === 1 && first && !hasWhen(first)) {
        used.add(first.id);
        items.push(itemOf(first));
        tails = [first.id];
        continue;
      }
      if (children.length <= 2 && first && hasWhen(first)) {
        const elseNode =
          second && hasWhen(second) && same(negateCondition(text(first.when)), text(second.when))
            ? second
            : null;
        if (children.length === 1 || elseNode) {
          const condition = text(first.when);
          const thenPath = readPath(first, depth);
          const elsePath = elseNode ? readPath(elseNode, depth) : { items: [], tails };
          items.push({
            kind: "if",
            key: freshKey("if"),
            condition,
            then: thenPath.items,
            otherwise: elsePath.items,
          });
          tails = [...new Set([...thenPath.tails, ...elsePath.tails])];
          continue;
        }
      }
      // At the same time: every child starts a path; the next block waits for all their ends.
      const paths = children.map((child) => readPath(child, depth, true));
      items.push({ kind: "parallel", key: freshKey("together"), lanes: paths.map((p) => p.items) });
      tails = [...new Set(paths.flatMap((p) => p.tails))];
    }
    return { items, tails };
  };

  const readPath = (
    first: BuilderNode,
    depth: number,
    keepWhen = false,
  ): { items: Item[]; tails: string[] } => {
    used.add(first.id);
    const head = keepWhen ? first : stripWhen(first);
    const rest = read([first.id], depth + 1);
    return { items: [itemOf(head), ...rest.items], tails: rest.tails };
  };

  const main = read([], 0).items;
  const loose = nodes.filter((node) => !used.has(node.id));
  return { main, loose };
}

function hasWhen(node: BuilderNode): boolean {
  return typeof node.when === "string" && node.when.trim() !== "";
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stripWhen(node: BuilderNode): BuilderNode {
  return without(node, "when");
}

function itemOf(node: BuilderNode): Item {
  const clean = node.trigger_rule === JOIN_RULE ? without(node, "trigger_rule") : node;
  if (node.type === "loop_group") {
    const body = Array.isArray(node.nodes) ? (node.nodes as BuilderNode[]) : [];
    const program = programOf(body);
    return { kind: "repeat", node: without(clean, "nodes"), body: program.main };
  }
  return { kind: "block", node: clean };
}

/** Writes a program back as `nodes`: each block waits for the end of what is above it. */
export function nodesOf(items: readonly Item[]): BuilderNode[] {
  const out: BuilderNode[] = [];
  write(items, [], { when: null, join: false }, out);
  return out;
}

interface Entry {
  /** The condition the first block written carries (the first block of an If path). */
  when: string | null;
  /** The first blocks written follow an If: they run when the path taken finished. */
  join: boolean;
}

function place(node: BuilderNode, after: readonly string[], entry: Entry): BuilderNode {
  let next: BuilderNode = without(without(node, "depends_on"), "when");
  if (after.length > 0) next = { ...next, depends_on: [...after] };
  if (entry.when) next = { ...next, when: entry.when };
  else if (typeof node.when === "string" && node.when !== "") next = { ...next, when: node.when };
  if (entry.join && after.length > 1) next = { ...next, trigger_rule: JOIN_RULE };
  return next;
}

/** Writes `items` after `after`; answers the ids the next block must wait for. */
function write(
  items: readonly Item[],
  after: readonly string[],
  entry: Entry,
  out: BuilderNode[],
): string[] {
  let tails = [...after];
  let pending: Entry = entry;
  for (const item of items) {
    if (item.kind === "block") {
      out.push(place(item.node, tails, pending));
      tails = [item.node.id];
      pending = { when: null, join: false };
    } else if (item.kind === "repeat") {
      const body = nodesOf(item.body);
      out.push({ ...place(item.node, tails, pending), nodes: body });
      tails = [item.node.id];
      pending = { when: null, join: false };
    } else if (item.kind === "stage") {
      tails = write(item.steps, tails, pending, out);
      pending = { when: null, join: false };
    } else if (item.kind === "if") {
      const negated = negateCondition(item.condition);
      const thenTails =
        item.then.length > 0
          ? write(item.then, tails, { when: item.condition || null, join: pending.join }, out)
          : tails;
      const elseTails =
        item.otherwise.length > 0
          ? write(item.otherwise, tails, { when: negated, join: pending.join }, out)
          : tails;
      tails = [...new Set([...thenTails, ...elseTails])];
      pending = { when: null, join: true };
    } else {
      const ends = item.lanes
        .filter((lane) => lane.length > 0)
        .flatMap((lane) => write(lane, tails, pending, out));
      tails = ends.length > 0 ? [...new Set(ends)] : tails;
      pending = { when: null, join: false };
    }
  }
  return tails;
}

/* ---------- Edits on a program (paths address a list inside the tree) ---------- */

/** Where a list of items is: the main stack (in a scenario written as blocks, its stages), a
 * repeat's body, an If path, a lane or a stage's steps. */
export type Slot =
  | { in: "main" }
  | { in: "body"; owner: string }
  | { in: "then" | "otherwise"; owner: string }
  | { in: "lane"; owner: string; lane: number }
  | { in: "stage"; owner: string };

export function itemId(item: Item): string {
  return item.kind === "block" || item.kind === "repeat" ? (item.key ?? item.node.id) : item.key;
}

/** The lists an item holds, in order (a stage's steps, a body, an If's two paths, the lanes). */
export function listsOf(item: Item): readonly (readonly Item[])[] {
  if (item.kind === "stage") return [item.steps];
  if (item.kind === "repeat") return [item.body];
  if (item.kind === "if") return [item.then, item.otherwise];
  if (item.kind === "parallel") return item.lanes;
  return [];
}

function mapLists(items: Item[], slot: Slot, fn: (list: Item[]) => Item[]): Item[] {
  if (slot.in === "main") return fn(items);
  return items.map((item) => {
    const id = itemId(item);
    if (item.kind === "stage") {
      const steps =
        slot.in === "stage" && id === slot.owner ? fn(item.steps) : mapLists(item.steps, slot, fn);
      return { ...item, steps };
    }
    if (item.kind === "repeat") {
      const body =
        id === (slot as { owner: string }).owner && slot.in === "body"
          ? fn(item.body)
          : mapLists(item.body, slot, fn);
      return { ...item, body };
    }
    if (item.kind === "if") {
      const mine = id === (slot as { owner: string }).owner;
      return {
        ...item,
        then: mine && slot.in === "then" ? fn(item.then) : mapLists(item.then, slot, fn),
        otherwise:
          mine && slot.in === "otherwise" ? fn(item.otherwise) : mapLists(item.otherwise, slot, fn),
      };
    }
    if (item.kind === "parallel") {
      const mine = id === (slot as { owner: string }).owner && slot.in === "lane";
      return {
        ...item,
        lanes: item.lanes.map((lane, index) =>
          mine && index === (slot as { lane: number }).lane ? fn(lane) : mapLists(lane, slot, fn),
        ),
      };
    }
    return item;
  });
}

/** The list `slot` addresses (null when its owner is gone). */
export function listAt(items: readonly Item[], slot: Slot): readonly Item[] | null {
  if (slot.in === "main") return items;
  const owner = findItem(items, slot.owner);
  if (!owner) return null;
  if (owner.kind === "stage" && slot.in === "stage") return owner.steps;
  if (owner.kind === "repeat" && slot.in === "body") return owner.body;
  if (owner.kind === "if" && slot.in === "then") return owner.then;
  if (owner.kind === "if" && slot.in === "otherwise") return owner.otherwise;
  if (owner.kind === "parallel" && slot.in === "lane") return owner.lanes[slot.lane] ?? null;
  return null;
}

/** Puts `moved` into `slot` at `index` (an index past the end appends). */
export function insertAt(items: Item[], slot: Slot, index: number, moved: readonly Item[]): Item[] {
  return mapLists(items, slot, (list) => [...list.slice(0, index), ...moved, ...list.slice(index)]);
}

/** Takes the item `id` and every item after it in its list out of the tree (Scratch's drag: a
 * block takes the blocks under it along); `alone` takes only that item. */
export function takeFrom(
  items: Item[],
  id: string,
  alone = false,
): { rest: Item[]; taken: Item[] } {
  let taken: Item[] = [];
  const visit = (list: Item[]): Item[] => {
    const index = list.findIndex((item) => itemId(item) === id);
    if (index >= 0) {
      taken = alone ? list.slice(index, index + 1) : list.slice(index);
      return alone ? [...list.slice(0, index), ...list.slice(index + 1)] : list.slice(0, index);
    }
    return list.map((item) => {
      if (item.kind === "stage") return { ...item, steps: visit(item.steps) };
      if (item.kind === "repeat") return { ...item, body: visit(item.body) };
      if (item.kind === "if")
        return { ...item, then: visit(item.then), otherwise: visit(item.otherwise) };
      if (item.kind === "parallel") return { ...item, lanes: item.lanes.map(visit) };
      return item;
    });
  };
  const rest = visit(items);
  return { rest, taken };
}

/** Replaces the item `id` wherever it is. */
export function replaceItem(items: Item[], id: string, next: Item): Item[] {
  return items.map((item) => {
    if (itemId(item) === id) return next;
    if (item.kind === "stage") return { ...item, steps: replaceItem(item.steps, id, next) };
    if (item.kind === "repeat") return { ...item, body: replaceItem(item.body, id, next) };
    if (item.kind === "if")
      return {
        ...item,
        then: replaceItem(item.then, id, next),
        otherwise: replaceItem(item.otherwise, id, next),
      };
    if (item.kind === "parallel")
      return { ...item, lanes: item.lanes.map((lane) => replaceItem(lane, id, next)) };
    return item;
  });
}

/** Finds the item `id`. */
export function findItem(items: readonly Item[], id: string): Item | null {
  for (const item of items) {
    if (itemId(item) === id) return item;
    const inner = listsOf(item).reduce<Item | null>(
      (found, list) => found ?? findItem(list, id),
      null,
    );
    if (inner) return inner;
  }
  return null;
}

/** Every node of a program (to name a fresh id). */
export function programNodes(items: readonly Item[]): BuilderNode[] {
  return items.flatMap((item) => {
    if (item.kind === "block") return [item.node];
    if (item.kind === "repeat") return [item.node, ...programNodes(item.body)];
    return listsOf(item).flatMap(programNodes);
  });
}

type Located = { slot: Slot; index: number } | null;

/** Where the item `id` sits: its list and its index there (null when absent). */
export function locate(items: readonly Item[], id: string, slot: Slot = { in: "main" }): Located {
  for (const [index, item] of items.entries()) {
    if (itemId(item) === id) return { slot, index };
    let inner: Located = null;
    if (item.kind === "stage") inner = locate(item.steps, id, { in: "stage", owner: item.key });
    else if (item.kind === "repeat")
      inner = locate(item.body, id, { in: "body", owner: itemId(item) });
    else if (item.kind === "if") {
      const owner = itemId(item);
      inner =
        locate(item.then, id, { in: "then", owner }) ??
        locate(item.otherwise, id, { in: "otherwise", owner });
    } else if (item.kind === "parallel") {
      const owner = itemId(item);
      inner = item.lanes.reduce<Located>(
        (found, lane, at) => found ?? locate(lane, id, { in: "lane", owner, lane: at }),
        null,
      );
    }
    if (inner) return inner;
  }
  return null;
}

/** The step numbers the gutter shows: 1, 2, 3, then 3.1, 3.2 … inside a C-block, counting on
 * across an If's two paths and across lanes, so each block has its own number. In a scenario
 * written as blocks, a block's number is its address. */
export function stepNumbers(items: readonly Item[], prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  if (items.some((item) => item.kind === "stage")) {
    const all = (list: readonly Item[]): void => {
      for (const item of list) {
        out.set(itemId(item), itemId(item));
        for (const inner of listsOf(item)) all(inner);
      }
    };
    all(items);
    return out;
  }
  const walk = (list: readonly Item[], head: string, start: number): number => {
    let n = start;
    for (const item of list) {
      n += 1;
      const label = `${head}${String(n)}`;
      out.set(itemId(item), label);
      let m = 0;
      for (const body of listsOf(item)) m = walk(body, `${label}.`, m);
    }
    return n;
  };
  walk(items, prefix, 0);
  return out;
}

/* ---------- A scenario written as blocks (version 2) ---------- */

/** A step's kind key and the node type it becomes (`wait`, `repeat`, `if` and `together` apart). */
const LEAVES: Readonly<Record<string, { type: string; key: string }>> = {
  do: { type: "action", key: "action" },
  wait_until: { type: "expect", key: "action" },
  you: { type: "approval", key: "message" },
  include: { type: "include", key: "include" },
};
const STEP_KINDS = ["do", "wait_until", "you", "wait", "include", "repeat", "if", "together"];
/** A node's type, back to its step's kind key. */
const KIND_OF: Readonly<Record<string, string>> = {
  action: "do",
  expect: "wait_until",
  approval: "you",
  include: "include",
};
/** A node that holds a step the builder cannot read (no kind key, or two), written as it is. */
const UNREAD = "unread";
// The canonical key order (generator's scenario writer): a canonical file's mapping written back
// reads as the same JSON, key for key, so an edit undone leaves nothing to save. The round trip
// of the writer's own every-key document (testing/treeDocuments.ts) checks it is the writer's.
const TREE_ORDER = ["version", "kind", "name", "revision", "description", "inputs", "stages"];
const STAGE_ORDER = ["name", "description", "steps"];
const STEP_ORDER = [
  ...STEP_KINDS,
  "id",
  "description",
  "with",
  "until",
  "every",
  "timeout",
  "decisions",
  "capture_response",
  "then",
  "else",
  "capture",
  "retry",
];
const REPEAT_ORDER = ["max", "until", "steps"];
const WAIT_ORDER = ["duration", "until", "attention", "options"];

/** `mapping` with the keys `order` names first, in that order, then the rest as given. */
function ordered(mapping: Mapping, order: readonly string[]): Mapping {
  const out: Mapping = {};
  for (const key of order) {
    const value = mapping[key];
    if (value !== undefined) out[key] = value;
  }
  for (const [key, value] of Object.entries(mapping)) if (!(key in out)) out[key] = value;
  return out;
}

type Mapping = Record<string, Json>;

function mapping(value: Json | undefined): Mapping {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

function list(value: Json | undefined): Json[] {
  return Array.isArray(value) ? value : [];
}

/** Whether a scenario file's mapping is written as blocks (`version: 2`, stages of blocks). */
export function isTree(document: unknown): boolean {
  return (
    typeof document === "object" &&
    document !== null &&
    !Array.isArray(document) &&
    (document as Record<string, unknown>).version === 2
  );
}

/** A stage name's slug, as core makes it: lowercase, each run of other characters one `-`. */
export function stageSlug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

/** The id a block without one runs under: `<stage slug>--<its address in the stage>`. */
export function derivedId(slug: string, address: string): string {
  const inStage = address.split(".").slice(1).join("-");
  return `${slug}--${inStage}`;
}

/** The stages of a scenario written as blocks, as items keyed by their block address. */
export function stagesOf(document: Mapping): Item[] {
  const stages = list(document.stages).map((stage): Item => {
    const { name, steps, ...extra } = mapping(stage);
    const item: Item = {
      kind: "stage",
      key: "",
      name: typeof name === "string" ? name : "",
      steps: list(steps).map(stepItem),
    };
    return Object.keys(extra).length > 0 ? { ...item, extra } : item;
  });
  return addressed(stages).items;
}

function stepItem(value: Json): Item {
  const step = mapping(value);
  const kinds = STEP_KINDS.filter((kind) => kind in step);
  const [kind] = kinds;
  if (kinds.length !== 1 || kind === undefined) {
    return { kind: "block", key: "", named: false, node: { id: "", type: UNREAD, step } };
  }
  const { id, ...rest } = step;
  const named = id !== undefined;
  const nodeId = typeof id === "string" ? id : "";
  if (kind === "if") {
    const { if: condition, then, else: otherwise, ...extra } = rest;
    const item: Item = {
      kind: "if",
      key: "",
      condition: typeof condition === "string" ? condition : "",
      then: list(then).map(stepItem),
      otherwise: list(otherwise).map(stepItem),
    };
    return Object.keys(extra).length > 0 ? { ...item, extra } : item;
  }
  if (kind === "together") {
    const { together, ...extra } = rest;
    const item: Item = {
      kind: "parallel",
      key: "",
      lanes: list(together).map((lane) => list(lane).map(stepItem)),
    };
    return Object.keys(extra).length > 0 ? { ...item, extra } : item;
  }
  if (kind === "repeat") {
    const { repeat, ...own } = rest;
    const { max, until, steps } = mapping(repeat);
    let node: BuilderNode = { ...own, id: nodeId, type: "loop_group" };
    if (max !== undefined) node = { ...node, max_iterations: max };
    if (until !== undefined) node = { ...node, until_when: until };
    return { kind: "repeat", key: "", named, node, body: list(steps).map(stepItem) };
  }
  if (kind === "wait") {
    const { wait, ...own } = rest;
    return {
      kind: "block",
      key: "",
      named,
      node: { ...own, ...mapping(wait), id: nodeId, type: "wait" },
    };
  }
  const leaf = LEAVES[kind] ?? { type: kind, key: kind };
  const { [kind]: main, until, ...own } = rest;
  let node: BuilderNode = { ...own, id: nodeId, type: leaf.type };
  if (main !== undefined) node = { ...node, [leaf.key]: main };
  if (until !== undefined)
    node = { ...node, [kind === "wait_until" ? "until_when" : "until"]: until };
  return { kind: "block", key: "", named, node };
}

/** `document` with its stages written from `stages` (every other key kept as it is), its keys
 * in the canonical order. */
export function treeOf(document: Mapping, stages: readonly Item[]): Mapping {
  return ordered({ ...document, stages: stages.filter(isStage).map(stageOf) }, TREE_ORDER);
}

function isStage(item: Item): item is Extract<Item, { kind: "stage" }> {
  return item.kind === "stage";
}

function stageOf(stage: Extract<Item, { kind: "stage" }>): Json {
  return ordered({ name: stage.name, ...stage.extra, steps: stage.steps.map(stepOf) }, STAGE_ORDER);
}

function stepOf(item: Item): Json {
  const step = writtenStep(item);
  if (typeof step !== "object" || step === null || Array.isArray(step)) return step;
  const out = ordered(step, STEP_ORDER);
  const repeat = out.repeat;
  if (typeof repeat === "object" && repeat !== null && !Array.isArray(repeat)) {
    out.repeat = ordered(repeat, REPEAT_ORDER);
  }
  const wait = out.wait;
  if (typeof wait === "object" && wait !== null && !Array.isArray(wait)) {
    out.wait = ordered(wait, WAIT_ORDER);
  }
  return out;
}

function writtenStep(item: Item): Json {
  if (item.kind === "stage") return stageOf(item);
  if (item.kind === "if") {
    const written: Mapping = { if: item.condition, then: item.then.map(stepOf) };
    if (item.otherwise.length > 0) written.else = item.otherwise.map(stepOf);
    return { ...written, ...item.extra };
  }
  if (item.kind === "parallel") {
    return { together: item.lanes.map((lane) => lane.map(stepOf)), ...item.extra };
  }
  const { id, type, ...own } = item.node;
  const named: Mapping = item.named === true ? { id } : {};
  if (type === UNREAD) return mapping(own.step);
  if (item.kind === "repeat") {
    const { max_iterations: max, until_when: until, ...rest } = own;
    const repeat: Mapping = {};
    if (max !== undefined) repeat.max = max;
    if (until !== undefined) repeat.until = until;
    return { repeat: { ...repeat, steps: item.body.map(stepOf) }, ...named, ...rest };
  }
  if (type === "wait") {
    const { description, ...wait } = own;
    const written: Mapping = { wait, ...named };
    return description === undefined ? written : { ...written, description };
  }
  const kind = KIND_OF[type] ?? type;
  const leaf = LEAVES[kind] ?? { type, key: kind };
  const { [leaf.key]: main, until_when: until, ...rest } = own;
  const written: Mapping = { [kind]: main ?? "", ...named, ...rest };
  if (until !== undefined) written[kind === "wait_until" ? "until" : "until_when"] = until;
  return written;
}

/** `items` keyed again by their place (each block's address, and the id a block without one
 * runs under), with the key each item had before: after an edit, what was selected follows. */
export function addressed(items: readonly Item[]): { items: Item[]; keys: Map<string, string> } {
  const keys = new Map<string, string>();
  const walk = (list: readonly Item[], address: string, slug: string): Item[] =>
    list.map((item, index) => {
      const key = `${address}.${String(index + 1)}`;
      keys.set(itemId(item), key);
      if (item.kind === "stage") return item;
      if (item.kind === "if") {
        return {
          ...item,
          key,
          then: walk(item.then, `${key}.then`, slug),
          otherwise: walk(item.otherwise, `${key}.else`, slug),
        };
      }
      if (item.kind === "parallel") {
        return {
          ...item,
          key,
          lanes: item.lanes.map((lane, at) => walk(lane, `${key}.p${String(at + 1)}`, slug)),
        };
      }
      const node = item.named === true ? item.node : { ...item.node, id: derivedId(slug, key) };
      if (item.kind === "repeat") return { ...item, key, node, body: walk(item.body, key, slug) };
      return { ...item, key, node };
    });
  const stages = items.map((item, index): Item => {
    const key = String(index + 1);
    keys.set(itemId(item), key);
    if (item.kind !== "stage") return item;
    return { ...item, key, steps: walk(item.steps, key, stageSlug(item.name)) };
  });
  return { items: stages, keys };
}

/** How an edit from `before` to `next` changes the ids blocks run under, as the references to
 * them must follow so that each still reads the block it read: a block with no id of its own
 * that `next` puts at another place, or in a stage of another name, from its old place's id to
 * its new one; a removed block, from its id to `<id>-removed`, an id no place gives, so that no
 * block now at its place reads as it (only when it had no id of its own, or another block now
 * runs under it). Items are matched by their key (`next` keeps the keys of `before`). An id two
 * blocks share, before or after, is left out: no reference to it can be told apart. */
export function idChanges(before: readonly Item[], next: readonly Item[]): Map<string, string> {
  const count = (ids: readonly string[]) => {
    const seen = new Map<string, number>();
    for (const id of ids) seen.set(id, (seen.get(id) ?? 0) + 1);
    return seen;
  };
  const was = nodeItems(before);
  const idOf = new Map(was.map((item) => [itemId(item), item.node.id]));
  const oldIds = count(was.map((item) => item.node.id));
  const moved = nodeItems(next);
  const placed = nodeItems(addressed(next).items);
  const newIds = count(placed.map((item) => item.node.id));
  const changes = new Map<string, string>();
  const kept = new Set<string>();
  for (const [index, item] of moved.entries()) {
    const from = idOf.get(itemId(item));
    if (from === undefined) continue;
    kept.add(itemId(item));
    const to = placed[index]?.node.id;
    if (to === undefined || to === from) continue;
    if (oldIds.get(from) === 1 && newIds.get(to) === 1) changes.set(from, to);
  }
  for (const item of was) {
    const id = item.node.id;
    if (kept.has(itemId(item)) || oldIds.get(id) !== 1) continue;
    if (item.named !== true || newIds.has(id)) changes.set(id, `${id}-removed`);
  }
  return changes;
}

// A block's output read in a value: `$<id>.output…` or `$LOOP_PREV.<id>.output…` (`$$` is a
// written dollar, not a reference).
const OUTPUT_REF = /\$(?:\$|(LOOP_PREV\.)?([A-Za-z0-9_-]+)\.output(?![A-Za-z0-9_]))/g;
// An id a reference can name: a reference is written only with one (a proposal, or a file the
// load refused, can give a block any id).
const REF_ID = /^[A-Za-z0-9_-]+$/;

/** `document` with each reference in its stages to a block whose id `ids` maps written with the
 * id it maps to, all at once (so two blocks that swap places swap their references too). */
export function renameRefs(document: Mapping, ids: ReadonlyMap<string, string>): Mapping {
  if (ids.size === 0 || document.stages === undefined) return document;
  return { ...document, stages: renamedIn(document.stages, ids) };
}

/** `value` with each reference to a block whose id `ids` maps written with the id it maps to,
 * in its string values only (never a key), and only when that id is one a reference can name:
 * a reference to a block whose new id no reference can name stays as written. `value` itself
 * when nothing changes. */
function renamedIn(value: Json, ids: ReadonlyMap<string, string>): Json {
  if (ids.size === 0) return value;
  if (typeof value === "string") {
    return value.replace(
      OUTPUT_REF,
      (whole: string, prev: string | undefined, id: string | undefined) => {
        const to = id === undefined ? undefined : ids.get(id);
        return to === undefined || !REF_ID.test(to) ? whole : `$${prev ?? ""}${to}.output`;
      },
    );
  }
  if (Array.isArray(value)) {
    const next = value.map((item) => renamedIn(item, ids));
    return next.some((item, at) => item !== value[at]) ? next : value;
  }
  if (value === null || typeof value !== "object") return value;
  const entries = Object.entries(value);
  const next = entries.map(([key, item]): [string, Json] => [key, renamedIn(item, ids)]);
  return next.some(([, item], at) => item !== entries[at]?.[1]) ? Object.fromEntries(next) : value;
}

/** `items` as new blocks of a scenario written as blocks: no id of their own (their place gives
 * one; with `keepIds`, the ids they give are kept, as a proposal's) and a key no other item has
 * until they are addressed. */
export function fresh(items: readonly Item[], keepIds = false, prefix = "+"): Item[] {
  return items.map((item, index) => {
    const key = `${prefix}${String(index)}`;
    const inner = (list: readonly Item[], at: number) =>
      fresh(list, keepIds, `${key}/${String(at)}.`);
    if (item.kind === "stage") return { ...item, key, steps: inner(item.steps, 0) };
    if (item.kind === "if")
      return { ...item, key, then: inner(item.then, 0), otherwise: inner(item.otherwise, 1) };
    if (item.kind === "parallel")
      return { ...item, key, lanes: item.lanes.map((lane, at) => inner(lane, at)) };
    const named = keepIds && item.named === true;
    if (item.kind === "repeat") return { ...item, key, named, body: inner(item.body, 0) };
    return { ...item, key, named };
  });
}

/** The keys of `item` and of every item it holds. */
export function keysOf(item: Item): string[] {
  return [itemId(item), ...listsOf(item).flatMap((list) => list.flatMap(keysOf))];
}

/** A new empty stage, named `Stage <n>` with a slug no stage of `names` has. */
export function newStage(names: readonly string[]): StageItem {
  const taken = new Set(names.map(stageSlug));
  let n = names.length + 1;
  while (taken.has(stageSlug(`Stage ${String(n)}`))) n += 1;
  return { kind: "stage", key: "+stage", name: `Stage ${String(n)}`, steps: [] };
}

/** Every item of `items` with each node passed through `fn` (a Repeat's too). */
export function mapNodes(items: readonly Item[], fn: (node: BuilderNode) => BuilderNode): Item[] {
  return items.map((item) => {
    if (item.kind === "stage") return { ...item, steps: mapNodes(item.steps, fn) };
    if (item.kind === "if")
      return { ...item, then: mapNodes(item.then, fn), otherwise: mapNodes(item.otherwise, fn) };
    if (item.kind === "parallel")
      return { ...item, lanes: item.lanes.map((lane) => mapNodes(lane, fn)) };
    if (item.kind === "repeat")
      return { ...item, node: fn(item.node), body: mapNodes(item.body, fn) };
    return { ...item, node: fn(item.node) };
  });
}

/** The stages as one chain of nodes (each stage's first block after the last block before it),
 * as the translation runs them: the graph the Graph view draws and value pickers read. */
export function treeNodes(stages: readonly Item[]): BuilderNode[] {
  return nodesOf(stages.flatMap((stage) => (stage.kind === "stage" ? stage.steps : [stage])));
}

/** The key path of the block at `address`: `2.3.p2.1` is `stages[1].steps[2].together[1][0]`. */
export function keyPathOf(address: string): string {
  const [stage, ...rest] = address.split(".");
  let path = `stages[${String(Number(stage) - 1)}]`;
  let list = "steps";
  for (const part of rest) {
    if (part === "then" || part === "else") list = part;
    else if (/^p\d+$/.test(part)) list = `together[${String(Number(part.slice(1)) - 1)}]`;
    else {
      path += `.${list}[${String(Number(part) - 1)}]`;
      list = "repeat.steps";
    }
  }
  return path;
}

/** The address of the block a problem's key path is on (`stages[0].steps[1].until` is on
 * `1.2`), or null for a key of the document's own. */
export function addressOfKey(key: string | null | undefined): string | null {
  const head = /^stages\[(\d+)\]/.exec(key ?? "");
  if (!head) return null;
  let address = String(Number(head[1]) + 1);
  let rest = (key ?? "").slice(head[0].length);
  const STEP = /^\.(steps|then|else|repeat\.steps)\[(\d+)\]|^\.together\[(\d+)\]\[(\d+)\]/;
  for (let match = STEP.exec(rest); match; match = STEP.exec(rest)) {
    const [whole, owner, at, path, inPath] = match;
    if (path !== undefined)
      address += `.p${String(Number(path) + 1)}.${String(Number(inPath) + 1)}`;
    else if (owner === "then" || owner === "else") address += `.${owner}.${String(Number(at) + 1)}`;
    else address += `.${String(Number(at) + 1)}`;
    rest = rest.slice(whole.length);
  }
  return address;
}

/* ---------- Claude's proposal for a scenario written as blocks, reviewed ---------- */

/** A change Claude's proposal makes to a scenario written as blocks. A review lists its changes
 * once, when it opens (`treeReview`), and each keeps its id until the review closes. */
export interface TreeChange {
  /** What it is and where, as the review names it: `new block 1.4` and `new stage 3` by their
   * address in the proposal, `changed block 2.3`, `removed block 7.1`, `changed stage 2` and
   * `removed stage 4` by theirs in the draft the review opened on, `changed inputs`, `changed
   * description`. Two blocks alike are two changes. */
  id: string;
  kind: "new" | "changed" | "removed";
  of: "stage" | "block" | "inputs" | "description";
  /** The block's or stage's address in the draft the review opened on (a new one: in the
   * proposal); "" for the scenario's inputs and description. */
  address: string;
  /** Its address in the proposal (new and changed blocks and stages), to outline it there. */
  proposed: string | null;
  /** The proposal's item (new, changed) or the draft's (removed); null for inputs and
   * description. */
  item: Item | null;
}

/** How a step of a stage both hold comes into the draft: kept (the same in both), or by its
 * change's decision. */
type StepPlan =
  | { op: "kept"; i: number; j: number }
  | { op: "changed"; i: number; j: number; id: string }
  | { op: "removed"; i: number; id: string }
  | { op: "new"; j: number; id: string };

/** How a stage comes into the draft: one both hold (in place; or moved, at the draft's place
 * unless its change is accepted and at the proposal's when it is), the draft's alone or the
 * proposal's alone. `frame` is the change of its name, the keys it gives beside its steps and
 * its place, when any differs. */
type StagePlan =
  | { op: "kept" | "from" | "to"; i: number; j: number; frame: string | null; steps: StepPlan[] }
  | { op: "removed"; i: number; id: string }
  | { op: "new"; j: number; id: string };

/** A review of Claude's proposal for a scenario written as blocks: the draft as it was when the
 * review opened, the proposal, and the changes from one to the other, read once. */
export interface TreeReview {
  readonly base: Mapping;
  readonly proposal: Mapping;
  /** Every change, in reading order. */
  readonly changes: readonly TreeChange[];
  readonly mine: readonly StageItem[];
  readonly theirs: readonly StageItem[];
  readonly plan: readonly StagePlan[];
}

/** A person's decision on a change of a review. */
export type Decision = "accept" | "reject";

/** JSON text with every mapping's keys in order: two values give the same text when they are
 * the same, whatever order their keys are written in. */
function stable(value: Json | undefined): string {
  if (value === undefined) return "";
  return JSON.stringify(value, (_key, inner: unknown) =>
    typeof inner === "object" && inner !== null && !Array.isArray(inner)
      ? Object.fromEntries(
          Object.entries(inner as Mapping).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
        )
      : inner,
  );
}

function stepsIn(stage: Json | undefined): Json[] {
  return list(mapping(stage).steps);
}

/** A stage as written, but its steps: its name and the keys it gives beside them. */
function frameOf(stage: Json | undefined): string {
  return stable(
    Object.fromEntries(Object.entries(mapping(stage)).filter(([key]) => key !== "steps")),
  );
}

/** The review of `proposal` for `base` (both scenarios written as blocks): stages matched by
 * their slug (one both hold but in another order is moved), then each matched stage's steps
 * aligned by what they write (a run of removed and new steps between two kept ones pairs up as
 * changed); the scenario's inputs and description when the proposal gives others. */
export function treeReview(base: Mapping, proposal: Mapping): TreeReview {
  const mine = stagesOf(base).filter(isStage);
  const theirs = stagesOf(proposal).filter(isStage);
  const mineRaw = list(base.stages);
  const theirsRaw = list(proposal.stages);
  const changes: TreeChange[] = [];
  if (proposal.inputs !== undefined && stable(proposal.inputs) !== stable(base.inputs)) {
    changes.push({
      id: "changed inputs",
      kind: "changed",
      of: "inputs",
      address: "",
      proposed: null,
      item: null,
    });
  }
  if (typeof proposal.description === "string" && proposal.description !== base.description) {
    changes.push({
      id: "changed description",
      kind: "changed",
      of: "description",
      address: "",
      proposed: null,
      item: null,
    });
  }

  const slugs = (stages: readonly StageItem[]) => stages.map((stage) => stageSlug(stage.name));
  const a = slugs(mine);
  const b = slugs(theirs);
  const walk = aligned(a, b, [0, a.length], [0, b.length]);
  // A stage both hold that the alignment leaves out on either side is moved (paired in order).
  const free = walk.flatMap((step) => (step.i === undefined ? [step.j] : []));
  const movedTo = new Map<number, number>();
  for (const step of walk) {
    if (step.j !== undefined) continue;
    const at = free.findIndex((j) => j !== -1 && b[j] === a[step.i]);
    const j = free[at];
    if (j === undefined) continue;
    movedTo.set(step.i, j);
    free[at] = -1;
  }
  const movedFrom = new Map([...movedTo].map(([i, j]) => [j, i]));
  const stepPlan = (i: number, j: number): { steps: StepPlan[]; changes: TreeChange[] } => {
    const own = mine[i]?.steps ?? [];
    const their = theirs[j]?.steps ?? [];
    const x = stepsIn(mineRaw[i]).map(stable);
    const y = stepsIn(theirsRaw[j]).map(stable);
    const steps: StepPlan[] = [];
    const listed: TreeChange[] = [];
    let removed: number[] = [];
    let added: number[] = [];
    const flush = () => {
      const pairs = Math.min(removed.length, added.length);
      for (const [n, at] of removed.entries()) {
        const mineStep = own[at];
        const to = n < pairs ? added[n] : undefined;
        const theirStep = to === undefined ? undefined : their[to];
        if (!mineStep) continue;
        if (to !== undefined && theirStep) {
          const id = `changed block ${itemId(mineStep)}`;
          steps.push({ op: "changed", i: at, j: to, id });
          listed.push({
            id,
            kind: "changed",
            of: "block",
            address: itemId(mineStep),
            proposed: itemId(theirStep),
            item: theirStep,
          });
        } else {
          const id = `removed block ${itemId(mineStep)}`;
          steps.push({ op: "removed", i: at, id });
          listed.push({
            id,
            kind: "removed",
            of: "block",
            address: itemId(mineStep),
            proposed: null,
            item: mineStep,
          });
        }
      }
      for (const at of added.slice(pairs)) {
        const theirStep = their[at];
        if (!theirStep) continue;
        const id = `new block ${itemId(theirStep)}`;
        steps.push({ op: "new", j: at, id });
        listed.push({
          id,
          kind: "new",
          of: "block",
          address: itemId(theirStep),
          proposed: itemId(theirStep),
          item: theirStep,
        });
      }
      removed = [];
      added = [];
    };
    for (const step of aligned(x, y, [0, x.length], [0, y.length])) {
      if (step.i !== undefined && step.j !== undefined) {
        flush();
        steps.push({ op: "kept", i: step.i, j: step.j });
      } else if (step.i !== undefined) removed.push(step.i);
      else added.push(step.j);
    }
    flush();
    return { steps, changes: listed };
  };

  // A stage both hold: its change (its name, the keys beside its steps, its place) and its
  // steps', read once whether it is met at the draft's place or the proposal's first.
  interface Matched {
    frame: TreeChange | null;
    steps: StepPlan[];
    changes: TreeChange[];
  }
  const matched = new Map<number, Matched>();
  const matchOf = (i: number, j: number, moved: boolean): Matched => {
    const known = matched.get(i);
    if (known) return known;
    const own = mine[i];
    const their = theirs[j];
    const frame: TreeChange | null =
      own && their && (moved || frameOf(mineRaw[i]) !== frameOf(theirsRaw[j]))
        ? {
            id: `changed stage ${own.key}`,
            kind: "changed",
            of: "stage",
            address: own.key,
            proposed: their.key,
            item: their,
          }
        : null;
    const made = { frame, ...stepPlan(i, j) };
    matched.set(i, made);
    return made;
  };
  const plan: StagePlan[] = [];
  const stageChange = (made: Matched) => {
    if (made.frame) changes.push(made.frame);
    changes.push(...made.changes);
  };
  for (const step of walk) {
    if (step.i !== undefined && step.j !== undefined) {
      const made = matchOf(step.i, step.j, false);
      plan.push({
        op: "kept",
        i: step.i,
        j: step.j,
        frame: made.frame?.id ?? null,
        steps: made.steps,
      });
      stageChange(made);
    } else if (step.i !== undefined) {
      const j = movedTo.get(step.i);
      if (j !== undefined) {
        const made = matchOf(step.i, j, true);
        plan.push({ op: "from", i: step.i, j, frame: made.frame?.id ?? null, steps: made.steps });
        continue;
      }
      const own = mine[step.i];
      if (!own) continue;
      const id = `removed stage ${own.key}`;
      plan.push({ op: "removed", i: step.i, id });
      changes.push({
        id,
        kind: "removed",
        of: "stage",
        address: own.key,
        proposed: null,
        item: own,
      });
    } else {
      const i = movedFrom.get(step.j);
      if (i !== undefined) {
        const made = matchOf(i, step.j, true);
        plan.push({ op: "to", i, j: step.j, frame: made.frame?.id ?? null, steps: made.steps });
        stageChange(made);
        continue;
      }
      const their = theirs[step.j];
      if (!their) continue;
      const id = `new stage ${their.key}`;
      plan.push({ op: "new", j: step.j, id });
      changes.push({
        id,
        kind: "new",
        of: "stage",
        address: their.key,
        proposed: their.key,
        item: their,
      });
    }
  }
  return { base, proposal, changes, mine, theirs, plan };
}

/** A step of the draft a review gives: what it is written as before its references are read
 * again, the item it is read as, and where it comes from (the draft's alone, the proposal's
 * alone, or one both hold), with the block it takes the place of or that takes its place. */
interface Piece {
  origin: "mine" | "theirs" | "both";
  raw: Json;
  item: Item;
  mine?: Item;
  theirs?: Item;
}

/** The draft a review gives when the changes `accepted` are taken and every other one is
 * left: built again from the draft the review opened on and the proposal each time, never
 * from the draft an earlier decision gave. A block taken from the proposal is written as the
 * proposal wrote it; one of the draft's alone (a removal or a change rejected) has each
 * reference read again so that it reads the block it read, at its place now (one taken out:
 * `<id>-removed`, an id no place gives, unless it had an id of its own no block now runs under);
 * one both hold reads the block it reads in both, or the one of its two the draft still holds,
 * and is written as it is otherwise. Nothing accepted gives the draft; everything, the
 * proposal. */
export function applyReview(review: TreeReview, accepted: ReadonlySet<string>): Mapping {
  const { base, proposal, mine, theirs, plan } = review;
  const mineRaw = list(base.stages);
  const theirsRaw = list(proposal.stages);
  const taken = (id: string | null) => id !== null && accepted.has(id);
  const out: { frame: Json; name: string; pieces: Piece[] }[] = [];
  const alone = (origin: "mine" | "theirs", stage: StageItem, raw: Json | undefined) => {
    const raws = stepsIn(raw);
    out.push({
      frame: raw ?? null,
      name: stage.name,
      pieces: stage.steps.map((item, at) => ({ origin, raw: raws[at] ?? null, item })),
    });
  };
  for (const stage of plan) {
    if (stage.op === "removed") {
      const own = mine[stage.i];
      if (own && !taken(stage.id)) alone("mine", own, mineRaw[stage.i]);
      continue;
    }
    if (stage.op === "new") {
      const their = theirs[stage.j];
      if (their && taken(stage.id)) alone("theirs", their, theirsRaw[stage.j]);
      continue;
    }
    const framed = taken(stage.frame);
    if ((stage.op === "from" && framed) || (stage.op === "to" && !framed)) continue;
    const own = mine[stage.i];
    const their = theirs[stage.j];
    if (!own || !their) continue;
    const ownRaws = stepsIn(mineRaw[stage.i]);
    const theirRaws = stepsIn(theirsRaw[stage.j]);
    const pieces: Piece[] = [];
    for (const step of stage.steps) {
      const ownStep = step.op === "new" ? undefined : own.steps[step.i];
      const theirStep = step.op === "removed" ? undefined : their.steps[step.j];
      const ownRaw = step.op === "new" ? null : (ownRaws[step.i] ?? null);
      const theirRaw = step.op === "removed" ? null : (theirRaws[step.j] ?? null);
      if (step.op === "kept") {
        if (ownStep && theirStep) {
          pieces.push({ origin: "both", raw: ownRaw, item: ownStep, theirs: theirStep });
        }
      } else if (taken(step.id)) {
        if (theirStep)
          pieces.push({
            origin: "theirs",
            raw: theirRaw,
            item: theirStep,
            ...(ownStep ? { mine: ownStep } : {}),
          });
      } else if (ownStep) {
        pieces.push({
          origin: "mine",
          raw: ownRaw,
          item: ownStep,
          ...(theirStep ? { theirs: theirStep } : {}),
        });
      }
    }
    out.push({
      frame: (framed ? theirsRaw[stage.j] : mineRaw[stage.i]) ?? null,
      name: framed ? their.name : own.name,
      pieces,
    });
  }

  // Each block at its place in the draft given, and the id it runs under there.
  const placed = addressed(
    out.map((stage): Item => ({
      kind: "stage",
      key: "",
      name: stage.name,
      steps: stage.pieces.map((piece) => piece.item),
    })),
  ).items;
  const counted = (items: readonly Item[]) => {
    const seen = new Map<string, number>();
    for (const item of nodeItems(items)) seen.set(item.node.id, (seen.get(item.node.id) ?? 0) + 1);
    return seen;
  };
  const inMine = counted(mine);
  const inTheirs = counted(theirs);
  const inResult = counted(placed);
  // Each block's id in the draft (or in the proposal) to the id it runs under in the draft
  // given, for the ones it holds; an id two blocks share, on either side, is left out.
  const mineTo = new Map<string, string>();
  const theirsTo = new Map<string, string>();
  const held = new Set<Item>();
  const heldTheirs = new Set<Item>();
  const follow = (
    to: Map<string, string>,
    count: ReadonlyMap<string, number>,
    keep: Set<Item>,
    from: Item | undefined,
    at: Item,
  ) => {
    if (!from) return;
    const now = nodeItems([at]);
    for (const [n, item] of nodeItems([from]).entries()) {
      const next = now[n];
      if (!next) break;
      keep.add(item);
      if (count.get(item.node.id) === 1 && inResult.get(next.node.id) === 1) {
        to.set(item.node.id, next.node.id);
      }
    }
  };
  for (const [s, stage] of out.entries()) {
    const at = placed[s];
    const steps = at?.kind === "stage" ? at.steps : [];
    for (const [k, piece] of stage.pieces.entries()) {
      const step = steps[k];
      if (!step) continue;
      follow(mineTo, inMine, held, piece.origin === "theirs" ? piece.mine : piece.item, step);
      follow(
        theirsTo,
        inTheirs,
        heldTheirs,
        piece.origin === "theirs" ? piece.item : piece.theirs,
        step,
      );
    }
  }
  // The ids of blocks the draft given no longer holds, on either side.
  const gone = (items: readonly Item[], count: ReadonlyMap<string, number>, keep: Set<Item>) =>
    new Set(
      nodeItems(items)
        .filter((item) => !keep.has(item) && count.get(item.node.id) === 1)
        .map((item) => item.node.id),
    );
  const mineGone = gone(mine, inMine, held);
  const theirsGone = gone(theirs, inTheirs, heldTheirs);
  const namedGone = new Set(
    nodeItems(mine)
      .filter((item) => mineGone.has(item.node.id) && item.named === true)
      .map((item) => item.node.id),
  );
  // The draft's own blocks follow theirs; a block both hold reads its block when it reads the
  // same one in both, or when the draft given holds only one of its two.
  const own = new Map<string, string>();
  for (const [from, to] of mineTo) if (from !== to) own.set(from, to);
  for (const id of mineGone) {
    if (!namedGone.has(id) || inResult.has(id)) own.set(id, `${id}-removed`);
  }
  const both = new Map<string, string>();
  for (const id of new Set([...mineTo.keys(), ...theirsTo.keys()])) {
    const m = mineTo.get(id);
    const t = theirsTo.get(id);
    const to =
      t !== undefined && (m === t || mineGone.has(id))
        ? t
        : m !== undefined && theirsGone.has(id)
          ? m
          : undefined;
    if (to !== undefined && to !== id) both.set(id, to);
  }

  const stages = out.map((stage): Json => {
    const frame = mapping(stage.frame);
    const steps = stage.pieces.map((piece) =>
      piece.origin === "theirs"
        ? piece.raw
        : renamedIn(piece.raw, piece.origin === "mine" ? own : both),
    );
    return "steps" in frame || steps.length > 0 ? { ...frame, steps } : frame;
  });
  const written: Mapping = { ...base };
  if ("stages" in base || stages.length > 0) written.stages = stages;
  for (const change of review.changes) {
    if (!accepted.has(change.id)) continue;
    if (change.of === "inputs" && proposal.inputs !== undefined) written.inputs = proposal.inputs;
    if (change.of === "description" && proposal.description !== undefined) {
      written.description = proposal.description;
    }
  }
  return written;
}

/** The decisions `decisions` with each of `ids` (changes the review lists) given `decision`,
 * the draft they give (`applyReview`), and whether the review is done: every change it listed
 * when it opened decided. Accept all and Reject all are every id at once. */
export function decideReview(
  review: TreeReview,
  decisions: ReadonlyMap<string, Decision>,
  ids: readonly string[],
  decision: Decision,
): { decisions: Map<string, Decision>; draft: Mapping; closed: boolean } {
  const listed = new Set(review.changes.map((change) => change.id));
  const next = new Map(decisions);
  for (const id of ids) if (listed.has(id)) next.set(id, decision);
  const accepted = new Set([...next].flatMap(([id, made]) => (made === "accept" ? [id] : [])));
  return {
    decisions: next,
    draft: applyReview(review, accepted),
    closed: review.changes.every((change) => next.has(change.id)),
  };
}

/** The most steps a side of a stage is aligned over in full: the nodes a scenario may run as.
 * Past it, only the steps alike at either end are kept (a proposal may hold more than loads). */
const MAX_ALIGNED = 512;

/** How two lists of step texts line up: each step of `a` kept as one of `b`, removed, or each
 * of `b` new, in reading order (the longest common subsequence, by suffix lengths). */
type Aligned =
  { i: number; j: number } | { i: number; j?: undefined } | { i?: undefined; j: number };

function aligned(
  a: readonly string[],
  b: readonly string[],
  [i0, i1]: readonly [number, number],
  [j0, j1]: readonly [number, number],
): Aligned[] {
  const out: Aligned[] = [];
  if (i1 - i0 > MAX_ALIGNED || j1 - j0 > MAX_ALIGNED) {
    let head = 0;
    while (i0 + head < i1 && j0 + head < j1 && a[i0 + head] === b[j0 + head]) head += 1;
    let tail = 0;
    while (
      i1 - tail > i0 + head &&
      j1 - tail > j0 + head &&
      a[i1 - tail - 1] === b[j1 - tail - 1]
    ) {
      tail += 1;
    }
    const middle: [[number, number], [number, number]] = [
      [i0 + head, i1 - tail],
      [j0 + head, j1 - tail],
    ];
    for (let n = 0; n < head; n += 1) out.push({ i: i0 + n, j: j0 + n });
    if (middle[0][1] - middle[0][0] > MAX_ALIGNED || middle[1][1] - middle[1][0] > MAX_ALIGNED) {
      // Still too many between them: each removed, then each new (paired up as changed).
      for (let i = middle[0][0]; i < middle[0][1]; i += 1) out.push({ i });
      for (let j = middle[1][0]; j < middle[1][1]; j += 1) out.push({ j });
    } else out.push(...aligned(a, b, ...middle));
    for (let n = tail; n > 0; n -= 1) out.push({ i: i1 - n, j: j1 - n });
    return out;
  }
  const width = j1 - j0 + 1;
  const lcs = new Uint16Array((i1 - i0 + 1) * width);
  const at = (i: number, j: number) => lcs[(i - i0) * width + (j - j0)] ?? 0;
  for (let i = i1 - 1; i >= i0; i -= 1) {
    for (let j = j1 - 1; j >= j0; j -= 1) {
      lcs[(i - i0) * width + (j - j0)] =
        a[i] === b[j] ? at(i + 1, j + 1) + 1 : Math.max(at(i + 1, j), at(i, j + 1));
    }
  }
  let i = i0;
  let j = j0;
  while (i < i1 || j < j1) {
    if (i < i1 && j < j1 && a[i] === b[j]) {
      out.push({ i, j });
      i += 1;
      j += 1;
    } else if (j >= j1 || (i < i1 && at(i + 1, j) >= at(i, j + 1))) {
      out.push({ i });
      i += 1;
    } else {
      out.push({ j });
      j += 1;
    }
  }
  return out;
}

/** The builder's copy of a scenario written as blocks: the file's mapping as it is. */
export function toTreeDocument(value: unknown): Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, Json>)
    : {};
}

/** Every item of `items` that holds a node (a block, a Repeat), in reading order. */
export function nodeItems(
  items: readonly Item[],
): Extract<Item, { kind: "block" } | { kind: "repeat" }>[] {
  return items.flatMap((item) => [
    ...(item.kind === "block" || item.kind === "repeat" ? [item] : []),
    ...listsOf(item).flatMap(nodeItems),
  ]);
}
