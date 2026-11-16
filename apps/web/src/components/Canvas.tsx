import "./Canvas.css";

import { useId, useLayoutEffect, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode, RefObject } from "react";

import type { Size, View } from "../lib/canvasView";
import type { NodeBox } from "../lib/nodeBoxes";
import { capture } from "../lib/usePanZoom";
import { Button, IconButton } from "./core";

/* The parts of a pan and zoom canvas that every graph shares: the viewport's size, the dot grid
 * that moves with the world, the zoom toolbar, the minimap and the arrowheads. Each graph keeps
 * its own world (cards, columns, edges) and its own keys. */

export const CANVAS_MIN_ZOOM = 0.25;
export const CANVAS_MAX_ZOOM = 2;
export const CANVAS_ZOOM_STEP = 1.2;

/** The viewport's inner size, kept up to date as it resizes. */
export function useViewportSize(viewport: RefObject<HTMLElement | null>): Size {
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const read = () => {
      setSize({ width: el.clientWidth, height: el.clientHeight });
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, [viewport]);
  return size;
}

/** The dot grid under the world: 1 px dots every 16 px, panned and scaled with the view. */
export function CanvasGrid({ view }: { view: View }) {
  const id = `ah-canvas-grid-${useId().replace(/:/g, "")}`;
  return (
    <svg className="ah-canvas-grid" aria-hidden="true">
      <defs>
        <pattern
          id={id}
          width={16}
          height={16}
          patternUnits="userSpaceOnUse"
          patternTransform={`translate(${String(view.x)} ${String(view.y)}) scale(${String(view.k)})`}
        >
          <circle cx={1} cy={1} r={1} />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
    </svg>
  );
}

/** The zoom toolbar: out, the percent (resets to 100%), in, fit; then the graph's own buttons. */
export function CanvasControls({
  view,
  label = "Graph view",
  onZoomBy,
  onZoomTo,
  onFit,
  children,
}: {
  view: View;
  label?: string;
  onZoomBy: (factor: number) => void;
  onZoomTo: (k: number) => void;
  onFit: () => void;
  children?: ReactNode;
}) {
  return (
    <div className="ah-canvas-controls" role="toolbar" aria-label={label} data-no-pan="">
      <IconButton
        size="sm"
        icon="minus"
        label="Zoom out (−)"
        disabled={view.k <= CANVAS_MIN_ZOOM + 1e-6}
        onClick={() => {
          onZoomBy(1 / CANVAS_ZOOM_STEP);
        }}
      />
      <Button
        size="sm"
        variant="ghost"
        aria-label="Reset zoom to 100%"
        className="ah-canvas-zoom"
        onClick={() => {
          onZoomTo(1);
        }}
      >
        {Math.round(view.k * 100)}%
      </Button>
      <IconButton
        size="sm"
        icon="plus"
        label="Zoom in (+)"
        disabled={view.k >= CANVAS_MAX_ZOOM - 1e-6}
        onClick={() => {
          onZoomBy(CANVAS_ZOOM_STEP);
        }}
      />
      <span className="ah-canvas-sep" aria-hidden="true" />
      <IconButton size="sm" icon="maximize-2" label="Fit to view (0)" onClick={onFit} />
      {children}
    </div>
  );
}

/** How a box shows on the minimap: a frame (outline) or a node in a tone; null leaves it out. */
export type MiniLook = {
  frame: boolean;
  kind?: string | undefined;
  state?: string | undefined;
} | null;

/**
 * The minimap: each box in its tone and the visible area, sized to the world's shape within
 * 176 x 112. A pointer aid only (`aria-hidden`): click or drag to move the view there.
 */
export function CanvasMinimap({
  boxes,
  size,
  view,
  viewport,
  look,
  onCentre,
}: {
  boxes: Readonly<Record<string, NodeBox>>;
  size: Size;
  view: View;
  viewport: Size;
  look: (id: string) => MiniLook;
  onCentre: (x: number, y: number) => void;
}) {
  const m = Math.min(176 / size.width, 112 / size.height);
  const W = Math.max(48, Math.round(size.width * m));
  const H = Math.max(32, Math.round(size.height * m));
  const ox = (W - size.width * m) / 2;
  const oy = (H - size.height * m) / 2;
  const at = (event: ReactPointerEvent<SVGSVGElement>) => {
    const r = event.currentTarget.getBoundingClientRect();
    onCentre((event.clientX - r.left - ox) / m, (event.clientY - r.top - oy) / m);
  };
  return (
    <svg
      className="ah-canvas-minimap"
      aria-hidden="true"
      width={W}
      height={H}
      data-no-pan=""
      onPointerDown={(event) => {
        capture(event.currentTarget, event.pointerId);
        at(event);
      }}
      onPointerMove={(event) => {
        if (event.buttons === 1) at(event);
      }}
    >
      {Object.entries(boxes).map(([id, box]) => {
        const info = look(id);
        if (!info) return null;
        return (
          <rect
            key={id}
            x={ox + box.left * m}
            y={oy + box.top * m}
            width={Math.max(2, (box.right - box.left) * m)}
            height={Math.max(2, (box.bottom - box.top) * m)}
            rx={1}
            className={info.frame ? "ah-canvas-mini-group" : "ah-canvas-mini-node"}
            data-kind={info.kind}
            data-state={info.state}
          />
        );
      })}
      <rect
        className="ah-canvas-mini-view"
        x={ox + (-view.x / view.k) * m}
        y={oy + (-view.y / view.k) * m}
        width={(viewport.width / view.k) * m}
        height={(viewport.height / view.k) * m}
      />
    </svg>
  );
}

/** Arrowhead markers, one per tone, as `<id>-<tone>`; the tone's fill comes from CSS. */
export function ArrowMarkers({ id, tones }: { id: string; tones: readonly string[] }) {
  return (
    <defs>
      {tones.map((tone) => (
        <marker
          key={tone}
          id={`${id}-${tone}`}
          viewBox="0 0 8 8"
          refX="7"
          refY="4"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
          className="ah-canvas-arrow"
          data-tone={tone}
        >
          <path d="M 0 0 L 8 4 L 0 8 z" />
        </marker>
      ))}
    </defs>
  );
}
