import { useLayoutEffect, useState } from "react";
import type { RefObject } from "react";

/** Where a graph node sits inside its scrolling root, in content coordinates. */
export interface NodeBox {
  left: number;
  right: number;
  top: number;
  bottom: number;
  /** The vertical middle, where a left-to-right edge meets the node. */
  mid: number;
}

/**
 * Measures every `[data-node-id]` element under `root` so an SVG layer can draw edges between
 * them. Re-measures when `shape` changes (not on every render) and when the root or a node
 * resizes, since a node that reflows moves its edges without resizing the root.
 */
export function useNodeBoxes(
  root: RefObject<HTMLElement | null>,
  shape: string,
): { boxes: Readonly<Record<string, NodeBox>>; size: { width: number; height: number } } {
  const [boxes, setBoxes] = useState<Record<string, NodeBox>>({});
  const [size, setSize] = useState({ width: 0, height: 0 });

  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;
    // Content coordinates: the SVG scrolls with the nodes, so add the scroll offsets. A root drawn
    // under a CSS scale (a zoomed canvas) is measured at its own scale, read from the DOM, so a
    // measure during a zoom transition is still right.
    const measure = () => {
      const origin = el.getBoundingClientRect();
      const scale = el.offsetWidth > 0 && origin.width > 0 ? origin.width / el.offsetWidth : 1;
      const at = (client: number, start: number, scroll: number) =>
        (client - start) / scale + scroll;
      const next: Record<string, NodeBox> = {};
      el.querySelectorAll<HTMLElement>("[data-node-id]").forEach((node) => {
        const r = node.getBoundingClientRect();
        const top = at(r.top, origin.top, el.scrollTop);
        const bottom = at(r.bottom, origin.top, el.scrollTop);
        next[node.dataset.nodeId ?? ""] = {
          left: at(r.left, origin.left, el.scrollLeft),
          right: at(r.right, origin.left, el.scrollLeft),
          top,
          bottom,
          mid: (top + bottom) / 2,
        };
      });
      setBoxes(next);
      setSize({ width: el.scrollWidth, height: el.scrollHeight });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    el.querySelectorAll("[data-node-id]").forEach((node) => {
      observer.observe(node);
    });
    return () => {
      observer.disconnect();
    };
  }, [root, shape]);

  return { boxes, size };
}

/** A left-to-right S-curve from `a`'s right edge to `b`'s left edge (0,0 while unmeasured). */
export function curvePath(a: NodeBox | undefined, b: NodeBox | undefined): string {
  const x1 = a?.right ?? 0;
  const y1 = a?.mid ?? 0;
  const x2 = b?.left ?? 0;
  const y2 = b?.mid ?? 0;
  const mx = (x1 + x2) / 2;
  return `M ${String(x1)} ${String(y1)} C ${String(mx)} ${String(y1)}, ${String(mx)} ${String(y2)}, ${String(x2)} ${String(y2)}`;
}
