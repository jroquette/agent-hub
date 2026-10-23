import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";
import { useSearchParams } from "react-router";

import {
  ArrowMarkers,
  Button,
  CANVAS_MAX_ZOOM as MAX_ZOOM,
  CANVAS_MIN_ZOOM as MIN_ZOOM,
  CANVAS_ZOOM_STEP as ZOOM_STEP,
  CanvasControls,
  CanvasGrid,
  CanvasMinimap,
  DataTable,
  Icon,
  IconButton,
  SegmentedControl,
  useViewportSize,
} from "../../components";
import type { IconName } from "../../components";
import { assignLanes, centreOn, fitView } from "../../lib/canvasView";
import { curvePath, useNodeBoxes } from "../../lib/nodeBoxes";
import { usePanZoom, type WheelMode } from "../../lib/usePanZoom";
import { goSequencePending, typingIn } from "../../shell/goSequence";
import {
  canvasModel,
  chainOf,
  columnWidth,
  downPath,
  drawnColumns,
  edgeKey,
  neighbours,
  runOrder,
  visibleEdges,
  wrapPath,
  wrapRows,
  WORLD_PAD,
  type CanvasModel,
  type CanvasStep,
  type Doc,
} from "./graphModel";
import { STEP_KINDS, stepKind } from "./steps";

/* The workflow canvas (plan 6.3/6.4): the server's layers as columns, left to right, on a pan and
 * zoom surface. Steps are cards with their kind, a rounds group is a frame holding its own steps,
 * edges are curves with arrowheads and the chosen step lights its whole chain. One Tab stop: the
 * arrow keys follow the edges. A list view stays as the text alternative, and a side panel
 * (About, or the chosen step) docks inside the card. */

export interface GraphNode {
  id: string;
  type: string;
  depends_on: string[];
  description?: string | null | undefined;
}

const TYPE_ICON: Readonly<Record<string, IconName>> = {
  agent: "message-square",
  shell: "terminal",
  script: "file-text",
  loop: "rotate-ccw",
  loop_group: "refresh-cw",
  approval: "stamp",
  wait: "hourglass",
  halt: "octagon-x",
  include: "layers",
};

export function typeIcon(type: string): IconName {
  return TYPE_ICON[type] ?? "box";
}

/** One edge per depends_on whose source is drawn, as `source→target`. */
export function edgesOf(layers: readonly (readonly GraphNode[])[]): [string, string][] {
  const ids = new Set(layers.flat().map((node) => node.id));
  return layers
    .flat()
    .flatMap((node) =>
      node.depends_on.filter((dep) => ids.has(dep)).map((dep): [string, string] => [dep, node.id]),
    );
}

/** The DOM id of a node's button, to give focus back when its panel closes. */
export function nodeDomId(id: string): string {
  return `wf-node-${id}`;
}

/** The plain kind label of a step: "AI agent", "Command", "Rounds". */
export function kindLabelOf(type: string): string {
  if (type === "loop_group") return "Rounds";
  const one = STEP_KINDS[stepKind(type)].one;
  return `${(one[0] ?? "").toUpperCase()}${one.slice(1)}`;
}

/** Below this zoom the cards show only their kind and title. */
const FAR = 0.6;
/** Top to bottom, the first view fits the whole graph only at this zoom or more. */
const READABLE = 0.85;
/** How far a skip edge's first lane runs from the cards it passes, and the step between lanes. */
const LANE_OFFSET = 24;
const LANE_STEP = 12;

export interface WorkflowGraphProps<N extends GraphNode> {
  layers: N[][];
  /** The document as written: badges, rounds groups and their own steps come from it. */
  document?: unknown;
  /** The graph's accessible name (default "Workflow graph"). */
  label?: string | undefined;
  selected: string | null;
  onSelect: (id: string) => void;
  /** Esc on the canvas or the panel: close the chosen step. */
  onClose?: (() => void) | undefined;
  /** A line under the card (a run's state); also a column of the list view. */
  detail?: ((id: string) => ReactNode) | undefined;
  /** The step's state for styling (`data-state`), by id (a group's own steps too). */
  state?: ((id: string) => string | undefined) | undefined;
  /** The list view's last column title, when `detail` is given. */
  detailLabel?: string | undefined;
  /** The details panel docked at the right of the canvas (About, or the chosen step). */
  panel?: ReactNode;
  /** The wheel pans the canvas (`"pan"`, a canvas that fills the page) or scrolls the page. */
  wheel?: WheelMode | undefined;
  /** Offer a Graph | List switch with the list as the text alternative (default `"list"`). */
  textAlternative?: "list" | "none" | undefined;
  /** The step the first view centres on when none is chosen (a run's step that needs you). */
  focusFirst?: string | null | undefined;
  /** Extra content at the top right of the canvas (a legend). */
  overlay?: ReactNode;
  /** Classes of the canvas card (its height). */
  className?: string | undefined;
}

