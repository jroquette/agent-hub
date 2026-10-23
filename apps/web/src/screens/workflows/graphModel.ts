import { roundedPath } from "../../lib/canvasView";

/* The workflow canvas as data: a rounds group's own steps laid out in layers, the edges a view
 * draws, a step's upstream and downstream chain, run order, and the fit of a world in a viewport.
 * Pure functions, so the canvas only draws. */

export type Doc = Record<string, unknown>;

function isDoc(value: unknown): value is Doc {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The nodes of a document (or of a group), as written. */
export function docNodes(value: unknown): Doc[] {
  return Array.isArray(value) ? value.filter(isDoc) : [];
}

/** The node as written at the top level of a document's `nodes`. */
export function documentNode(document: unknown, id: string): Doc | undefined {
  if (!isDoc(document)) return undefined;
  return docNodes(document.nodes).find((node) => node.id === id);
}

/** A step a canvas draws: a declared node, or one of a rounds group's own steps. */
export interface CanvasStep {
  /** The id the engine and the URL use: `<group>__<id>` for a group's own step. */
  id: string;
  /** The id as written in the file (without the group prefix). */
  bare: string;
  type: string;
  depends_on: string[];
  description: string | null;
  /** The node as written in the file. */
  doc: Doc | undefined;
  /** The group the step belongs to, if any. */
  group: string | null;
}

/** The body id of a group's own step, as the engine keys it. */
export function bodyId(group: string, id: string): string {
  return `${group}__${id}`;
}

/**
 * A group's own steps in layers: the longest path from a step with no wait inside the group, so a
 * step sits one column right of the last step it waits for. Waits on ids outside the group are
 * ignored; a cycle (a broken file) falls back to the order written.
 */
export function bodyLayers(groupId: string, group: Doc | undefined): CanvasStep[][] {
  const written = docNodes(group?.nodes);
  // A file may write a body id bare (`fix`) or already keyed (`fixing__fix`).
  const prefix = `${groupId}__`;
  const strip = (id: string) => (id.startsWith(prefix) ? id.slice(prefix.length) : id);
  const ids = new Set(written.map((node) => strip(String(node.id))));
  const steps = written.map((node): CanvasStep => {
    const bare = strip(String(node.id));
    const deps = Array.isArray(node.depends_on) ? node.depends_on.map((d) => strip(String(d))) : [];
    return {
      id: bodyId(groupId, bare),
      bare,
      type: typeof node.type === "string" ? node.type : "agent",
      depends_on: deps.filter((dep) => ids.has(dep)).map((dep) => bodyId(groupId, dep)),
      description: typeof node.description === "string" ? node.description : null,
      doc: node,
      group: groupId,
    };
  });
  const byId = new Map(steps.map((step) => [step.id, step]));
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const depthOf = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const step = byId.get(id);
    const d = step ? Math.max(-1, ...step.depends_on.map(depthOf)) + 1 : 0;
    visiting.delete(id);
    depth.set(id, d);
    return d;
  };
  const layers: CanvasStep[][] = [];
  for (const step of steps) {
    const d = depthOf(step.id);
    (layers[d] ??= []).push(step);
  }
  return layers.filter((layer) => layer.length > 0);
}

export interface GraphInput {
  id: string;
  type: string;
  depends_on: string[];
  description?: string | null | undefined;
}

/** Every step of a workflow the canvas can draw, by id, with each group's layers. */
export interface CanvasModel {
  steps: Map<string, CanvasStep>;
  /** A rounds group's own layers, by group id (only groups whose file lists steps). */
  groups: Map<string, CanvasStep[][]>;
}

export function canvasModel(
  layers: readonly (readonly GraphInput[])[],
  document: unknown,
): CanvasModel {
  const steps = new Map<string, CanvasStep>();
  const groups = new Map<string, CanvasStep[][]>();
  for (const node of layers.flat()) {
    const doc = documentNode(document, node.id);
    steps.set(node.id, {
      id: node.id,
      bare: node.id,
      type: node.type,
      depends_on: node.depends_on,
      description:
        node.description ?? (typeof doc?.description === "string" ? doc.description : null),
      doc,
      group: null,
    });
    if (node.type === "loop_group") {
      const body = bodyLayers(node.id, doc);
      if (body.length > 0) {
        groups.set(node.id, body);
        for (const step of body.flat()) steps.set(step.id, step);
      }
    }
  }
  return { steps, groups };
}

export type Edge = [string, string];

export function edgeKey([from, to]: Edge): string {
  return `${from}→${to}`;
}

/** The edges a view draws: each drawn depends_on, and the waits inside each open group. */
export function visibleEdges(
  layers: readonly (readonly GraphInput[])[],
  model: CanvasModel,
  open: ReadonlySet<string>,
): Edge[] {
  const ids = new Set(layers.flat().map((node) => node.id));
  const edges: Edge[] = layers
    .flat()
    .flatMap((node) =>
      node.depends_on.filter((dep) => ids.has(dep)).map((dep): Edge => [dep, node.id]),
    );
  for (const [group, body] of model.groups) {
    if (!open.has(group)) continue;
    for (const step of body.flat()) {
      for (const dep of step.depends_on) edges.push([dep, step.id]);
    }
  }
  return edges;
}

