/* The scenario builder's document model: a scenario as the JSON the builder edits (the file's
 * mapping, keys as the engine writes them), and the pure edits the canvas and the inspector
 * make on it. The engine's semantics only: a block is a node, an edge is `depends_on`, a branch
 * is sibling blocks with a `when`, a repeat is a `loop_group`. Nothing here talks to the API. */

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type BuilderNode = { id: string; type: string } & Record<string, Json>;
export interface BuilderDocument {
  [key: string]: Json;
  nodes: BuilderNode[];
}

export type BlockKind = "action" | "expect" | "approval" | "wait" | "loop_group" | "include";

function isRecord(value: unknown): value is Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The builder's copy of a scenario file's mapping (a missing `nodes` reads as none). */
export function toDocument(value: unknown): BuilderDocument {
  const record = isRecord(value) ? value : {};
  const nodes = Array.isArray(record.nodes) ? record.nodes.filter(isNode) : [];
  return { ...record, nodes };
}

function isNode(value: unknown): value is BuilderNode {
  return isRecord(value) && typeof value.id === "string" && typeof value.type === "string";
}

export function dependsOn(node: BuilderNode): string[] {
  return Array.isArray(node.depends_on)
    ? node.depends_on.filter((item): item is string => typeof item === "string")
    : [];
}

/** Layers of blocks, top to bottom: a block sits one layer below the last block it waits for
 * (the engine's Kahn layers), in document order inside a layer. A cycle falls back to order. */
export function layersOf(nodes: readonly BuilderNode[]): BuilderNode[][] {
  const ids = new Set(nodes.map((node) => node.id));
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const depthOf = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const node = byId.get(id);
    const parents = node ? dependsOn(node).filter((parent) => ids.has(parent)) : [];
    const value = parents.length === 0 ? 0 : 1 + Math.max(...parents.map(depthOf));
    visiting.delete(id);
    depth.set(id, value);
    return value;
  };
  const layers: BuilderNode[][] = [];
  for (const node of nodes) {
    const at = depthOf(node.id);
    (layers[at] ??= []).push(node);
  }
  return layers.filter((layer) => layer.length > 0);
}

/** The edges among `nodes` (parent → child), only between blocks of the same level. */
export function edgesOf(nodes: readonly BuilderNode[]): [string, string][] {
  const ids = new Set(nodes.map((node) => node.id));
  return nodes.flatMap((node) =>
    dependsOn(node)
      .filter((parent) => ids.has(parent))
      .map((parent): [string, string] => [parent, node.id]),
  );
}

/** A fresh id for a kind: `check`, `check-2`… never one already in the document. */
export function freshId(document: BuilderDocument, base: string): string {
  const taken = new Set(allNodes(document.nodes).map((node) => node.id));
  if (!taken.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const id = `${base}-${String(n)}`;
    if (!taken.has(id)) return id;
  }
}

/** Every node, a repeat's body included. */
export function allNodes(nodes: readonly BuilderNode[]): BuilderNode[] {
  return nodes.flatMap((node) => [
    node,
    ...(Array.isArray(node.nodes) ? allNodes(node.nodes.filter(isNode)) : []),
  ]);
}

/** A `with` value that only repeats the run's value of the same name (`x: $INPUTS.x`). */
export function passesRunValue(name: string, value: Json | undefined): boolean {
  return value === `$INPUTS.${name}`;
}

/** The document without the `with` values that only repeat a run value: each such input takes
 * the run's value anyway (an action input a step leaves out takes the scenario input of its
 * name). Returns the document and how many values it dropped. */
export function withoutRunRepeats(document: BuilderDocument): {
  document: BuilderDocument;
  dropped: number;
} {
  let dropped = 0;
  const clean = (nodes: readonly BuilderNode[]): BuilderNode[] =>
    nodes.map((node) => {
      let next: BuilderNode = node;
      const given = node.with;
      if (typeof given === "object" && given !== null && !Array.isArray(given)) {
        const kept = Object.entries(given).filter(([name, value]) => {
          const repeat = passesRunValue(name, value);
          if (repeat) dropped += 1;
          return !repeat;
        });
        if (kept.length !== Object.keys(given).length) {
          next =
            kept.length > 0 ? { ...node, with: Object.fromEntries(kept) } : without(node, "with");
        }
      }
      if (Array.isArray(node.nodes)) next = { ...next, nodes: clean(node.nodes.filter(isNode)) };
      return next;
    });
  const nodes = clean(document.nodes);
  return { document: { ...document, nodes }, dropped };
}

