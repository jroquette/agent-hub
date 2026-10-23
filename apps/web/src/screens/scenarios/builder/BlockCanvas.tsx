import {
  useCallback,
  useEffect,
  useRef,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import { CanvasControls, Icon, useViewportSize } from "../../../components";
import { fitView } from "../../../lib/canvasView";
import { usePanZoom } from "../../../lib/usePanZoom";
import type { ScenarioAction, ScenarioPlanRow } from "../queries";
import { CardFacts, CardHead, RunsLine, TokenText, cardTitle } from "./CardParts";
import { kindLook } from "./FlowCanvas";
import { conditionWords, type BuilderNode } from "./model";
import { itemId, type Item, type Slot } from "./program";
import type { BuilderProblem } from "./useScenarioDraft";

/* The block canvas: the scenario as step cards joined by arrows on a free canvas. A card under
 * another runs after it; Repeat, If / else and At the same time hold cards in lanes. A card is
 * read here and edited in the side form. Dragging a
 * block takes the blocks under it along and drops them into any gap or mouth; dropped on the empty
 * canvas they become a loose stack (not part of the flow until snapped back). The canvas pans and
 * zooms; where the stacks sit is the only thing kept outside the file (in this browser). */

export interface Stack {
  id: string;
  x: number;
  y: number;
  items: Item[];
  /** Blocks of the file the blocks cannot place: saved as written. */
  kept?: boolean;
}

export type DropTarget =
  { stack: string; slot: Slot; index: number } | { free: { x: number; y: number } };

export interface DragState {
  items: Item[];
  /** Where the pointer grabbed the first block, from its top left. */
  grab: { x: number; y: number };
  client: { x: number; y: number };
  target: DropTarget | null;
}

export interface BlockCanvasProps {
  main: Stack;
  loose: readonly Stack[];
  selected: string | null;
  actionOf: (node: BuilderNode) => ScenarioAction | null;
  problemsOf: (id: string) => readonly BuilderProblem[];
  inputs: readonly string[];
  onSelect: (id: string | null) => void;
  /** A press on a block that moved: the caller takes the items out and answers them. */
  onTake: (stack: string, id: string, alone: boolean) => Item[];
  onDrop: (items: Item[], target: DropTarget) => void;
  onMoveStack: (stack: string, x: number, y: number) => void;
  /** The drag in progress (from a block or from the palette), owned by the builder. */
  drag: DragState | null;
  onDrag: (next: DragState | null) => void;
  statusOf?: (id: string) => ReactNode;
  /** The step number of each block (1, 2, 3.1 …), shown in the gutter. */
  numbers: ReadonlyMap<string, string>;
  /** A "+" was pressed: insert at this place; `anchor` is the button, for the menu. */
  onInsert: (target: { stack: string; slot: Slot; index: number }, anchor: DOMRect) => void;
  /** Reviewing Claude's proposal: the ids of its new or changed blocks (read-only canvas). */
  suggested?: ReadonlySet<string> | undefined;
  /** A preview in an environment: the plan's row of a step, and the environment's name. */
  planOf?: ((id: string) => ScenarioPlanRow | null) | undefined;
  planEnvironment?: string | null | undefined;
  /** The scenario changed after the preview: its lines say so. */
  planStale?: boolean | undefined;
  /** The hub's actions: still loading, could not be read, or read. */
  actions?: "loading" | "error" | "ready" | undefined;
  /** The hat ("when the scenario starts") was clicked: open the scenario's inputs. */
  onHat?: (() => void) | undefined;
}

export interface InsertTarget {
  stack: string;
  slot: Slot;
  index: number;
}

const DRAG_PX = 4;
/** Fit never zooms past this: blocks stay at a readable size, not a poster. */
const FIT_MAX = 1.2;
/** Fit never zooms out past this: below it the words cannot be read; the rest scrolls. */
const FIT_MIN = 0.8;
/** How near a gap the dragged blocks snap into it, in screen pixels. */
const SNAP_PX = 48;

interface Ctx {
  props: BlockCanvasProps;
  stack: string;
  dragging: boolean;
  target: DropTarget | null;
  startPress: (event: ReactPointerEvent, stack: string, id: string) => void;
}

function isTarget(target: DropTarget | null, stack: string, slot: Slot, index: number): boolean {
  if (!target || !("slot" in target)) return false;
  return (
    target.stack === stack &&
    target.index === index &&
    JSON.stringify(target.slot) === JSON.stringify(slot)
  );
}

/** The link between two steps: an arrow down, a drop zone, and a "+" on it. */
function Gap({
  ctx,
  slot,
  index,
  empty,
  where,
  first = false,
}: {
  ctx: Ctx;
  slot: Slot;
  index: number;
  empty?: string;
  where: string;
  first?: boolean;
}) {
  const active = isTarget(ctx.target, ctx.stack, slot, index);
  const plus = !ctx.dragging && ctx.stack !== "ghost" && (
    <button
      type="button"
      className="bk-plus"
      aria-label={`Add a block ${where}`}
      title={`Add a step ${where}`}
      data-no-pan=""
      onPointerDown={(event) => {
        event.stopPropagation();
      }}
      onClick={(event) => {
        ctx.props.onInsert(
          { stack: ctx.stack, slot, index },
          event.currentTarget.getBoundingClientRect(),
        );
      }}
    >
      <Icon name="plus" size="sm" />
      {empty && <span>{empty}</span>}
    </button>
  );
  return (
    <div
      className={empty ? "bk-mouth-empty" : "bk-gap"}
      data-first={first || undefined}
      data-drop={JSON.stringify({ stack: ctx.stack, slot, index })}
      data-active={active || undefined}
    >
      {empty && ctx.dragging ? <span>drop here</span> : plus}
    </div>
  );
}

function List({
  ctx,
  items,
  slot,
  empty,
}: {
  ctx: Ctx;
  items: readonly Item[];
  slot: Slot;
  empty: string;
}) {
  if (items.length === 0) {
    return (
      <div className="bk-list" role="group">
        <Gap ctx={ctx} slot={slot} index={0} empty={empty} where={empty} />
      </div>
    );
  }
  return (
    <div className="bk-list" role="group">
      <Gap
        ctx={ctx}
        slot={slot}
        index={0}
        first
        where={`before ${items[0] ? itemId(items[0]) : "the first step"}`}
      />
      {items.map((item, index) => (
        <div key={itemId(item)} className="bk-entry">
          <ItemView ctx={ctx} item={item} />
          <Gap ctx={ctx} slot={slot} index={index + 1} where={`after ${itemId(item)}`} />
        </div>
      ))}
    </div>
  );
}

function cardProps(ctx: Ctx, id: string, kind: string, label: string) {
  const look = kindLook(kind);
  return {
    "data-no-pan": "",
    "data-selected": ctx.props.selected === id || undefined,
    "data-suggested": ctx.props.suggested?.has(id) === true || undefined,
    "data-invalid":
      ctx.props.problemsOf(id).some((problem) => problem.severity === "error") || undefined,
    style: { ["--kind" as string]: look.tint, ["--kind-soft" as string]: look.soft },
    role: "treeitem",
    tabIndex: 0,
    "aria-label": label,
    "aria-selected": ctx.props.selected === id,
    onPointerDown: (event: ReactPointerEvent) => {
      ctx.startPress(event, ctx.stack, id);
    },
    onKeyDown: (event: KeyboardEvent) => {
      if (event.target !== event.currentTarget) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        ctx.props.onSelect(id);
      }
    },
  };
}

