/* The view of a pan and zoom canvas: `translate(x, y) scale(k)` of a world in a viewport. */

export interface View {
  x: number;
  y: number;
  k: number;
}

export interface Size {
  width: number;
  height: number;
}

/** The view that shows the whole world in the viewport, never above `max` (a small graph stays 100%). */
export function fitView(world: Size, viewport: Size, { max = 1, min = 0.25, pad = 32 } = {}): View {
  if (world.width <= 0 || world.height <= 0 || viewport.width <= 0 || viewport.height <= 0) {
    return { x: 0, y: 0, k: 1 };
  }
  const k = Math.max(
    min,
    Math.min(
      max,
      (viewport.width - 2 * pad) / world.width,
      (viewport.height - 2 * pad) / world.height,
    ),
  );
  return {
    k,
    x: (viewport.width - world.width * k) / 2,
    y: (viewport.height - world.height * k) / 2,
  };
}

/** The view that puts a box (world coordinates) at the centre of the viewport, at scale `k`. */
export function centreOn(
  box: { left: number; right: number; top: number; bottom: number },
  viewport: Size,
  k: number,
): View {
  return {
    k,
    x: viewport.width / 2 - ((box.left + box.right) / 2) * k,
    y: viewport.height / 2 - ((box.top + box.bottom) / 2) * k,
  };
}

/** Zoom by `factor` around a viewport point, within [min, max]. */
export function zoomAround(
  view: View,
  factor: number,
  point: { x: number; y: number },
  min = 0.25,
  max = 2,
): View {
  const k = Math.min(max, Math.max(min, view.k * factor));
  const ratio = k / view.k;
  return { k, x: point.x - (point.x - view.x) * ratio, y: point.y - (point.y - view.y) * ratio };
}

/** A line through `points` with its corners rounded to radius `r` (an edge routed around cards). */
export function roundedPath(points: readonly (readonly [number, number])[], r = 10): string {
  const [first] = points;
  let d = first ? `M ${String(first[0])} ${String(first[1])}` : "";
  for (let i = 1; i < points.length - 1; i += 1) {
    const prev = points[i - 1];
    const cur = points[i];
    const nxt = points[i + 1];
    if (!prev || !cur || !nxt) continue;
    const [px, py] = prev;
    const [cx, cy] = cur;
    const [nx, ny] = nxt;
    const inLen = Math.hypot(cx - px, cy - py);
    const outLen = Math.hypot(nx - cx, ny - cy);
    const rr = Math.min(r, inLen / 2, outLen / 2);
    const sx = cx - ((cx - px) / (inLen || 1)) * rr;
    const sy = cy - ((cy - py) / (inLen || 1)) * rr;
    const ex = cx + ((nx - cx) / (outLen || 1)) * rr;
    const ey = cy + ((ny - cy) / (outLen || 1)) * rr;
    d += ` L ${String(sx)} ${String(sy)} Q ${String(cx)} ${String(cy)}, ${String(ex)} ${String(ey)}`;
  }
  const last = points.at(-1) ?? [0, 0];
  return `${d} L ${String(last[0])} ${String(last[1])}`;
}
