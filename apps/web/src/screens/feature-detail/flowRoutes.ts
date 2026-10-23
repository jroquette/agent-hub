import { assignLanes, roundedPath } from "../../lib/canvasView";
import type { NodeBox } from "../../lib/nodeBoxes";

/** A blocker → ticket edge to route; both ends sit in the drawn columns. */
export interface RouteEdge {
  from: string;
  to: string;
}

/** Where a line branches off a shared trunk: a dot is drawn there, lit with any line through it. */
export interface Junction {
  x: number;
  y: number;
  /** The keys (`from→to`) of the lines that pass through the point. */
  edges: string[];
}

export interface FlowRoutes {
  /** The SVG path of each edge, by key `from→to`. */
  paths: Map<string, string>;
  junctions: Junction[];
  /** The gap before each drawn column (index 0 is always 0). */
  gutters: number[];
  /** Room a channel needs above the first card and below the lowest one. */
  room: { top: number; bottom: number };
}

/** Lines leave and land at the card's id row: 10 px padding + half of the 20 px row. */
export const PORT_TOP = 20;
/** Parallel lines (lanes, slots, ports) are never closer than this. */
export const LANE = 12;
/** The narrowest gutter between two groups. */
export const GUTTER_MIN = 72;
/** The first vertical slot sits this far right of the cards it leaves. */
const SLOT_START = 24;
/** A channel under the groups it passes keeps this far below their lowest card. */
const CHANNEL_GAP = 24;
/** From the first card's top to above the group headers (32 px header, gaps). */
const HEAD = 44;
/** Corner radius: at most half the lane step, so parallel corners never touch. */
const RADIUS = 6;

const keyOf = (e: RouteEdge) => `${e.from}→${e.to}`;

/** A slot pool's spans are padded so two lines never run within a lane of each other. */
const PAD = LANE / 2;

interface Vertical {
  key: string;
  low: number;
  high: number;
}

/**
 * Routes the ticket flow's edges as orthogonal lines, left to right:
 * - every line leaves its blocker's right side and lands on the ticket's left side at the id row
 *   (a ticket with several lines gets one port each, `LANE` apart, ordered so they never cross at
 *   the card);
 * - a blocker's lines share one trunk in the gutter after it and branch off to each ticket (a single
 *   level line is drawn straight);
 * - a line that skips groups runs in a channel under the groups it passes (or above the headers
 *   when that is shorter), and drops into its ticket from a slot in the gutter before it;
 * - verticals in one gutter take slots `LANE` apart, by `assignLanes`, and the gutter widens to
 *   hold them.
 * Pure: the measured boxes in, the paths, junction dots and gutter widths out.
 */