function badgesOf(step: CanvasStep): { icon: IconName; text: string; mono?: boolean }[] {
  const doc = step.doc;
  if (!doc) return [];
  const badges: { icon: IconName; text: string; mono?: boolean }[] = [];
  if (typeof doc.when === "string" && doc.when.trim())
    badges.push({ icon: "split", text: "Only when" });
  if (typeof doc.include === "string")
    badges.push({ icon: "layers", text: doc.include, mono: true });
  if (step.type === "loop" && typeof doc.max_iterations === "number") {
    badges.push({ icon: "rotate-ccw", text: `Up to ${String(doc.max_iterations)} turns` });
  }
  if (step.group !== null && doc.context === "fresh") {
    badges.push({ icon: "rotate-ccw", text: "Starts afresh" });
  }
  return badges.slice(0, 2);
}

/** The rule of a rounds group in one line: "Up to 3 rounds · Stops when …". */
function roundsLine(doc: Doc | undefined): { max: string; rule: ReactNode } {
  const max = typeof doc?.max_iterations === "number" ? String(doc.max_iterations) : "?";
  const until = typeof doc?.until_when === "string" ? doc.until_when : null;
  const bash = Array.isArray(doc?.until_bash) ? doc.until_bash.map(String).join(" ") : null;
  return {
    max,
    rule: until ? (
      <>
        Stops when <code>{until}</code>
      </>
    ) : bash ? (
      <>
        Stops when <code>{bash}</code> passes
      </>
    ) : (
      <>Runs all {max} rounds</>
    ),
  };
}

interface CardProps {
  step: CanvasStep;
  selected: boolean;
  onChain: boolean;
  tabStop: boolean;
  state: string | undefined;
  detail: ReactNode;
  onSelect: (id: string) => void;
  onFocus: (id: string) => void;
  onHover: (id: string | null) => void;
}

function NodeCard({
  step,
  selected,
  onChain,
  tabStop,
  state,
  detail,
  onSelect,
  onFocus,
  onHover,
}: CardProps) {
  const kind = stepKind(step.type);
  const titled = step.description !== null && step.description.trim() !== "";
  const badges = badgesOf(step);
  const describedId = useId();
  const when = typeof step.doc?.when === "string" ? step.doc.when : null;
  const waits = step.depends_on.map((id) => (step.group ? id.slice(step.group.length + 2) : id));
  const described = [
    waits.length > 0 ? `Waits for ${waits.join(", ")}.` : "",
    when ? `Only when ${when}.` : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <li className="wf-col-item">
      {described && (
        <span id={describedId} hidden>
          {described}
        </span>
      )}
      <button
        aria-describedby={described ? describedId : undefined}
        type="button"
        id={nodeDomId(step.id)}
        className="wf-node"
        data-node-id={step.id}
        data-kind={kind}
        data-state={state}
        data-chain={onChain ? "" : undefined}
        aria-pressed={selected}
        tabIndex={tabStop ? 0 : -1}
        onClick={() => {
          onSelect(step.id);
        }}
        onFocus={() => {
          onFocus(step.id);
        }}
        onMouseEnter={() => {
          onHover(step.id);
        }}
        onMouseLeave={() => {
          onHover(null);
        }}
      >
        <span className="wf-kind-tile" data-kind={kind} aria-hidden="true">
          <Icon name={STEP_KINDS[kind].icon} size="sm" />
        </span>
        <span className="wf-node-text">
          <span className={titled ? "wf-node-title" : "wf-node-title ah-mono"}>
            {titled ? step.description : step.bare}
          </span>
          <span className="wf-node-caption">
            {titled && (
              <>
                <span className="ah-mono wf-node-id" title={step.bare}>
                  {step.bare}
                </span>
                <span aria-hidden="true"> · </span>
              </>
            )}
            <span>{kindLabelOf(step.type)}</span>
          </span>
          {badges.length > 0 && (
            <span className="wf-node-badges">
              {badges.map((badge) => (
                <span key={badge.text} className={badge.mono ? "wf-badge ah-mono" : "wf-badge"}>
                  <Icon name={badge.icon} size="sm" />
                  {badge.text}
                </span>
              ))}
            </span>
          )}
          {detail !== undefined && detail !== null && (
            <span className="wf-node-state">{detail}</span>
          )}
        </span>
      </button>
    </li>
  );
}