/** A step's whole chain: every step it waits on, every step that waits on it, and their edges. */
export function chainOf(
  edges: readonly Edge[],
  id: string,
): { nodes: Set<string>; edges: Set<string> } {
  const nodes = new Set<string>([id]);
  const hot = new Set<string>();
  const walk = (start: string, forward: boolean) => {
    const queue = [start];
    const seen = new Set<string>([start]);
    while (queue.length > 0) {
      const at = queue.shift();
      if (at === undefined) break;
      for (const edge of edges) {
        const [from, to] = edge;
        const near = forward ? from : to;
        const far = forward ? to : from;
        if (near !== at) continue;
        hot.add(edgeKey(edge));
        nodes.add(far);
        if (!seen.has(far)) {
          seen.add(far);
          queue.push(far);
        }
      }
    }
  };
  walk(id, true);
  walk(id, false);
  return { nodes, edges: hot };
}

/** The steps a step leads to, and the steps it waits for, among the drawn edges. */
export function neighbours(
  edges: readonly Edge[],
  id: string,
): { next: string[]; previous: string[] } {
  return {
    next: edges.filter(([from]) => from === id).map(([, to]) => to),
    previous: edges.filter(([, to]) => to === id).map(([from]) => from),
  };
}

/** The columns as drawn: each top layer, and inside it each open group's own layers after it. */
export function drawnColumns(
  layers: readonly (readonly GraphInput[])[],
  model: CanvasModel,
  open: ReadonlySet<string>,
): string[][] {
  const columns: string[][] = [];
  for (const layer of layers) {
    columns.push(layer.map((node) => node.id));
    for (const node of layer) {
      const body = model.groups.get(node.id);
      if (body && open.has(node.id)) for (const inner of body) columns.push(inner.map((s) => s.id));
    }
  }
  return columns;
}

/** Run order: the top layers in order, a group's own steps right after the group. */
export function runOrder(
  layers: readonly (readonly GraphInput[])[],
  model: CanvasModel,
  open: ReadonlySet<string>,
): string[] {
  return layers.flat().flatMap((node) => {
    const body = model.groups.get(node.id);
    return body && open.has(node.id) ? [node.id, ...body.flat().map((s) => s.id)] : [node.id];
  });
}

/** The drawn width of a card, and the gap between columns (keep in step with workflows.css). */
export const CARD_W = 216;
export const COL_GAP = 56;
export const WORLD_PAD = 32;

/** A column's width as drawn: its widest card, or an open group's frame around its own columns. */
export function columnWidth(
  layer: readonly GraphInput[],
  model: CanvasModel,
  open: ReadonlySet<string>,
): number {
  let width = CARD_W;
  for (const node of layer) {
    const body = model.groups.get(node.id);
    if (body && open.has(node.id)) {
      width = Math.max(width, body.length * CARD_W + (body.length - 1) * COL_GAP + 34);
    }
  }
  return width;
}

/**
 * The top layers packed into rows that each fit `width` (at 100%), in order; every row holds at
 * least one layer. A width of 0 (not measured yet) keeps one row.
 */
export function wrapRows(widths: readonly number[], width: number): number[][] {
  if (width <= 0 || widths.length === 0) return [widths.map((_, i) => i)];
  const rows: number[][] = [];
  let row: number[] = [];
  let used = 2 * WORLD_PAD;
  widths.forEach((w, i) => {
    const add = row.length === 0 ? w : COL_GAP + w;
    if (row.length > 0 && used + add > width) {
      rows.push(row);
      row = [];
      used = 2 * WORLD_PAD;
    }
    used += row.length === 0 ? w : COL_GAP + w;
    row.push(i);
  });
  if (row.length > 0) rows.push(row);
  return rows;
}

/**
 * An edge to a later row: out of the source to the right, down into the gap under the source's
 * row, then left to just before the target and down into it. An edge that skips rows runs down the
 * world's left gutter to the gap above the target's row instead, so it never crosses a card.
 * Corners are rounded with radius `r`.
 */
export function wrapPath(
  a: { right: number; mid: number },
  b: { left: number; mid: number },
  gapBelow: number,
  r = 10,
  skip?: { gapAbove: number; gutter: number },
): string {
  const x1 = a.right;
  const x2 = b.left;
  const out = x1 + 20;
  const into = x2 - 20;
  const pts: [number, number][] = skip
    ? [
        [x1, a.mid],
        [out, a.mid],
        [out, gapBelow],
        [skip.gutter, gapBelow],
        [skip.gutter, skip.gapAbove],
        [into, skip.gapAbove],
        [into, b.mid],
        [x2, b.mid],
      ]
    : [
        [x1, a.mid],
        [out, a.mid],
        [out, gapBelow],
        [into, gapBelow],
        [into, b.mid],
        [x2, b.mid],
      ];
  return roundedPath(pts, r);
}

/**
 * An edge between layers drawn top to bottom: out of the bottom of the source, into the top of the
 * target. To the next layer it is a vertical curve; an edge that skips layers drops into the gap
 * under the source's layer, runs down the world's left gutter to the gap above the target's layer
 * and comes in from above, so it never crosses a card. Corners are rounded with radius `r`.
 */
export function downPath(
  a: { left: number; right: number; bottom: number },
  b: { left: number; right: number; top: number },
  skip?: { gapBelow: number; gapAbove: number; gutter: number },
  r = 10,
): string {
  const x1 = (a.left + a.right) / 2;
  const x2 = (b.left + b.right) / 2;
  const y1 = a.bottom;
  const y2 = b.top;
  if (!skip) {
    const my = (y1 + y2) / 2;
    return `M ${String(x1)} ${String(y1)} C ${String(x1)} ${String(my)}, ${String(x2)} ${String(my)}, ${String(x2)} ${String(y2)}`;
  }
  return roundedPath(
    [
      [x1, y1],
      [x1, skip.gapBelow],
      [skip.gutter, skip.gapBelow],
      [skip.gutter, skip.gapAbove],
      [x2, skip.gapAbove],
      [x2, y2],
    ],
    r,
  );
}