const BASE_ID: Readonly<Record<BlockKind, string>> = {
  action: "script",
  expect: "check",
  approval: "manual-step",
  wait: "pause",
  loop_group: "repeat",
  include: "sub-flow",
};

/** A new block of `kind` with the keys its node needs to load (filled with defaults). */
export function newBlock(document: BuilderDocument, kind: BlockKind, action?: string): BuilderNode {
  const base = action ? (action.split("/").at(-1) ?? BASE_ID[kind]) : BASE_ID[kind];
  const id = freshId(document, base);
  switch (kind) {
    case "action":
      return { id, type: "action", action: action ?? "" };
    case "expect":
      return {
        id,
        type: "expect",
        action: action ?? "",
        every: "10s",
        timeout: "5m",
        until_when: "",
      };
    case "approval":
      return {
        id,
        type: "approval",
        message: "Do this by hand, then say how it went.",
        decisions: [
          { id: "done", label: "Done" },
          { id: "stop", label: "Stop" },
        ],
      };
    case "wait":
      return { id, type: "wait", duration: "30s" };
    case "loop_group":
      return { id, type: "loop_group", max_iterations: 3, until_when: "", nodes: [] };
    case "include":
      return { id, type: "include", include: "" };
  }
}

/** The list a block lives in: the top level, or a repeat's body (`group` its id). */
function listOf(document: BuilderDocument, group: string | null): BuilderNode[] {
  if (group === null) return document.nodes;
  const owner = allNodes(document.nodes).find((node) => node.id === group);
  return owner && Array.isArray(owner.nodes) ? owner.nodes.filter(isNode) : [];
}

function withList(
  document: BuilderDocument,
  group: string | null,
  list: BuilderNode[],
): BuilderDocument {
  if (group === null) return { ...document, nodes: list };
  const swap = (nodes: BuilderNode[]): BuilderNode[] =>
    nodes.map((node) =>
      node.id === group
        ? { ...node, nodes: list }
        : Array.isArray(node.nodes)
          ? { ...node, nodes: swap(node.nodes.filter(isNode)) }
          : node,
    );
  return { ...document, nodes: swap(document.nodes) };
}

/** Where a block is: the id of the repeat holding it, or null at the top level. */
export function groupOf(document: BuilderDocument, id: string): string | null {
  const search = (
    nodes: readonly BuilderNode[],
    group: string | null,
  ): string | null | undefined => {
    for (const node of nodes) {
      if (node.id === id) return group;
      if (Array.isArray(node.nodes)) {
        const found = search(node.nodes.filter(isNode), node.id);
        if (found !== undefined) return found;
      }
    }
    return undefined;
  };
  return search(document.nodes, null) ?? null;
}

/**
 * Inserts `block` after `after` in its list (null: at the end, after the last blocks): the block
 * waits for `after`, and the blocks that waited for `after` now wait for the block, so it slides
 * into the chain. At the end it waits for the list's last blocks (those no block waits for).
 */
export function insertAfter(
  document: BuilderDocument,
  block: BuilderNode,
  after: string | null,
  group: string | null = after === null ? null : groupOf(document, after),
): BuilderDocument {
  const list = listOf(document, group);
  if (after === null) {
    const waited = new Set(list.flatMap(dependsOn));
    const sinks = list.filter((node) => !waited.has(node.id)).map((node) => node.id);
    const placed = sinks.length > 0 ? { ...block, depends_on: sinks } : stripDeps(block);
    return withList(document, group, [...list, placed]);
  }
  const index = list.findIndex((node) => node.id === after);
  const placed = { ...block, depends_on: [after] };
  const rewired = list.map((node) =>
    dependsOn(node).includes(after)
      ? {
          ...node,
          depends_on: dependsOn(node).map((parent) => (parent === after ? block.id : parent)),
        }
      : node,
  );
  const next = [...rewired.slice(0, index + 1), placed, ...rewired.slice(index + 1)];
  return withList(document, group, next);
}