/** The card's head for a block: kind, number, effect, draft, problems, run status. */
function Head({
  ctx,
  id,
  kind,
  action,
}: {
  ctx: Ctx;
  id: string;
  kind: string;
  action?: ScenarioAction | null;
}) {
  const look = kindLook(kind);
  const problems = ctx.props.problemsOf(id);
  return (
    <CardHead
      icon={look.icon}
      kind={look.label}
      number={ctx.props.numbers.get(id)}
      action={action ?? null}
      errors={problems.filter((problem) => problem.severity === "error").length}
      warnings={
        problems.filter(
          (problem) => problem.severity !== "error" && !/draft/i.test(problem.message),
        ).length
      }
      extra={ctx.props.statusOf?.(id)}
    />
  );
}

/** What the preview in an environment says the step would do there. */
function PlanLine({ ctx, id }: { ctx: Ctx; id: string }) {
  const row = ctx.props.planOf?.(id) ?? null;
  if (!row) return null;
  return (
    <div
      className="bk-plan-line"
      data-decision={row.decision}
      data-stale={ctx.props.planStale === true || undefined}
    >
      <Icon name={ctx.props.planStale ? "clock" : "scan-eye"} size="sm" />
      <span>
        {ctx.props.planEnvironment
          ? `In ${ctx.props.planEnvironment}${ctx.props.planStale ? " (before your last change)" : ""}: `
          : ""}
        {row.plan}
      </span>
    </div>
  );
}