interface GroupProps extends Omit<CardProps, "detail"> {
  body: CanvasStep[][];
  open: boolean;
  onToggle: (id: string) => void;
  renderStep: (step: CanvasStep) => ReactNode;
  detail: ReactNode;
}

function GroupFrame({
  step,
  body,
  open,
  onToggle,
  renderStep,
  selected,
  onChain,
  tabStop,
  state,
  detail,
  onSelect,
  onFocus,
  onHover,
}: GroupProps) {
  const { max, rule } = roundsLine(step.doc);
  const titled = step.description !== null && step.description.trim() !== "";
  const inside = body.flat().length;
  return (
    <li className="wf-col-item">
      <div
        className="wf-group"
        data-node-id={step.id}
        data-open={open ? "" : undefined}
        data-state={state}
        data-chain={onChain ? "" : undefined}
        role="group"
        aria-label={`${step.bare} rounds: up to ${max}`}
      >
        <div className="wf-group-head">
          <button
            type="button"
            id={nodeDomId(step.id)}
            className="wf-group-title"
            aria-pressed={selected}
            tabIndex={tabStop ? 0 : -1}
            onClick={() => {
              onSelect(step.id);
            }}
            onFocus={() => {
              onFocus(step.id);
            }}
            onMouseEnter={() => {
              onHover(step.id);
            }}
            onMouseLeave={() => {
              onHover(null);
            }}
          >
            <span className="wf-kind-tile" data-kind="repeat" aria-hidden="true">
              <Icon name="refresh-cw" size="sm" />
            </span>
            <span className="wf-node-text">
              <span className={titled ? "wf-node-title" : "wf-node-title ah-mono"}>
                {titled ? step.description : step.bare}
              </span>
              <span className="wf-node-caption">
                {titled && (
                  <>
                    <span className="ah-mono wf-node-id">{step.bare}</span>
                    <span aria-hidden="true"> · </span>
                  </>
                )}
                Up to {max} rounds
                {open ? (
                  <>
                    <span aria-hidden="true"> · </span>
                    <span className="wf-group-rule">{rule}</span>
                  </>
                ) : (
                  ` · ${String(inside)} ${inside === 1 ? "step" : "steps"} inside`
                )}
              </span>
              {detail !== undefined && detail !== null && (
                <span className="wf-node-state">{detail}</span>
              )}
            </span>
          </button>
          <IconButton
            size="sm"
            icon={open ? "chevron-up" : "chevron-down"}
            label={open ? "Collapse rounds" : "Expand rounds"}
            aria-expanded={open}
            tabIndex={-1}
            onClick={() => {
              onToggle(step.id);
            }}
          />
        </div>
        {open && (
          <div className="wf-group-body">
            {body.map((layer, i) => (
              <ol key={i} className="wf-col" aria-label={`Layer ${String(i + 1)} of ${step.bare}`}>
                {layer.map(renderStep)}
              </ol>
            ))}
          </div>
        )}
      </div>
    </li>
  );
}