/** Adds `block` beside `sibling`: it waits for what `sibling` waits for (a parallel path). */
export function insertBeside(
  document: BuilderDocument,
  block: BuilderNode,
  sibling: string,
): BuilderDocument {
  const group = groupOf(document, sibling);
  const list = listOf(document, group);
  const index = list.findIndex((node) => node.id === sibling);
  const parents = dependsOn(list[index] ?? block);
  const placed = parents.length > 0 ? { ...block, depends_on: parents } : stripDeps(block);
  return withList(document, group, [...list.slice(0, index + 1), placed, ...list.slice(index + 1)]);
}

/** Two paths after `source`: each first block runs only when its condition holds. */
export function insertBranch(
  document: BuilderDocument,
  source: string,
  field: string,
  values: readonly [string, string],
): BuilderDocument {
  const group = groupOf(document, source);
  let next = document;
  for (const value of values) {
    const block = {
      ...newBlock(next, "action"),
      id: freshId(next, `if-${slug(value) || "path"}`),
      when: formatCondition([[{ field, op: "==", value }]]),
    };
    const list = listOf(next, group);
    next = withList(next, group, [...list, { ...block, depends_on: [source] }]);
  }
  return next;
}

function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 24);
}

function stripDeps(block: BuilderNode): BuilderNode {
  return without(block, "depends_on");
}

/** A copy of `value` without `key` (never a dynamic delete). */
export function without<T extends Record<string, Json>>(value: T, key: string): T {
  return Object.fromEntries(Object.entries(value).filter(([name]) => name !== key)) as T;
}