/** The selected card's problems, one line each (the form has the fields to fix them). */
function Problems({ ctx, id }: { ctx: Ctx; id: string }) {
  if (ctx.props.selected !== id) return null;
  const problems = ctx.props.problemsOf(id);
  if (problems.length === 0) return null;
  return (
    <ul className="bk-problems">
      {problems.map((problem, index) => (
        <li key={index} data-severity={problem.severity}>
          <Icon name={problem.severity === "error" ? "circle-x" : "triangle-alert"} size="sm" />
          {problem.message}
        </li>
      ))}
    </ul>
  );
}

function ItemView({ ctx, item }: { ctx: Ctx; item: Item }) {
  if (item.kind === "block") {
    const node = item.node;
    const look = kindLook(node.type);
    const action = ctx.props.actionOf(node);
    const selected = ctx.props.selected === node.id;
    return (
      <div className="bk-card" {...cardProps(ctx, node.id, node.type, `${look.label} ${node.id}`)}>
        <Head ctx={ctx} id={node.id} kind={node.type} action={action} />
        <div className="bk-title">
          <TokenText value={cardTitle(node, action)} />
        </div>
        <RunsLine node={node} action={action} actions={ctx.props.actions} />
        <CardFacts node={node} action={action} selected={selected} runInputs={ctx.props.inputs} />
        <PlanLine ctx={ctx} id={node.id} />
        <Problems ctx={ctx} id={node.id} />
      </div>
    );
  }
  if (item.kind === "repeat") {
    const node = item.node;
    return (
      <div className="bk-group" data-kind="repeat">
        <div
          className="bk-card bk-head"
          {...cardProps(ctx, node.id, "loop_group", `Repeat ${node.id}`)}
        >
          <Head ctx={ctx} id={node.id} kind="loop_group" />
          <div className="bk-title">{cardTitle(node, null)}</div>
          <CardFacts node={node} action={null} selected={ctx.props.selected === node.id} />
          <Problems ctx={ctx} id={node.id} />
        </div>
        <div className="bk-lane bk-loop">
          <List
            ctx={ctx}
            items={item.body}
            slot={{ in: "body", owner: node.id }}
            empty="put the steps that repeat here"
          />
          <span className="bk-foot">
            <Icon name="refresh-cw" size="sm" /> back to the top until it holds
          </span>
        </div>
      </div>
    );
  }
  if (item.kind === "if") {
    return (
      <div className="bk-group" data-kind="if">
        <div className="bk-card bk-head" {...cardProps(ctx, item.key, "branch", "If")}>
          <Head ctx={ctx} id={item.key} kind="branch" />
          <div className="bk-title">
            {item.condition ? `If ${conditionWords(item.condition)}` : "If a condition holds"}
          </div>
        </div>
        <div className="bk-lanes">
          <div className="bk-lane">
            <span className="bk-lane-label">yes</span>
            <List
              ctx={ctx}
              items={item.then}
              slot={{ in: "then", owner: item.key }}
              empty="what happens when it holds"
            />
          </div>
          <div className="bk-lane">
            <span className="bk-lane-label">no</span>
            <List
              ctx={ctx}
              items={item.otherwise}
              slot={{ in: "otherwise", owner: item.key }}
              empty="otherwise (or nothing: skip to the next block)"
            />
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="bk-group" data-kind="parallel">
      <div
        className="bk-card bk-head"
        {...cardProps(ctx, item.key, "parallel", "At the same time")}
      >
        <Head ctx={ctx} id={item.key} kind="parallel" />
        <div className="bk-title">Run {item.lanes.length} paths at the same time</div>
        <dl className="sc-values bk-facts-grid">
          <div className="sc-value">
            <dt>Then</dt>
            <dd>continues when every path ends</dd>
          </div>
        </dl>
      </div>
      <div className="bk-lanes">
        {item.lanes.map((lane, index) => (
          <div key={index} className="bk-lane">
            <span className="bk-lane-label">path {index + 1}</span>
            <List
              ctx={ctx}
              items={lane}
              slot={{ in: "lane", owner: item.key, lane: index }}
              empty="a path"
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function StackView({
  stack,
  ctx,
  hat,
  steps,
}: {
  stack: Stack;
  ctx: Ctx;
  hat?: ReactNode;
  steps?: number;
}) {
  return (
    <div
      className="bk-stack"
      style={{ left: stack.x, top: stack.y }}
      data-loose={!hat || undefined}
      role="tree"
      aria-label={hat ? "Steps of the scenario" : "Loose steps"}
    >
      {hat}
      {!hat && (
        <div className="bk-loose-note">
          <Icon name="triangle-alert" size="sm" />
          {stack.kept
            ? "Kept as written: the blocks cannot show how these connect"
            : "Not connected: snap under a step to use it (not saved)"}
        </div>
      )}
      <List
        ctx={ctx}
        items={stack.items}
        slot={{ in: "main" }}
        empty={hat ? "add the first step" : ""}
      />
      {hat && (
        <div className="bk-cap">
          <Icon name="circle-check" size="sm" />
          End
          {steps !== undefined ? ` · ${String(steps)} ${steps === 1 ? "step" : "steps"}` : ""}
        </div>
      )}
    </div>
  );
}

export function BlockCanvas(props: BlockCanvasProps) {
  const viewport = useRef<HTMLDivElement>(null);
  const pz = usePanZoom(viewport, { wheel: "pan", min: 0.4, max: 1.6 });
  const size = useViewportSize(viewport);
  const { drag, onDrag: setDrag } = props;
  const active = drag;

  // Fit the stacks (not a fixed box) in the viewport: on first show, and on Fit.
  const { setView } = pz;
  const fit = useCallback(
    (animate: boolean, whole = false) => {
      const stacks = viewport.current?.querySelectorAll<HTMLElement>(".bk-world > .bk-stack") ?? [];
      let box: { left: number; top: number; right: number; bottom: number } | null = null;
      stacks.forEach((stack) => {
        const left = stack.offsetLeft;
        const top = stack.offsetTop;
        const right = left + stack.offsetWidth;
        const bottom = top + stack.offsetHeight;
        box = box
          ? {
              left: Math.min(box.left, left),
              top: Math.min(box.top, top),
              right: Math.max(box.right, right),
              bottom: Math.max(box.bottom, bottom),
            }
          : { left, top, right, bottom };
      });
      const found = box as { left: number; top: number; right: number; bottom: number } | null;
      if (!found || size.width === 0) return;
      const world = { width: found.right - found.left, height: found.bottom - found.top };
      // On open: read it at 100 % (90 % on a small screen), from the top; Fit shows it whole.
      const k = whole
        ? fitView(world, size, { max: FIT_MAX, min: 0.3, pad: 48 }).k
        : size.width < 1100
          ? FIT_MIN + 0.1
          : 1;
      const x = (size.width - world.width * k) / 2 - found.left * k;
      const y = whole && world.height * k < size.height ? (size.height - world.height * k) / 2 : 24;
      setView({ k, x, y: y - found.top * k }, animate);
    },
    [setView, size],
  );
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current || size.width === 0) return;
    fitted.current = true;
    fit(false);
  }, [fit, size.width]);

  // The selected card stays in view: the side form narrows the canvas when it opens.
  const latest = useRef(pz.view);
  useEffect(() => {
    latest.current = pz.view;
  });
  useEffect(() => {
    const frame = viewport.current;
    const world = frame?.querySelector<HTMLElement>(".bk-world");
    const card = world?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!frame || !world || !card) return;
    // Where the card sits in the world (steady while the view animates), then on screen once
    // the view reaches its target.
    const view = latest.current;
    const k = view.k;
    const box = card.getBoundingClientRect();
    const origin = world.getBoundingClientRect();
    const at = {
      x: (box.left - origin.left) / k,
      y: (box.top - origin.top) / k,
      width: box.width / k,
      height: box.height / k,
    };
    const width = frame.clientWidth;
    const height = frame.clientHeight;
    const left = view.x + at.x * view.k;
    const top = view.y + at.y * view.k;
    const right = left + at.width * view.k;
    const bottom = top + at.height * view.k;
    const dx = left < 24 || right > width - 24 ? width / 2 - (left + right) / 2 : 0;
    const dy =
      top < 24
        ? 48 - top
        : bottom > height - 24 && bottom - top < height - 96
          ? height - 48 - bottom
          : 0;
    if (dx === 0 && dy === 0) return;
    setView({ k: view.k, x: view.x + dx, y: view.y + dy }, true);
  }, [props.selected, size.width, setView]);

  const toWorld = (clientX: number, clientY: number) => {
    const rect = viewport.current?.getBoundingClientRect();
    const { x, y, k } = pz.view;
    return { x: (clientX - (rect?.left ?? 0) - x) / k, y: (clientY - (rect?.top ?? 0) - y) / k };
  };

  const targetAt = (
    clientX: number,
    clientY: number,
    grab: { x: number; y: number },
  ): DropTarget | null => {
    const hit = document.elementFromPoint(clientX, clientY)?.closest<HTMLElement>("[data-drop]");
    if (hit?.dataset.drop) return JSON.parse(hit.dataset.drop) as DropTarget;
    // Snap, as Scratch does: the nearest gap or mouth to the dragged block's top left corner.
    const corner = { x: clientX - grab.x * pz.view.k, y: clientY - grab.y * pz.view.k };
    let best: { distance: number; drop: string } | null = null;
    viewport.current?.querySelectorAll<HTMLElement>(".bk-world [data-drop]").forEach((zone) => {
      const box = zone.getBoundingClientRect();
      const dx =
        corner.x < box.left ? box.left - corner.x : corner.x > box.right ? corner.x - box.right : 0;
      const dy = Math.abs(corner.y - (box.top + box.bottom) / 2);
      const distance = Math.hypot(dx, dy);
      if (zone.dataset.drop && distance < SNAP_PX && (best === null || distance < best.distance)) {
        best = { distance, drop: zone.dataset.drop };
      }
    });
    const snapped = best as { distance: number; drop: string } | null;
    if (snapped) return JSON.parse(snapped.drop) as DropTarget;
    const rect = viewport.current?.getBoundingClientRect();
    if (
      !rect ||
      clientX < rect.left ||
      clientX > rect.right ||
      clientY < rect.top ||
      clientY > rect.bottom
    )
      return null;
    const at = toWorld(clientX - grab.x, clientY - grab.y);
    return { free: { x: Math.round(at.x), y: Math.round(at.y) } };
  };

  // While a drag runs (from a block or from the palette), the window follows the pointer.
  useEffect(() => {
    if (!active) return;
    const move = (event: PointerEvent) => {
      const grab = active.grab;
      setDrag({
        ...active,
        client: { x: event.clientX, y: event.clientY },
        target: targetAt(event.clientX, event.clientY, grab),
      });
    };
    const up = (event: PointerEvent) => {
      const target = targetAt(event.clientX, event.clientY, active.grab);
      setDrag(null);
      props.onDrop(active.items, target ?? { free: toWorld(event.clientX, event.clientY) });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  });

  const startPress = (event: ReactPointerEvent, stack: string, id: string) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
    // The press lives in these handlers' closure: a click selects, a move past DRAG_PX drags.
    const p = { stack, id, x: event.clientX, y: event.clientY, alt: event.altKey, box };
    let pressed = true;
    const move = (moved: PointerEvent) => {
      if (!pressed || Math.hypot(moved.clientX - p.x, moved.clientY - p.y) < DRAG_PX) return;
      pressed = false;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const items = props.onTake(p.stack, p.id, p.alt);
      if (items.length === 0) return;
      const k = pz.view.k;
      const grab = { x: (p.x - p.box.left) / k, y: (p.y - p.box.top) / k };
      setDrag({ items, grab, client: { x: moved.clientX, y: moved.clientY }, target: null });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      if (pressed) props.onSelect(p.id);
      pressed = false;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  };

  const ctx = (stack: string): Ctx => ({
    props,
    stack,
    dragging: active !== null,
    target: active?.target ?? null,
    startPress,
  });

  const inputsText =
    props.inputs.length === 0
      ? ""
      : props.inputs.length <= 2
        ? ` · with ${props.inputs.join(" and ")}`
        : ` · with ${props.inputs.slice(0, 2).join(", ")} and ${String(props.inputs.length - 2)} more`;
  const hat = (
    <button
      type="button"
      className="bk-hat"
      data-no-pan=""
      onClick={props.onHat}
      title="The scenario's inputs"
    >
      <span className="bk-icon bk-icon-neutral" aria-hidden>
        <Icon name="flag" size="sm" />
      </span>
      <span>
        <b>When the scenario starts</b>
        <span className="bk-quiet">{inputsText}</span>
      </span>
    </button>
  );
  const count = (items: readonly Item[]): number =>
    items.reduce(
      (total, item) =>
        total +
        (item.kind === "block"
          ? 1
          : item.kind === "repeat"
            ? 1 + count(item.body)
            : item.kind === "if"
              ? count(item.then) + count(item.otherwise)
              : item.lanes.reduce((sum, lane) => sum + count(lane), 0)),
      0,
    );

  return (
    <div
      ref={viewport}
      className="bk-viewport"
      data-dragging={active ? "" : undefined}
      {...pz.handlers}
    >
      <div
        className="bk-world"
        style={{
          transform: `translate(${String(pz.view.x)}px, ${String(pz.view.y)}px) scale(${String(pz.view.k)})`,
          transition: pz.animated ? "transform 160ms ease" : undefined,
        }}
      >
        <StackView
          stack={props.main}
          ctx={ctx(props.main.id)}
          hat={hat}
          steps={count(props.main.items)}
        />
        {props.loose.map((stack) => (
          <StackView key={stack.id} stack={stack} ctx={ctx(stack.id)} />
        ))}
      </div>
      {active && (
        <div
          className="bk-ghost"
          style={{
            left: active.client.x - active.grab.x * pz.view.k,
            top: active.client.y - active.grab.y * pz.view.k,
            transform: `scale(${String(pz.view.k)})`,
          }}
          aria-hidden
        >
          {active.items.map((item) => (
            <ItemView
              key={itemId(item)}
              item={item}
              ctx={{ ...ctx("ghost"), dragging: false, target: null }}
            />
          ))}
        </div>
      )}
      <CanvasControls
        view={pz.view}
        label="Block canvas"
        onZoomBy={(factor) => {
          pz.zoomBy(factor);
        }}
        onZoomTo={(k) => {
          pz.zoomTo(k);
        }}
        onFit={() => {
          fit(true, true);
        }}
      />
    </div>
  );
}
