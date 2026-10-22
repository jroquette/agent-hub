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