/** A JSON value as text for a field: a string as is, a number or boolean as JSON, else "". */
export function text(value: Json | undefined, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

/** A JSON value as one line of text (a string as is, anything else as JSON). */
export function shown(value: Json | undefined): string {
  return typeof value === "string" ? value : JSON.stringify(value ?? null);
}

/** Removes a block: the blocks that waited for it wait for what it waited for instead. */
export function removeBlock(document: BuilderDocument, id: string): BuilderDocument {
  const group = groupOf(document, id);
  const list = listOf(document, group);
  const gone = list.find((node) => node.id === id);
  if (!gone) return document;
  const parents = dependsOn(gone);
  const next = list
    .filter((node) => node.id !== id)
    .map((node) => {
      if (!dependsOn(node).includes(id)) return node;
      const deps = [
        ...new Set(dependsOn(node).flatMap((parent) => (parent === id ? parents : [parent]))),
      ];
      return deps.length > 0 ? { ...node, depends_on: deps } : stripDeps(node);
    });
  return withList(document, group, next);
}

/** Replaces block `id` with `next` (a rename rewrites what waits for it and its references). */
export function updateBlock(
  document: BuilderDocument,
  id: string,
  next: BuilderNode,
): BuilderDocument {
  const group = groupOf(document, id);
  const list = listOf(document, group).map((node) => (node.id === id ? next : node));
  let updated = withList(document, group, list);
  if (next.id !== id) {
    const text = JSON.stringify(updated)
      .split(`"${id}"`)
      .join(`"${next.id}"`)
      .split(`$${id}.output`)
      .join(`$${next.id}.output`);
    updated = toDocument(JSON.parse(text));
  }
  return updated;
}

/** Moves a block one place up or down in its list (document order, the layer's order). */
export function moveBlock(document: BuilderDocument, id: string, by: -1 | 1): BuilderDocument {
  const group = groupOf(document, id);
  const list = [...listOf(document, group)];
  const index = list.findIndex((node) => node.id === id);
  const target = index + by;
  if (index < 0 || target < 0 || target >= list.length) return document;
  const [item] = list.splice(index, 1);
  if (item) list.splice(target, 0, item);
  return withList(document, group, list);
}

/* ---------- Values a block may read ---------- */

export interface ValueSource {
  /** The reference written in the file: `$INPUTS.x`, `$CTX.x`, `$node.output.path`. */
  ref: string;
  label: string;
  group: "Scenario inputs" | "Kept earlier" | "Typed by you" | "Outputs of earlier blocks";
  hint: string;
}

/** The blocks upstream of `id` (what it waits for, transitively). */
export function upstreamOf(document: BuilderDocument, id: string): BuilderNode[] {
  const nodes = allNodes(document.nodes);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const seen = new Set<string>();
  const walk = (at: string) => {
    const node = byId.get(at);
    if (!node) return;
    for (const parent of dependsOn(node)) {
      if (!seen.has(parent)) {
        seen.add(parent);
        walk(parent);
      }
    }
  };
  walk(id);
  const group = groupOf(document, id);
  if (group !== null) {
    seen.add(group);
    walk(group);
  }
  return nodes.filter((node) => seen.has(node.id) && node.id !== group);
}

/** What a block may read: the scenario inputs, values kept upstream, a manual step's typed
 * answer, and an upstream action's output fields (`outputs` by action ref). */
export function valueSources(
  document: BuilderDocument,
  id: string,
  outputs: (action: string) => readonly string[],
): ValueSource[] {
  const sources: ValueSource[] = [];
  const inputs = isRecord(document.inputs) ? Object.keys(document.inputs) : [];
  for (const name of inputs) {
    sources.push({ ref: `$INPUTS.${name}`, label: name, group: "Scenario inputs", hint: "input" });
  }
  for (const node of upstreamOf(document, id)) {
    if (isRecord(node.capture)) {
      for (const name of Object.keys(node.capture)) {
        sources.push({
          ref: `$CTX.${name}`,
          label: name,
          group: "Kept earlier",
          hint: `kept by ${node.id}`,
        });
      }
    }
    if (node.type === "approval" && node.capture_response === true) {
      sources.push({
        ref: `$${node.id}.output.text`,
        label: `${node.id} · typed answer`,
        group: "Typed by you",
        hint: "what you type at this manual step",
      });
    }
    if ((node.type === "action" || node.type === "expect") && typeof node.action === "string") {
      for (const path of outputs(node.action)) {
        sources.push({
          ref: `$${node.id}.output.${path}`,
          label: `${node.id} · ${path}`,
          group: "Outputs of earlier blocks",
          hint: `from ${node.id}`,
        });
      }
    }
  }
  return sources;
}

/** A reference in words: "input target", "kept record_id", "from fetch · status". */
export function refInWords(value: string): { text: string; ref: boolean } {
  const input = /^\$INPUTS\.([A-Za-z0-9_]+)$/.exec(value);
  if (input) return { text: `input ${input[1] ?? ""}`, ref: true };
  const kept = /^\$CTX\.([A-Za-z0-9_]+)$/.exec(value);
  if (kept) return { text: kept[1] ?? "", ref: true };
  const self = /^\$self\.output\.(.+)$/.exec(value);
  if (self) return { text: self[1] ?? "", ref: true };
  const output = /^\$([a-z0-9_-]+)\.output(?:\.(.+))?$/i.exec(value);
  if (output) return { text: `${output[1] ?? ""} · ${output[2] ?? "output"}`, ref: true };
  return { text: value, ref: false };
}

/* ---------- Conditions (`when`, `until_when`) ---------- */

export interface ConditionRow {
  field: string;
  op: string;
  value: string;
}

export const OPERATORS: readonly { op: string; words: string }[] = [
  { op: "==", words: "is" },
  { op: "!=", words: "is not" },
  { op: ">", words: "is above" },
  { op: "<", words: "is below" },
  { op: ">=", words: "is at least" },
  { op: "<=", words: "is at most" },
];

const ATOM = /^\s*(\$[A-Za-z0-9_.-]+)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$/;

/** `a == 'x' && b > 2 || c == true` as "or" groups of "and" rows (the grammar's shape: `&&`
 * binds tighter, no parentheses); null when it is not that shape (shown as written). */
export function parseCondition(text: string): ConditionRow[][] | null {
  if (text.trim() === "") return [];
  const groups = text.split("||").map((group) =>
    group.split("&&").map((atom) => {
      const match = ATOM.exec(atom);
      if (!match) return null;
      const raw = match[3] ?? "";
      const quoted = /^'(.*)'$/.exec(raw);
      return {
        field: match[1] ?? "",
        op: match[2] ?? "==",
        value: quoted ? (quoted[1] ?? "") : raw,
      };
    }),
  );
  if (groups.some((group) => group.some((row) => row === null))) return null;
  return groups as ConditionRow[][];
}

function literal(value: string): string {
  const trimmed = value.trim();
  if (/^-?\d+(\.\d+)?$/.test(trimmed) || trimmed === "true" || trimmed === "false") return trimmed;
  return `'${trimmed.replace(/'/g, "")}'`;
}

export function formatCondition(groups: readonly (readonly ConditionRow[])[]): string {
  return groups
    .map((group) =>
      group
        .filter((row) => row.field !== "")
        .map((row) => `${row.field} ${row.op} ${literal(row.value)}`)
        .join(" && "),
    )
    .filter((group) => group !== "")
    .join(" || ");
}

/** A condition in words: "status is 200 and state is DONE". */
export function conditionWords(text: string): string {
  const groups = parseCondition(text);
  if (groups === null) return text;
  return groups
    .map((group) =>
      group
        .map(
          (row) =>
            `${refInWords(row.field).text} ${OPERATORS.find((item) => item.op === row.op)?.words ?? row.op} ${row.value}`,
        )
        .join(" and "),
    )
    .join(" or ");
}

/* ---------- A condition typed in words ---------- */

// Longest phrases first, so "is not" wins over "is".
const PHRASES: readonly [string, string][] = [
  ["is greater than or equal to", ">="],
  ["is less than or equal to", "<="],
  ["is greater than", ">"],
  ["is less than", "<"],
  ["is at least", ">="],
  ["is at most", "<="],
  ["is above", ">"],
  ["is below", "<"],
  ["is not", "!="],
  ["isn't", "!="],
  ["equals", "=="],
  ["is", "=="],
  ["!=", "!="],
  [">=", ">="],
  ["<=", "<="],
  ["==", "=="],
  ["=", "=="],
  [">", ">"],
  ["<", "<"],
];

function plain(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]/g, "");
}