/** The rounds groups drawn open: all but the ones closed, and always the one holding `keep`. */
function useOpenGroups(model: CanvasModel, keep: readonly (string | null | undefined)[]) {
  const [closed, setClosed] = useState<ReadonlySet<string>>(() => new Set());
  const open = useMemo(() => {
    const forced = new Set(
      keep.map((id) => (id ? model.steps.get(id)?.group : null)).filter((g) => g != null),
    );
    return new Set([...model.groups.keys()].filter((id) => !closed.has(id) || forced.has(id)));
  }, [model, closed, keep]);
  const toggle = useCallback((id: string) => {
    setClosed((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const closeAll = useCallback(() => {
    setClosed(new Set(model.groups.keys()));
  }, [model]);
  return { open, closeAll, toggle };
}

function GraphCanvas<N extends GraphNode>({
  layers,
  document,
  label = "Workflow graph",
  selected,
  onSelect,
  onClose,
  detail,
  state,
  panel,
  wheel = "pan",
  focusFirst,
  overlay,
  className,
}: WorkflowGraphProps<N>) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const hintId = useId();
  const arrowId = `wf-arrow-${useId().replace(/:/g, "")}`;
  const model = useMemo(() => canvasModel(layers, document), [layers, document]);
  const keepOpen = useMemo(() => [selected, focusFirst], [selected, focusFirst]);
  const { open, closeAll, toggle } = useOpenGroups(model, keepOpen);
  const edges = useMemo(() => visibleEdges(layers, model, open), [layers, model, open]);
  const order = useMemo(() => runOrder(layers, model, open), [layers, model, open]);
  const columns = useMemo(() => drawnColumns(layers, model, open), [layers, model, open]);
  const pz = usePanZoom(viewportRef, { wheel, min: MIN_ZOOM, max: MAX_ZOOM });
  const { view } = pz;
  const far = view.k < FAR;

  const viewport = useViewportSize(viewportRef);

  // Topological order, top to bottom: each layer is a row and the arrows point down. The other
  // flow lays the layers out as columns, left to right, wrapped into rows that fit the canvas.
  const [flow, setFlow] = useState<"down" | "across">("down");
  const rows = useMemo(
    () =>
      flow === "down"
        ? layers.map((_, i) => [i])
        : wrapRows(
            layers.map((layer) => columnWidth(layer, model, open)),
            viewport.width,
          ),
    [flow, layers, model, open, viewport.width],
  );
  const rowOf = useMemo(() => {
    const map = new Map<string, number>();
    rows.forEach((row, r) => {
      for (const i of row) {
        for (const node of layers[i] ?? []) {
          map.set(node.id, r);
          for (const inner of model.groups.get(node.id)?.flat() ?? []) map.set(inner.id, r);
        }
      }
    });
    return map;
  }, [rows, layers, model]);
  // Re-measure when the shape changes, not on every render (a live run re-renders each second).
  const shape = `${edges.map(edgeKey).join(" ")}|${order.join(",")}|${far ? "far" : "near"}|${rows.map((r) => r.join(".")).join("/")}`;
  const { boxes, size, measured } = useNodeBoxes(worldRef, shape);

  // The first view, once the world and the viewport have a size.
  const placed = useRef(false);
  const triedClosing = useRef(false);
  useLayoutEffect(() => {
    if (placed.current) return;
    if (size.width === 0 || viewport.width === 0) return;
    // Wait for the measure of the graph as now laid out: after closing the rounds, the boxes and
    // the size are still the open graph's until the next measure.
    if (measured !== shape) return;
    const target = selected ?? focusFirst ?? null;
    const box = target ? boxes[target] : undefined;
    if (box) {
      // A rounds frame can be wider than the canvas: centre on its head, from its left edge.
      const head = model.groups.has(target ?? "")
        ? {
            left: box.left,
            right: Math.min(box.right, box.left + viewport.width * 0.8),
            top: box.top,
            bottom: Math.min(box.bottom, box.top + 120),
          }
        : box;
      pz.setView(centreOn(head, viewport, 1));
      placed.current = true;
      return;
    }
    const fit = fitView(size, viewport, { max: 1, min: MIN_ZOOM });
    // Top to bottom, the whole graph only when it stays readable; else 100% from the top.
    if (fit.k >= (flow === "down" ? READABLE : FAR)) {
      pz.setView(fit);
      placed.current = true;
      return;
    }
    if (!triedClosing.current && open.size > 0) {
      // Too big to read whole: close the rounds and look again.
      triedClosing.current = true;
      closeAll();
      return;
    }
    if (flow === "down") {
      const x = size.width < viewport.width ? (viewport.width - size.width) / 2 : 0;
      pz.setView({ k: 1, x, y: 0 });
      placed.current = true;
      return;
    }
    if (rows.length > 1) {
      // Wrapped rows: the full width, from the top.
      const k = Math.max(MIN_ZOOM, Math.min(1, viewport.width / size.width));
      pz.setView({ k, x: (viewport.width - size.width * k) / 2, y: 0 });
      placed.current = true;
      return;
    }
    pz.setView({ k: 0.8, x: 0, y: Math.max(0, (viewport.height - size.height * 0.8) / 2) });
    placed.current = true;
  }, [
    boxes,
    size,
    measured,
    shape,
    flow,
    viewport,
    selected,
    focusFirst,
    open,
    closeAll,
    pz,
    rows.length,
    model.groups,
  ]);

  // The chain of the chosen step, or the direct edges of the one under the pointer or focus.
  const [hover, setHover] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const chain = useMemo(() => {
    if (selected && model.steps.has(selected)) return chainOf(edges, selected);
    return null;
  }, [edges, selected, model]);
  const near = !chain ? (hover ?? null) : null;

  const tabStop =
    focusId && order.includes(focusId)
      ? focusId
      : selected && order.includes(selected)
        ? selected
        : order[0];

  const fit = useCallback(() => {
    pz.setView(fitView(size, viewport, { max: 1, min: MIN_ZOOM }), true);
  }, [pz, size, viewport]);

  /** Keep a focused step on screen, with a margin. */
  const reveal = useCallback(
    (id: string) => {
      const box = boxes[id];
      if (!box || viewport.width === 0) return;
      const margin = 48;
      const { x, y, k } = pz.view;
      const left = box.left * k + x;
      const right = box.right * k + x;
      const top = box.top * k + y;
      const bottom = box.bottom * k + y;
      let nx = x;
      let ny = y;
      if (left < margin) nx += margin - left;
      else if (right > viewport.width - margin) nx -= right - (viewport.width - margin);
      if (top < margin) ny += margin - top;
      else if (bottom > viewport.height - margin) ny -= bottom - (viewport.height - margin);
      if (nx !== x || ny !== y) pz.setView({ k, x: nx, y: ny }, true);
    },
    [boxes, pz, viewport],
  );

  const moveTo = (id: string | undefined) => {
    if (!id) return;
    const el = window.document.getElementById(nodeDomId(id));
    el?.focus({ preventScroll: true });
    reveal(id);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    if (typingIn(event.target)) return;
    const target = event.target as HTMLElement;
    const inWorld = worldRef.current?.contains(target) ?? false;
    const inCanvas = viewportRef.current?.contains(target) ?? false;
    if (event.key === "Escape" && selected && onClose) {
      event.preventDefault();
      onClose();
      return;
    }
    if (!inCanvas) return;
    if (goSequencePending()) return;
    const at = target.closest<HTMLElement>("[data-node-id], .wf-group-title");
    const id = at?.classList.contains("wf-group-title")
      ? (at.closest<HTMLElement>("[data-node-id]")?.dataset.nodeId ?? null)
      : (at?.dataset.nodeId ?? null);
    switch (event.key) {
      case "+":
      case "=":
        event.preventDefault();
        pz.zoomBy(ZOOM_STEP);
        return;
      case "-":
        event.preventDefault();
        pz.zoomBy(1 / ZOOM_STEP);
        return;
      case "0":
        event.preventDefault();
        fit();
        return;
      case "1":
        event.preventDefault();
        pz.zoomTo(1);
        return;
    }
    if (!inWorld || !id) return;
    const step = model.steps.get(id);
    const { next, previous } = neighbours(edges, id);
    let to: string | undefined;
    switch (event.key) {
      case "ArrowRight": {
        const body = model.groups.get(id);
        if (body && !open.has(id)) {
          // A closed rounds frame opens first, as a tree item does.
          event.preventDefault();
          toggle(id);
          return;
        }
        to = body ? body[0]?.[0]?.id : next[0];
        if (!to && step?.group) to = neighbours(edges, step.group).next[0];
        break;
      }
      case "ArrowLeft": {
        const held = keepOpen.some((k) => k != null && model.steps.get(k)?.group === id);
        if (model.groups.has(id) && open.has(id) && !held) {
          // An open rounds frame closes first.
          event.preventDefault();
          toggle(id);
          return;
        }
        to = previous[0] ?? step?.group ?? undefined;
        break;
      }
      case "ArrowDown":
      case "ArrowUp": {
        const column = columns.find((col) => col.includes(id)) ?? [];
        const i = column.indexOf(id) + (event.key === "ArrowDown" ? 1 : -1);
        to = column[i];
        break;
      }
      case "j":
      case "k": {
        const i = order.indexOf(id) + (event.key === "j" ? 1 : -1);
        to = order[i];
        break;
      }
      default:
        return;
    }
    event.preventDefault();
    moveTo(to);
  };

  const renderStep = (step: CanvasStep): ReactNode => {
    const common = {
      step,
      selected: selected === step.id,
      onChain: chain?.nodes.has(step.id) ?? false,
      tabStop: tabStop === step.id,
      state: state?.(step.id),
      detail: detail?.(step.id),
      onSelect,
      onFocus: setFocusId,
      onHover: setHover,
    };
    const body = model.groups.get(step.id);
    if (body) {
      return (
        <GroupFrame
          key={step.id}
          {...common}
          body={body}
          open={open.has(step.id)}
          onToggle={toggle}
          renderStep={renderStep}
        />
      );
    }
    return <NodeCard key={step.id} {...common} />;
  };

  // Top to bottom, each edge that skips rows gets its own lane over the rows it spans, so no two
  // run on the same line; edges from one step share a trunk.
  const downLanes = useMemo(
    () =>
      assignLanes(
        edges.flatMap(([from, to]) => {
          const ra = rowOf.get(from);
          const rb = rowOf.get(to);
          if (ra === undefined || rb === undefined || rb <= ra + 1) return [];
          return [{ id: `${from}→${to}`, start: ra, end: rb, trunk: from }];
        }),
      ),
    [edges, rowOf],
  );
  const laneCount = downLanes.size === 0 ? 0 : Math.max(...downLanes.values()) + 1;
  // Across, the lane of each edge that crosses to a later row: its rank among those leaving the same row.
  const lanes = new Map<string, number>();
  {
    const perRow = new Map<number, number>();
    for (const [from, to] of edges) {
      const ra = rowOf.get(from);
      const rb = rowOf.get(to);
      if (ra === undefined || rb === undefined || rb <= ra) continue;
      const n = perRow.get(ra) ?? 0;
      lanes.set(`${from}→${to}`, (n % 5) - 2);
      perRow.set(ra, n + 1);
    }
  }
  /** A curve within a row; a routed line back to the start of a later row. */
  const edgePath = (from: string, to: string): string => {
    const a = boxes[from];
    const b = boxes[to];
    const ra = rowOf.get(from);
    const rb = rowOf.get(to);
    if (a && b && ra !== undefined && rb !== undefined && rb > ra) {
      const gap = (r: number) => {
        const above = boxes[`row:${String(r)}`];
        const below = boxes[`row:${String(r + 1)}`];
        return above && below ? (above.bottom + below.top) / 2 : a.bottom + 36;
      };
      // Parallel lines get their own lane, 5 px apart, so each can be followed.
      const lane = (lanes.get(`${from}→${to}`) ?? 0) * 5;
      if (flow === "down") {
        if (rb === ra + 1) return downPath(a, b);
        // Beside the rows it passes, not at the world's edge.
        const n = downLanes.get(`${from}→${to}`) ?? 0;
        let left = Math.min(a.left, b.left);
        for (let r = ra + 1; r < rb; r += 1) {
          const row = boxes[`row:${String(r)}`];
          if (row) left = Math.min(left, row.left);
        }
        return downPath(a, b, {
          gapBelow: gap(ra) - n * 6,
          gapAbove: gap(rb - 1) + n * 6,
          gutter: Math.max(4, left - LANE_OFFSET - n * LANE_STEP),
        });
      }
      if (rb === ra + 1) return wrapPath(a, b, gap(ra) + lane);
      return wrapPath(a, b, gap(ra) + lane, 10, {
        gapAbove: gap(rb - 1) - lane,
        gutter: WORLD_PAD / 2 - lane,
      });
    }
    return curvePath(a, b);
  };

  const empty = layers.length === 0 || layers.every((layer) => layer.length === 0);
  const overflow =
    size.width * view.k > viewport.width + 1 || size.height * view.k > viewport.height + 1;
  const worldStyle: CSSProperties & Record<"--k", string> = {
    transform: `translate(${String(view.x)}px, ${String(view.y)}px) scale(${String(view.k)})`,
    "--k": String(view.k),
  };

  return (
    // The keys of the canvas and its panel (arrows, zoom, Esc) bubble here from their buttons.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      data-canvas="workflow"
      className={className ? `ah-canvas ${className}` : "ah-canvas"}
      data-panel={panel ? "" : undefined}
      onKeyDown={onKeyDown}
    >
      <div
        ref={viewportRef}
        className="ah-canvas-viewport"
        data-dragging={pz.dragging ? "" : undefined}
        {...pz.handlers}
      >
        <CanvasGrid view={view} />
        {empty ? (
          <div className="ah-canvas-empty">
            <span className="ah-empty-icon">
              <Icon name="workflow" size="lg" />
            </span>
            <p className="ah-empty-title" style={{ margin: 0 }}>
              This workflow has no steps.
            </p>
            <p className="ah-small ah-muted" style={{ margin: 0 }}>
              Its file declares no nodes. Add them under <code className="ah-mono">nodes:</code> in
              the file, or ask Claude with Discuss.
            </p>
          </div>
        ) : (
          <div
            ref={worldRef}
            className="ah-canvas-world"
            role="group"
            aria-label={label}
            aria-describedby={hintId}
            data-zoom={far ? "far" : undefined}
            data-animate={pz.animated ? "" : undefined}
            data-chosen={chain ? "" : undefined}
            style={worldStyle}
          >
            <svg
              aria-hidden="true"
              data-edges=""
              className="wf-edges"
              // A 1 px box that draws outside itself: sized to the world, it would hold the world's
              // own measure at its last size.
              width={1}
              height={1}
            >
              <ArrowMarkers id={arrowId} tones={["plain", "hot"]} />
              {edges.map((edge) => {
                const key = edgeKey(edge);
                const [from, to] = edge;
                // The chosen step's own edges light up; the rest of its chain stays, the others fade.
                const focus = selected && chain ? selected : near;
                const hot = focus !== null && (from === focus || to === focus);
                const dim = chain !== null && !chain.edges.has(key);
                return (
                  <path
                    key={key}
                    data-edge={key}
                    data-hot={hot ? "" : undefined}
                    data-chain={chain && !hot && !dim ? "" : undefined}
                    data-dim={dim ? "" : undefined}
                    data-pending={
                      state && ["pending", "skipped"].includes(state(to) ?? "") ? "" : undefined
                    }
                    d={edgePath(from, to)}
                    markerEnd={`url(#${arrowId}-${hot ? "hot" : "plain"})`}
                  />
                );
              })}
            </svg>
            <div
              className="wf-rows"
              data-flow={flow}
              // Room beside the column for the lanes of the edges that skip rows.
              style={
                flow === "down"
                  ? {
                      paddingInline: LANE_OFFSET + LANE_STEP * laneCount,
                    }
                  : undefined
              }
            >
              {rows.map((row, r) => (
                <div key={r} className="wf-cols" data-node-id={`row:${String(r)}`} data-row="">
                  {row.map((i) => (
                    <ol key={i} className="wf-col" aria-label={`Layer ${String(i + 1)}`}>
                      {(layers[i] ?? []).map((node) => {
                        const step = model.steps.get(node.id);
                        return step ? renderStep(step) : null;
                      })}
                    </ol>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}
        <span id={hintId} className="ah-sr">
          Arrow keys follow the arrows, right opens and left closes a rounds frame, Enter opens a
          step, plus and minus zoom, 0 fits the graph.
        </span>
        {overlay && <div className="ah-canvas-overlay">{overlay}</div>}
        {!empty && (
          <CanvasControls
            view={view}
            onZoomBy={(f) => {
              pz.zoomBy(f);
            }}
            onZoomTo={(k) => {
              pz.zoomTo(k);
            }}
            onFit={fit}
          >
            <IconButton
              size="sm"
              icon={flow === "down" ? "corner-down-right" : "arrow-down"}
              label={
                flow === "down"
                  ? "Lay the layers out left to right"
                  : "Lay the layers out top to bottom"
              }
              aria-pressed={flow === "across"}
              onClick={() => {
                placed.current = false;
                setFlow((f) => (f === "down" ? "across" : "down"));
              }}
            />
          </CanvasControls>
        )}
        {!empty && overflow && size.width > 0 && (
          <CanvasMinimap
            boxes={boxes}
            size={size}
            view={view}
            viewport={viewport}
            look={(id) => {
              if (id.startsWith("row:")) return null;
              const step = model.steps.get(id);
              return {
                frame: model.groups.has(id) && open.has(id),
                kind: step ? stepKind(step.type) : "command",
                state: state?.(id),
              };
            }}
            onCentre={(x, y) => {
              pz.setView({
                k: view.k,
                x: viewport.width / 2 - x * view.k,
                y: viewport.height / 2 - y * view.k,
              });
            }}
          />
        )}
      </div>
      {panel && <div className="ah-canvas-panel">{panel}</div>}
    </div>
  );
}

function GraphList<N extends GraphNode>({
  layers,
  onSelect,
  detail,
  detailLabel,
}: WorkflowGraphProps<N>) {
  const rows = layers.flatMap((layer, i) => layer.map((node) => ({ node, layer: i + 1 })));
  return (
    <DataTable
      caption="Nodes in run order"
      density="compact"
      rows={rows}
      rowKey={(row) => row.node.id}
      onRowClick={(row) => {
        onSelect(row.node.id);
      }}
      columns={[
        { id: "layer", label: "Layer", width: 64, render: (row) => row.layer },
        {
          id: "node",
          label: "Node",
          render: (row) => <span className="ah-mono">{row.node.id}</span>,
        },
        { id: "type", label: "Type", render: (row) => row.node.type },
        {
          id: "after",
          label: "Waits for",
          render: (row) => row.node.depends_on.join(", ") || "—",
        },
        ...(detail
          ? [
              {
                id: "detail",
                label: detailLabel ?? "State",
                render: (row: { node: N }) => detail(row.node.id),
              },
            ]
          : []),
      ]}
    />
  );
}

/** The canvas, with a Graph | List switch when the list is its text alternative. */
export function WorkflowGraph<N extends GraphNode>(props: WorkflowGraphProps<N>) {
  const [view, setView] = useState<"graph" | "list">("graph");
  if (props.textAlternative === "none") return <GraphCanvas {...props} />;
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <div className="ah-row" style={{ gap: 8 }}>
        <span className="ah-small ah-subtle">
          Arrows point to the step that waits · choose a step for its details
        </span>
        <span className="ah-grow" />
        <SegmentedControl
          label="Graph view"
          value={view}
          onChange={(id) => {
            setView(id === "list" ? "list" : "graph");
          }}
          options={[
            { id: "graph", label: "Graph" },
            { id: "list", label: "List" },
          ]}
        />
      </div>
      {view === "graph" ? (
        <GraphCanvas {...props} />
      ) : (
        <div className="wf-list-with-panel" data-panel={props.panel ? "" : undefined}>
          <GraphList {...props} />
          {props.panel}
        </div>
      )}
    </div>
  );
}

/**
 * The selected node (`?node=`): `open` remembers the element that opened the panel (a node button
 * or a list row) and `close` gives focus back to it, else to the node's button.
 */
export function useNodeParam(): {
  nodeId: string | null;
  openedByUser: boolean;
  open: (id: string) => void;
  close: () => void;
} {
  const [params, setParams] = useSearchParams();
  const opener = useRef<HTMLElement | null>(null);
  const [openedByUser, setOpenedByUser] = useState(false);
  const nodeId = params.get("node");
  const setNode = useCallback(
    (id: string | null) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (id === null) next.delete("node");
          else next.set("node", id);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  const open = (id: string) => {
    const active = document.activeElement;
    // Safari leaves focus on the body after a mouse click: fall back to the node then. A step
    // chosen from the panel (a "Waits for" chip) gives focus back to its own node.
    const inPanel = active instanceof HTMLElement && active.closest(".ah-canvas-panel") !== null;
    opener.current =
      active instanceof HTMLElement && active !== document.body && !inPanel ? active : null;
    setOpenedByUser(true);
    setNode(id);
  };
  const close = () => {
    const back = opener.current?.isConnected
      ? opener.current
      : nodeId
        ? document.getElementById(nodeDomId(nodeId))
        : null;
    opener.current = null;
    setOpenedByUser(false);
    setNode(null);
    back?.focus({ preventScroll: true });
  };
  return { nodeId, openedByUser, open, close };
}

/** The selected node's panel; Close gives focus back to what opened it. */
export function NodePanel({
  id,
  onClose,
  focusOnOpen,
  heading,
  children,
}: {
  id: string;
  onClose: () => void;
  /** Move focus into the panel: on a user's choice, not on a `?node=` link at load. */
  focusOnOpen: boolean;
  /** The head of the panel (default: the id in mono). */
  heading?: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focusOnOpen) ref.current?.focus({ preventScroll: true });
  }, [id, focusOnOpen]);
  return (
    <aside className="wf-inspector" aria-label={`Node ${id}`}>
      <div className="wf-inspector-head">
        <h2 ref={ref} tabIndex={-1} className="ah-h3 wf-inspector-title">
          {heading ?? <span className="ah-mono">{id}</span>}
        </h2>
        <Button size="sm" variant="ghost" icon="x" onClick={onClose}>
          Close
        </Button>
      </div>
      {children}
    </aside>
  );
}