export function routeFlow(
  columns: readonly (readonly string[])[],
  boxes: Readonly<Record<string, NodeBox>>,
  edges: readonly RouteEdge[],
): FlowRoutes {
  const gutters: number[] = columns.map((_, i) => (i === 0 ? 0 : GUTTER_MIN));
  const empty: FlowRoutes = {
    paths: new Map(),
    junctions: [],
    gutters,
    room: { top: 0, bottom: 0 },
  };
  const colOf = new Map(columns.flatMap((refs, i) => refs.map((r) => [r, i] as const)));
  const drawn = edges.filter((e) => {
    const a = colOf.get(e.from);
    const b = colOf.get(e.to);
    return a !== undefined && b !== undefined && b > a && boxes[e.from] && boxes[e.to];
  });
  if (drawn.length === 0) return empty;

  const unmeasured: NodeBox = { left: 0, right: 0, top: 0, bottom: 0, mid: 0 };
  // Every end of a drawn edge is measured (filtered above); the fallback only satisfies the type.
  const box = (ref: string): NodeBox => boxes[ref] ?? unmeasured;
  const col = (ref: string) => colOf.get(ref) ?? 0;
  const colBoxes = columns.map((refs) => refs.map((r) => boxes[r]).filter((b) => b !== undefined));
  const colRight = colBoxes.map((bs) => Math.max(...bs.map((b) => b.right)));
  const colBottom = colBoxes.map((bs) => Math.max(...bs.map((b) => b.bottom)));
  const firstTop = Math.min(...colBoxes.flat().map((b) => b.top));
  const portBase = (ref: string) => box(ref).top + PORT_TOP;
  const outY = portBase;

  // 1. Channels for the lines that skip a group: bottom or top, whichever runs less vertically.
  const skips = drawn.filter((e) => col(e.to) > col(e.from) + 1);
  const side = new Map<string, "top" | "bottom">();
  const bottomBase = (e: RouteEdge) =>
    Math.max(...colBottom.slice(col(e.from) + 1, col(e.to))) + CHANNEL_GAP;
  const topBase = firstTop - HEAD - LANE;
  for (const e of skips) {
    const a = outY(e.from);
    const b = portBase(e.to);
    const bb = bottomBase(e);
    const runBottom = Math.abs(a - bb) + Math.abs(b - bb);
    const runTop = Math.abs(a - topBase) + Math.abs(b - topBase);
    side.set(keyOf(e), runTop < runBottom ? "top" : "bottom");
  }
  // A blocker's skips on one side share one channel; overlapping channels keep a lane apart.
  const channelY = new Map<string, number>();
  for (const where of ["bottom", "top"] as const) {
    const groups = new Map<string, { start: number; end: number; base: number; keys: string[] }>();
    for (const e of skips) {
      if (side.get(keyOf(e)) !== where) continue;
      const base = where === "bottom" ? bottomBase(e) : topBase;
      const g = groups.get(e.from);
      if (g) {
        g.start = Math.min(g.start, col(e.from));
        g.end = Math.max(g.end, col(e.to));
        g.base = where === "bottom" ? Math.max(g.base, base) : g.base;
        g.keys.push(keyOf(e));
      } else {
        groups.set(e.from, { start: col(e.from), end: col(e.to), base, keys: [keyOf(e)] });
      }
    }
    const placed: { start: number; end: number; y: number }[] = [];
    const ordered = [...groups.values()].sort(
      (a, b) => a.end - a.start - (b.end - b.start) || a.start - b.start,
    );
    for (const g of ordered) {
      let y = g.base;
      const step = where === "bottom" ? LANE : -LANE;
      while (placed.some((p) => p.start < g.end && g.start < p.end && Math.abs(p.y - y) < LANE)) {
        y += step;
      }
      placed.push({ start: g.start, end: g.end, y });
      for (const k of g.keys) channelY.set(k, y);
    }
  }

  // 2. In ports, first by where each line arrives from (refined once the slots are known).
  const incoming = new Map<string, RouteEdge[]>();
  for (const e of drawn) incoming.set(e.to, [...(incoming.get(e.to) ?? []), e]);
  const arriveY = (e: RouteEdge) => channelY.get(keyOf(e)) ?? outY(e.from);
  const portY = new Map<string, number>();
  const placePorts = (ref: string, order: readonly RouteEdge[]) => {
    const b = box(ref);
    const base = b.top + PORT_TOP;
    const room = b.bottom - 16 - base;
    const step = order.length > 1 ? Math.max(6, Math.min(LANE, room / (order.length - 1))) : LANE;
    order.forEach((e, i) => portY.set(keyOf(e), base + step * i));
  };
  for (const [ref, list] of incoming) {
    placePorts(
      ref,
      [...list].sort((a, b) => arriveY(a) - arriveY(b) || a.from.localeCompare(b.from)),
    );
  }

  // A blocker whose one line goes level into the next group is drawn straight, with no slot.
  const outgoing = new Map<string, RouteEdge[]>();
  for (const e of drawn) outgoing.set(e.from, [...(outgoing.get(e.from) ?? []), e]);
  const straight = new Set<string>();
  for (const [from, list] of outgoing) {
    const [only] = list;
    if (
      list.length === 1 &&
      only &&
      col(only.to) === col(from) + 1 &&
      (incoming.get(only.to)?.length ?? 0) === 1 &&
      Math.abs((portY.get(keyOf(only)) ?? 0) - outY(from)) <= 2
    ) {
      straight.add(keyOf(only));
    }
  }

  // 3. Slots in each gutter: the leaving trunks and the arriving skip drops, side by side.
  const trunkX = new Map<string, number>(); // by source ref
  const dropX = new Map<string, number>(); // by `${source}@${column}`
  const verticalsOf = (keys: Iterable<string>, ys: (key: string) => number[]): Vertical[] =>
    [...keys].map((key) => {
      const all = ys(key);
      return { key, low: Math.min(...all), high: Math.max(...all) };
    });
  for (let g = 0; g < columns.length - 1; g += 1) {
    const leaving = new Map<string, number[]>();
    const arriving = new Map<string, number[]>();
    for (const e of drawn) {
      const k = keyOf(e);
      if (col(e.from) === g && !straight.has(k)) {
        const ys = leaving.get(e.from) ?? [outY(e.from)];
        ys.push(channelY.get(k) ?? portY.get(k) ?? 0);
        leaving.set(e.from, ys);
      }
      if (col(e.to) === g + 1 && channelY.has(k)) {
        const id = `${e.from}@${String(g + 1)}`;
        const ys = arriving.get(id) ?? [channelY.get(k) ?? 0];
        ys.push(portY.get(k) ?? 0);
        arriving.set(id, ys);
      }
    }
    const leave = verticalsOf(leaving.keys(), (k) => leaving.get(k) ?? []);
    const arrive = verticalsOf(arriving.keys(), (k) => arriving.get(k) ?? []);
    const lanesOf = (vs: Vertical[]) =>
      assignLanes(vs.map((v) => ({ id: v.key, start: v.low - PAD, end: v.high + PAD })));
    const leaveLanes = lanesOf(leave);
    const arriveLanes = lanesOf(arrive);
    const nLeave = leave.length ? Math.max(...leaveLanes.values()) + 1 : 0;
    const nArrive = arrive.length ? Math.max(...arriveLanes.values()) + 1 : 0;
    // Arriving left of leaving, or the reverse: keep the one whose horizontals cross fewer verticals.
    const inside = (y: number, v: Vertical) => y > v.low + 0.5 && y < v.high - 0.5;
    let arriveLeft = 0;
    let arriveRight = 0;
    for (const a of arrive) {
      const [from] = a.key.split("@");
      const branches = drawn
        .filter((e) => e.from === from && col(e.to) === g + 1 && channelY.has(keyOf(e)))
        .map((e) => portY.get(keyOf(e)) ?? 0);
      const chY = (arriving.get(a.key) ?? [0])[0] ?? 0;
      for (const l of leave) {
        const lb = drawn
          .filter((e) => e.from === l.key && !channelY.has(keyOf(e)))
          .map((e) => portY.get(keyOf(e)) ?? 0);
        if (inside(outY(l.key), a)) arriveLeft += 1;
        arriveLeft += branches.filter((y) => inside(y, l)).length;
        if (inside(chY, l)) arriveRight += 1;
        arriveRight += lb.filter((y) => inside(y, a)).length;
      }
    }
    const leftFirst = arriveLeft <= arriveRight;
    const x0 = (colRight[g] ?? 0) + SLOT_START;
    for (const v of leave) {
      const lane = (leaveLanes.get(v.key) ?? 0) + (leftFirst ? nArrive : 0);
      trunkX.set(v.key, x0 + LANE * lane);
    }
    for (const v of arrive) {
      const lane = (arriveLanes.get(v.key) ?? 0) + (leftFirst ? 0 : nLeave);
      dropX.set(v.key, x0 + LANE * lane);
    }
    const slots = nLeave + nArrive;
    gutters[g + 1] = slots > 0 ? Math.max(GUTTER_MIN, 56 + LANE * (slots - 1)) : GUTTER_MIN;
  }

  // The x of the last vertical a line runs down (or up) before it turns into its ticket.
  const lastX = (e: RouteEdge) => {
    const k = keyOf(e);
    if (straight.has(k)) return Number.NEGATIVE_INFINITY;
    if (channelY.has(k)) return dropX.get(`${e.from}@${String(col(e.to))}`) ?? 0;
    return trunkX.get(e.from) ?? 0;
  };

  // 4. Final ports: from above first (the further left lower, nested), then level, then from below
  //    (the further left higher), so no two lines cross at the card.
  for (const [ref, list] of incoming) {
    const base = portBase(ref);
    const above = list.filter((e) => arriveY(e) < base - 2);
    const below = list.filter((e) => arriveY(e) > base + 2);
    const level = list.filter((e) => !above.includes(e) && !below.includes(e));
    above.sort((a, b) => lastX(b) - lastX(a) || a.from.localeCompare(b.from));
    below.sort((a, b) => lastX(a) - lastX(b) || a.from.localeCompare(b.from));
    placePorts(ref, [...above, ...level, ...below]);
  }

  // 5. The paths.
  const paths = new Map<string, string>();
  for (const e of drawn) {
    const k = keyOf(e);
    const a = box(e.from);
    const b = box(e.to);
    const oy = outY(e.from);
    const iy = portY.get(k) ?? b.top + PORT_TOP;
    if (straight.has(k)) {
      paths.set(k, `M ${String(a.right)} ${String(oy)} L ${String(b.left)} ${String(iy)}`);
      continue;
    }
    const tx = trunkX.get(e.from) ?? a.right + SLOT_START;
    const chY = channelY.get(k);
    if (chY === undefined) {
      paths.set(
        k,
        roundedPath(
          [
            [a.right, oy],
            [tx, oy],
            [tx, iy],
            [b.left, iy],
          ],
          RADIUS,
        ),
      );
      continue;
    }
    const dx = dropX.get(`${e.from}@${String(col(e.to))}`) ?? b.left - SLOT_START;
    paths.set(
      k,
      roundedPath(
        [
          [a.right, oy],
          [tx, oy],
          [tx, chY],
          [dx, chY],
          [dx, iy],
          [b.left, iy],
        ],
        RADIUS,
      ),
    );
  }

  // 6. Junction dots: where a line leaves a trunk that goes on (never at a trunk's far corner).
  const dots = new Map<string, Junction>();
  const addDot = (x: number, y: number, keys: string[]) => {
    const id = `${String(Math.round(x))},${String(Math.round(y))}`;
    const dot = dots.get(id);
    if (dot) dot.edges = [...new Set([...dot.edges, ...keys])];
    else dots.set(id, { x, y, edges: keys });
  };
  /** Branch points along one vertical from `origin`: a dot wherever the vertical goes on. */
  const branchDots = (x: number, origin: number, branches: { y: number; key: string }[]) => {
    if (branches.length < 2) return;
    const ys = [origin, ...branches.map((br) => br.y)];
    const low = Math.min(...ys);
    const high = Math.max(...ys);
    for (const y of new Set(branches.map((br) => br.y))) {
      const atOrigin = Math.abs(y - origin) < 0.5;
      if (!atOrigin && (y <= low + 0.5 || y >= high - 0.5)) continue;
      const through = branches
        .filter(
          (br) =>
            atOrigin ||
            (Math.sign(br.y - origin) === Math.sign(y - origin) &&
              Math.abs(br.y - origin) >= Math.abs(y - origin) - 0.5),
        )
        .map((br) => br.key);
      addDot(x, y, through);
    }
  };
  for (const [from, list] of outgoing) {
    const tx = trunkX.get(from);
    if (tx === undefined) continue;
    branchDots(
      tx,
      outY(from),
      list.map((e) => ({ y: channelY.get(keyOf(e)) ?? portY.get(keyOf(e)) ?? 0, key: keyOf(e) })),
    );
    // A blocker's skips share a channel: a dot where a nearer one drops out of it.
    const sk = list.filter((e) => channelY.has(keyOf(e)));
    for (const e of sk) {
      const further = sk.filter((o) => col(o.to) > col(e.to));
      const dx = dropX.get(`${from}@${String(col(e.to))}`);
      if (further.length > 0 && dx !== undefined) {
        addDot(dx, channelY.get(keyOf(e)) ?? 0, [keyOf(e), ...further.map(keyOf)]);
      }
    }
  }
  for (const [id, x] of dropX) {
    const [from, at] = id.split("@");
    const list = drawn.filter(
      (e) => e.from === from && String(col(e.to)) === at && channelY.has(keyOf(e)),
    );
    const [first] = list;
    if (!first) continue;
    branchDots(
      x,
      channelY.get(keyOf(first)) ?? 0,
      list.map((e) => ({ y: portY.get(keyOf(e)) ?? 0, key: keyOf(e) })),
    );
  }

  const ys = [...channelY.values()];
  const lowest = Math.max(...colBottom);
  return {
    paths,
    junctions: [...dots.values()],
    gutters,
    room: {
      top: ys.length ? Math.max(0, firstTop - HEAD - (Math.min(...ys) - LANE)) : 0,
      bottom: ys.length ? Math.max(0, Math.max(...ys) + LANE * 2 - lowest) : 0,
    },
  };
}

/** Group 1 by ticket id; each later group under its blockers (the mean of their slots), then by
 * id. Order depends on the links and ids only, so no card moves when a ticket changes state. */
export function orderUnderBlockers(
  steps: readonly (readonly string[])[],
  blockersOf: (ref: string) => readonly string[],
): string[][] {
  const byId = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });
  const slot = new Map<string, number>();
  return steps.map((step) => {
    const keyed = step.map((ref) => {
      const at = blockersOf(ref)
        .map((b) => slot.get(b))
        .filter((n): n is number => n !== undefined);
      const key = at.length ? at.reduce((s, n) => s + n, 0) / at.length : Infinity;
      return { ref, key };
    });
    keyed.sort((a, b) => (a.key === b.key ? 0 : a.key < b.key ? -1 : 1) || byId(a.ref, b.ref));
    const ordered = keyed.map((k) => k.ref);
    ordered.forEach((ref, i) => slot.set(ref, i));
    return ordered;
  });
}