export type WordsResult = { ok: true; groups: ConditionRow[][] } | { ok: false; problem: string };

/**
 * A condition typed in words ("status is 200 and state is not DONE", "count >= 3 or ready is
 * true") as or-groups of and-rows, each field matched against the `fields` this place may
 * compare (by name, ignoring case, spaces and `_`). Generic: it knows only these field names and
 * the operator words, nothing about any system; what it cannot match it says, and guesses nothing.
 */
export function conditionFromWords(
  text: string,
  fields: readonly { ref: string; label: string }[],
): WordsResult {
  const groups: ConditionRow[][] = [];
  for (const group of text.split(/\s+or\s+/i)) {
    const rows: ConditionRow[] = [];
    for (const atom of group.split(/\s+and\s+/i)) {
      const lower = atom.toLowerCase();
      let found: { at: number; phrase: string; op: string } | null = null;
      for (const [phrase, op] of PHRASES) {
        const symbolic = /^[!<>=]+$/.test(phrase);
        const at = symbolic
          ? lower.indexOf(phrase)
          : lower.search(new RegExp(`\\s${phrase.replace(/'/g, "'")}\\s`));
        if (at > 0) {
          found = { at: symbolic ? at : at + 1, phrase, op };
          break;
        }
      }
      if (!found)
        return {
          ok: false,
          problem: `No comparison in “${atom.trim()}”: use is, is not, is above, is below, is at least, is at most.`,
        };
      const left = atom.slice(0, found.at).trim();
      const right = atom
        .slice(found.at + found.phrase.length)
        .trim()
        .replace(/^['"]|['"]$/g, "");
      const wanted = plain(left);
      const field =
        fields.find((item) => plain(item.label) === wanted) ??
        fields.find((item) => plain(item.ref.split(".").at(-1) ?? "") === wanted) ??
        fields.find((item) => plain(item.label).endsWith(wanted) && wanted.length >= 3);
      if (!field) {
        const names = fields.map((item) => item.label).join(", ") || "none here";
        return { ok: false, problem: `No field “${left}” here. Fields you can compare: ${names}.` };
      }
      if (right === "") return { ok: false, problem: `No value after “${left} ${found.phrase}”.` };
      rows.push({ field: field.ref, op: found.op, value: right });
    }
    groups.push(rows);
  }
  return { ok: true, groups };
}
