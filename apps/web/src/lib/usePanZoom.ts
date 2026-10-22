import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";

import { zoomAround, type View } from "./canvasView";

/* Pan and zoom of a canvas: the view is `translate(x, y) scale(k)` of a world inside `viewport`.
 * Dragging the background pans; the wheel pans (`"pan"`) or leaves the page its scroll (`"page"`,
 * where only a sideways or Shift wheel pans); Ctrl/⌘ + wheel or a pinch zooms at the pointer.
 * Only calls from buttons and keys animate (`animated`), never a drag or the wheel. */

export type WheelMode = "pan" | "page";

/** A press that moves less than this is a click, not a drag. */
const DRAG_PX = 4;

/** Where a press starts a pan: not on a control, a node or a link. */
const NO_PAN = "button, a, input, select, textarea, summary, [data-no-pan]";

/** Keep a drag's pointer on the element, where the platform supports it (not jsdom). */
export function capture(el: Element, pointerId: number): void {
  try {
    el.setPointerCapture(pointerId);
  } catch {
    // A pointer that is gone, or no pointer capture: the drag still works inside the element.
  }
}

export function usePanZoom(
  viewport: RefObject<HTMLElement | null>,
  { wheel, min = 0.25, max = 2 }: { wheel: WheelMode; min?: number; max?: number },
) {
  const [view, setViewState] = useState<View>({ x: 0, y: 0, k: 1 });
  const [animated, setAnimated] = useState(false);
  const [dragging, setDragging] = useState(false);
  // The view as last set, for handlers that run between renders (the wheel, a drag).
  const current = useRef(view);

  const setView = useCallback((next: View, animate = false) => {
    current.current = next;
    setAnimated(animate);
    setViewState(next);
  }, []);

  const zoomBy = (factor: number, point?: { x: number; y: number }) => {
    const el = viewport.current;
    const centre = { x: (el?.clientWidth ?? 0) / 2, y: (el?.clientHeight ?? 0) / 2 };
    setView(zoomAround(current.current, factor, point ?? centre, min, max), true);
  };

  const zoomTo = (k: number, point?: { x: number; y: number }) => {
    zoomBy(k / current.current.k, point);
  };

  // The wheel needs a non-passive listener to keep the page from scrolling or zooming.
  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        const r = el.getBoundingClientRect();
        const factor = Math.exp(-event.deltaY * 0.01);
        setView(
          zoomAround(
            current.current,
            factor,
            { x: event.clientX - r.left, y: event.clientY - r.top },
            min,
            max,
          ),
        );
        return;
      }
      let dx = event.deltaX;
      let dy = event.deltaY;
      if (wheel === "page") {
        if (event.shiftKey) {
          dx = dx || dy;
          dy = 0;
        } else if (Math.abs(dx) > Math.abs(dy)) {
          dy = 0;
        } else {
          return;
        }
      }
      event.preventDefault();
      const v = current.current;
      setView({ ...v, x: v.x - dx, y: v.y - dy });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", onWheel);
    };
  }, [viewport, wheel, min, max, setView]);

  const press = useRef<{ id: number; x: number; y: number; view: View; moved: boolean } | null>(
    null,
  );

  const onPointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    if (event.target instanceof Element && event.target.closest(NO_PAN)) return;
    press.current = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      view: current.current,
      moved: false,
    };
  }, []);

  const onPointerMove = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      const p = press.current;
      if (p?.id !== event.pointerId) return;
      const dx = event.clientX - p.x;
      const dy = event.clientY - p.y;
      if (!p.moved) {
        if (Math.hypot(dx, dy) < DRAG_PX) return;
        p.moved = true;
        setDragging(true);
        capture(event.currentTarget, event.pointerId);
      }
      setView({ ...p.view, x: p.view.x + dx, y: p.view.y + dy });
    },
    [setView],
  );

  const onPointerEnd = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (press.current?.id !== event.pointerId) return;
    press.current = null;
    setDragging(false);
  }, []);

  return {
    view,
    animated,
    dragging,
    setView,
    zoomBy,
    zoomTo,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: onPointerEnd,
      onPointerCancel: onPointerEnd,
    },
  };
}
