/* A scenario as a block program (the builder's Scratch-like view): stacks of blocks, where a block
 * snapped under another waits for it, and C-blocks that hold other blocks: Repeat (a
 * `loop_group`), If / else (the engine's `when` on the first block of each path, the else path
 * the condition negated, and the blocks after it joining with `none_failed_min_one_success`) and
 * At the same time (sibling paths that start together, joined by the next block).
 *
 * It is a reading of the document, not a second format: `programOf` reads the `nodes` of a
 * scenario into a program, `nodesOf` writes a program back to `nodes`, and nothing else is stored.
 * What the blocks cannot show (a graph that is not nested paths) stays as loose blocks, as
 * written. */

import {
  dependsOn,
  formatCondition,
  parseCondition,
  without,
  type BuilderNode,
  type ConditionRow,
} from "./model";

export type Item =
  | { kind: "block"; node: BuilderNode }
  | { kind: "repeat"; node: BuilderNode; body: Item[] }
  | { kind: "if"; key: string; condition: string; then: Item[]; otherwise: Item[] }
  | { kind: "parallel"; key: string; lanes: Item[][] };

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

/** Where a list of items is: the main stack, a repeat's body, an If path or a lane. */
export type Slot =
  | { in: "main" }
  | { in: "body"; owner: string }
  | { in: "then" | "otherwise"; owner: string }
  | { in: "lane"; owner: string; lane: number };

export function itemId(item: Item): string {
  return item.kind === "block" || item.kind === "repeat" ? item.node.id : item.key;
}

function mapLists(items: Item[], slot: Slot, fn: (list: Item[]) => Item[]): Item[] {
  if (slot.in === "main") return fn(items);
  return items.map((item) => {
    const id = itemId(item);
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
    const inner =
      item.kind === "repeat"
        ? findItem(item.body, id)
        : item.kind === "if"
          ? (findItem(item.then, id) ?? findItem(item.otherwise, id))
          : item.kind === "parallel"
            ? item.lanes.reduce<Item | null>((found, lane) => found ?? findItem(lane, id), null)
            : null;
    if (inner) return inner;
  }
  return null;
}

/** Every node of a program (to name a fresh id). */
export function programNodes(items: readonly Item[]): BuilderNode[] {
  return items.flatMap((item) => {
    if (item.kind === "block") return [item.node];
    if (item.kind === "repeat") return [item.node, ...programNodes(item.body)];
    if (item.kind === "if") return [...programNodes(item.then), ...programNodes(item.otherwise)];
    return item.lanes.flatMap(programNodes);
  });
}

type Located = { slot: Slot; index: number } | null;

/** Where the item `id` sits: its list and its index there (null when absent). */
export function locate(items: readonly Item[], id: string, slot: Slot = { in: "main" }): Located {
  for (const [index, item] of items.entries()) {
    if (itemId(item) === id) return { slot, index };
    let inner: Located = null;
    if (item.kind === "repeat") inner = locate(item.body, id, { in: "body", owner: item.node.id });
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
 * across an If's two paths and across lanes, so each block has its own number. */
export function stepNumbers(items: readonly Item[], prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  const walk = (list: readonly Item[], head: string, start: number): number => {
    let n = start;
    for (const item of list) {
      n += 1;
      const label = `${head}${String(n)}`;
      out.set(itemId(item), label);
      const inner =
        item.kind === "repeat"
          ? [item.body]
          : item.kind === "if"
            ? [item.then, item.otherwise]
            : item.kind === "parallel"
              ? item.lanes
              : [];
      let m = 0;
      for (const body of inner) m = walk(body, `${label}.`, m);
    }
    return n;
  };
  walk(items, prefix, 0);
  return out;
}
