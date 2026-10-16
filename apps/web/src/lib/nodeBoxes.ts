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
    // Content coordinates: the SVG scrolls with the nodes, so add the scroll offsets.
    const measure = () => {
      const origin = el.getBoundingClientRect();
      const dx = el.scrollLeft - origin.left;
      const dy = el.scrollTop - origin.top;
      const next: Record<string, NodeBox> = {};
      el.querySelectorAll<HTMLElement>("[data-node-id]").forEach((node) => {
        const r = node.getBoundingClientRect();
        next[node.dataset.nodeId ?? ""] = {
          left: r.left + dx,
          right: r.right + dx,
          top: r.top + dy,
          bottom: r.bottom + dy,
          mid: r.top + dy + r.height / 2,
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
