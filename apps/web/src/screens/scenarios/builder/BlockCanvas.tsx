import {
  useCallback,
  useEffect,
  useRef,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import { CanvasControls, Icon, useViewportSize, type IconName } from "../../../components";
import { fitView } from "../../../lib/canvasView";
import { usePanZoom } from "../../../lib/usePanZoom";
import type { ScenarioAction, ScenarioPlanRow } from "../queries";
import { BlockFacts } from "./BlockFacts";
import { maxChecks } from "../story";
import { kindLook } from "./FlowCanvas";
import { conditionWords, refInWords, shown, text, type BuilderNode, type Json } from "./model";
import { itemId, type Item, type Slot } from "./program";
import type { BuilderProblem } from "./useScenarioDraft";

/* The block canvas: the scenario as Scratch-like stacks on a free canvas. A block snapped under
 * another runs after it; C-blocks hold blocks (Repeat, If / else, At the same time). Dragging a
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
  onEditNode: (node: BuilderNode) => void;
  /** The drag in progress (from a block or from the palette), owned by the builder. */
  drag: DragState | null;
  onDrag: (next: DragState | null) => void;
  statusOf?: (id: string) => ReactNode;
  /** The step number of each block (1, 2, 3.1 …), shown in the gutter. */
  numbers: ReadonlyMap<string, string>;
  /** A "+" was pressed: insert at this place; `anchor` is the button, for the menu. */
  onInsert: (target: { stack: string; slot: Slot; index: number }, anchor: DOMRect) => void;
  /** A slot was clicked: open its popover. */
  onSlot: (request: SlotRequest) => void;
  /** Reviewing Claude's proposal: the ids of its new or changed blocks (read-only canvas). */
  suggested?: ReadonlySet<string> | undefined;
  /** A preview in an environment: the plan's row of a step, and the environment's name. */
  planOf?: ((id: string) => ScenarioPlanRow | null) | undefined;
  planEnvironment?: string | null | undefined;
}

/** A slot of a block clicked to fill it: which block (or C-block), which key, where. */
export interface SlotRequest {
  id: string;
  kind: "action" | "value" | "condition" | "text" | "include";
  /** The key it edits: `action`, `with.<input>`, `until_when`, `message`, `include`, `if`. */
  key: string;
  anchor: DOMRect;
}

export interface InsertTarget {
  stack: string;
  slot: Slot;
  index: number;
}

const DRAG_PX = 4;
/** Fit never zooms past this: blocks stay at a readable size, not a poster. */
const FIT_MAX = 1.2;
/** How near a gap the dragged blocks snap into it, in screen pixels. */
const SNAP_PX = 48;

function Field({
  value,
  label,
  width = 56,
  onChange,
}: {
  value: string;
  label: string;
  width?: number;
  onChange: (value: string) => void;
}) {
  return (
    <input
      className="bk-field"
      aria-label={label}
      value={value}
      style={{ width }}
      onPointerDown={(event) => {
        event.stopPropagation();
      }}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  );
}

function Pill({
  children,
  title,
  empty,
  label,
  onOpen,
  className = "bk-pill",
}: {
  children: ReactNode;
  title?: string | undefined;
  empty?: boolean;
  /** The slot's name, for its accessible name ("action: demo-get-status, change"). */
  label?: string;
  onOpen?: ((anchor: DOMRect) => void) | undefined;
  className?: string;
}) {
  if (!onOpen) {
    return (
      <span className={className} data-empty={empty === true ? true : undefined} title={title}>
        {children}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={`${className} bk-slot`}
      data-empty={empty === true ? true : undefined}
      data-no-pan=""
      title={title ?? "Click to change"}
      aria-label={label ? `${label}: ${empty ? "choose" : "change"}` : undefined}
      onPointerDown={(event) => {
        event.stopPropagation();
      }}
      onClick={(event) => {
        event.stopPropagation();
        onOpen(event.currentTarget.getBoundingClientRect());
      }}
    >
      {children}
    </button>
  );
}

function Condition({
  value,
  placeholder,
  onOpen,
}: {
  value: string;
  placeholder: string;
  onOpen?: (anchor: DOMRect) => void;
}) {
  return value.trim() === "" ? (
    <Pill empty label="condition" onOpen={onOpen}>
      {placeholder}
    </Pill>
  ) : (
    <Pill title={value} label="condition" onOpen={onOpen}>
      <Icon name="split" size="sm" /> {conditionWords(value)}
    </Pill>
  );
}

function firstLine(value: string): string | null {
  const line = value.split("\n")[0] ?? "";
  return line === "" ? null : line;
}

function values(node: BuilderNode): [string, Json][] {
  const given = node.with;
  return typeof given === "object" && given !== null && !Array.isArray(given)
    ? Object.entries(given)
    : [];
}

/** The words of a block, Scratch-like: verbs and inline fields. */
function BlockWords({
  node,
  facts,
  onEditNode,
  onSlot,
}: {
  node: BuilderNode;
  facts: ScenarioAction | null;
  onEditNode: (node: BuilderNode) => void;
  onSlot: (request: SlotRequest) => void;
}) {
  const set = (key: string, value: Json) => {
    onEditNode({ ...node, [key]: value });
  };
  const open =
    (kind: SlotRequest["kind"], key: string) =>
    (anchor: DOMRect): void => {
      onSlot({ id: node.id, kind, key, anchor });
    };
  const action = text(node.action);
  const actionPill = (
    <Pill empty={action === ""} label="action" onOpen={open("action", "action")}>
      {action === "" ? "choose an action" : action}
    </Pill>
  );
  const given = new Set(values(node).map(([key]) => key));
  const missing = (facts?.inputs ?? []).filter((input) => input.required && !given.has(input.name));
  const kept = Object.keys(
    typeof node.capture === "object" && node.capture !== null && !Array.isArray(node.capture)
      ? node.capture
      : {},
  );
  const chips = (
    <>
      {values(node).map(([key, value]) => {
        const words = refInWords(shown(value));
        return (
          <span key={key} className="bk-pair">
            <span className="bk-label">{key.replace(/_/g, " ")}</span>
            <Pill
              title={`${key} = ${shown(value)} · click to change`}
              label={key}
              onOpen={open("value", `with.${key}`)}
            >
              {words.ref && <Icon name="bookmark" size="sm" />}
              {words.text}
            </Pill>
          </span>
        );
      })}
      {missing.map((input) => (
        <span key={input.name} className="bk-pair">
          <span className="bk-label">{input.name.replace(/_/g, " ")}</span>
          <Pill empty label={input.name} onOpen={open("value", `with.${input.name}`)}>
            {input.description ?? "a value"}
          </Pill>
        </span>
      ))}
      {kept.map((name) => (
        <span key={name} className="bk-pair">
          <span className="bk-label">keep as</span>
          <span className="bk-pill bk-pill-kept">
            <Icon name="bookmark" size="sm" />
            {name}
          </span>
        </span>
      ))}
    </>
  );
  switch (node.type) {
    case "action":
      return (
        <>
          <span>run</span>
          {actionPill}
          {chips}
        </>
      );
    case "expect": {
      const every = text(node.every);
      const timeout = text(node.timeout);
      const checks = every && timeout ? maxChecks(every, timeout) : null;
      return (
        <>
          <span>wait until</span>
          <Condition
            value={text(node.until_when)}
            placeholder="a state holds"
            onOpen={open("condition", "until_when")}
          />
          <span className="bk-sep">·</span>
          <span className="bk-label">reading</span>
          {actionPill}
          <span className="bk-sep">·</span>
          <span className="bk-label">every</span>
          <Field
            value={every}
            label={`Check every, ${node.id}`}
            width={44}
            onChange={(value) => {
              set("every", value);
            }}
          />
          <span className="bk-label">up to</span>
          <Field
            value={timeout}
            label={`For up to, ${node.id}`}
            width={44}
            onChange={(value) => {
              set("timeout", value);
            }}
          />
          {checks !== null && <span className="bk-quiet">({checks} checks)</span>}
          {chips}
        </>
      );
    }
    case "approval":
      return (
        <>
          <span>ask me to</span>
          <Pill
            className="bk-pill bk-pill-text"
            title={text(node.message)}
            label="what to do"
            empty={firstLine(text(node.message)) === null}
            onOpen={open("text", "message")}
          >
            {firstLine(text(node.message)) ?? "do something by hand"}
          </Pill>
          {node.capture_response === true && <span className="bk-label">and keep what I type</span>}
        </>
      );
    case "wait":
      return (
        <>
          <span>wait</span>
          <Field
            value={text(node.duration)}
            label={`Wait for, ${node.id}`}
            width={48}
            onChange={(value) => {
              set("duration", value);
            }}
          />
        </>
      );
    case "include":
      return (
        <>
          <span>run the scenario</span>
          <Pill
            empty={text(node.include) === ""}
            label="scenario"
            onOpen={open("include", "include")}
          >
            {text(node.include) || "choose one"}
          </Pill>
        </>
      );
    default:
      return <span>{node.type}</span>;
  }
}

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

function Gap({
  ctx,
  slot,
  index,
  empty,
  where,
}: {
  ctx: Ctx;
  slot: Slot;
  index: number;
  empty?: string;
  where: string;
}) {
  const active = isTarget(ctx.target, ctx.stack, slot, index);
  const plus = !ctx.dragging && ctx.stack !== "ghost" && (
    <button
      type="button"
      className="bk-plus"
      aria-label={`Add a block ${where}`}
      title={`Add a block ${where}`}
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
    return <Gap ctx={ctx} slot={slot} index={0} empty={empty} where={empty} />;
  }
  return (
    <div className="bk-list">
      <Gap
        ctx={ctx}
        slot={slot}
        index={0}
        where={`before ${items[0] ? itemId(items[0]) : "the first block"}`}
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

const EFFECT_MARK: Readonly<Record<string, { icon: IconName; words: string }>> = {
  read: { icon: "file-text", words: "Reads only" },
  write: { icon: "file-pen", words: "Changes data" },
  destroy: { icon: "triangle-alert", words: "Deletes or replaces data" },
};

/** The block's marks at its right edge: effect, draft, problems, warnings, then a run's status. */
function Badges({ ctx, node }: { ctx: Ctx; node: BuilderNode }) {
  const action = ctx.props.actionOf(node);
  const problems = ctx.props.problemsOf(node.id);
  const errors = problems.filter((problem) => problem.severity === "error");
  const warnings = problems.filter(
    (problem) => problem.severity !== "error" && !/draft/i.test(problem.message),
  );
  const effect = action?.effect ? EFFECT_MARK[action.effect] : undefined;
  return (
    <span className="bk-marks">
      {effect && (
        <span className="bk-mark" title={effect.words} aria-label={effect.words}>
          <Icon name={effect.icon} size="sm" />
        </span>
      )}
      {action?.draft && (
        <span
          className="bk-mark"
          title="Draft action: commit it in the hub before the scenario can run"
          aria-label="Draft action"
        >
          <Icon name="circle-dashed" size="sm" />
        </span>
      )}
      {warnings.length > 0 && (
        <span
          className="bk-mark bk-mark-warn"
          title={warnings.map((problem) => problem.message).join("\n")}
        >
          <Icon name="triangle-alert" size="sm" />
        </span>
      )}
      {errors.length > 0 && (
        <span
          className="bk-mark bk-errors"
          title={errors.map((problem) => problem.message).join("\n")}
        >
          <Icon name="circle-x" size="sm" /> {errors.length}
        </span>
      )}
      {ctx.props.statusOf?.(node.id)}
    </span>
  );
}

function Num({ ctx, id }: { ctx: Ctx; id: string }) {
  const n = ctx.props.numbers.get(id);
  return n ? (
    <span className="bk-num" aria-hidden>
      {n}
    </span>
  ) : null;
}

function blockProps(ctx: Ctx, id: string, kind: string, label: string) {
  const look = kindLook(kind);
  return {
    "data-no-pan": "",
    "data-selected": ctx.props.selected === id || undefined,
    "data-suggested": ctx.props.suggested?.has(id) === true || undefined,
    "data-invalid":
      ctx.props.problemsOf(id).some((problem) => problem.severity === "error") || undefined,
    style: { ["--kind" as string]: look.tint },
    role: "button",
    tabIndex: 0,
    "aria-label": label,
    "aria-pressed": ctx.props.selected === id,
    onPointerDown: (event: ReactPointerEvent) => {
      ctx.startPress(event, ctx.stack, id);
    },
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        ctx.props.onSelect(id);
      }
    },
  };
}

function ControlHead({ icon, children }: { icon: IconName; children: ReactNode }) {
  return (
    <div className="bk-c-head">
      <Icon name={icon} size="sm" />
      {children}
    </div>
  );
}

function ItemView({ ctx, item }: { ctx: Ctx; item: Item }) {
  if (item.kind === "block") {
    const node = item.node;
    const look = kindLook(node.type);
    return (
      <div
        className="bk-block"
        {...blockProps(ctx, node.id, node.type, `${look.label} ${node.id}`)}
      >
        <Num ctx={ctx} id={node.id} />
        <span className="bk-icon" aria-hidden>
          <Icon name={look.icon} size="sm" />
        </span>
        <span className="bk-body">
          {typeof node.description === "string" && node.description !== "" && (
            <span className="bk-caption">{node.description}</span>
          )}
          <span className="bk-words">
            <BlockWords
              node={node}
              facts={ctx.props.actionOf(node)}
              onEditNode={ctx.props.onEditNode}
              onSlot={ctx.props.onSlot}
            />
          </span>
          <BlockFacts
            node={node}
            action={ctx.props.actionOf(node)}
            row={ctx.props.planOf?.(node.id) ?? null}
            environment={ctx.props.planEnvironment ?? null}
          />
        </span>
        <Badges ctx={ctx} node={node} />
      </div>
    );
  }
  if (item.kind === "repeat") {
    const node = item.node;
    return (
      <div className="bk-c" {...blockProps(ctx, node.id, "loop_group", `Repeat ${node.id}`)}>
        <ControlHead icon="refresh-cw">
          <Num ctx={ctx} id={node.id} />
          <span>repeat until</span>
          <Condition
            value={text(node.until_when)}
            placeholder="a state holds"
            onOpen={(anchor) => {
              ctx.props.onSlot({ id: node.id, kind: "condition", key: "until_when", anchor });
            }}
          />
          <span>· at most</span>
          <Field
            value={text(node.max_iterations, "1")}
            label={`Rounds, ${node.id}`}
            width={36}
            onChange={(value) => {
              ctx.props.onEditNode({
                ...node,
                max_iterations: /^\d+$/.test(value) ? Number(value) : value,
              });
            }}
          />
          <span>rounds</span>
          <Badges ctx={ctx} node={node} />
        </ControlHead>
        <div className="bk-mouth">
          <List
            ctx={ctx}
            items={item.body}
            slot={{ in: "body", owner: node.id }}
            empty="put the blocks that repeat here"
          />
        </div>
        <div className="bk-c-foot">then go on</div>
      </div>
    );
  }
  if (item.kind === "if") {
    return (
      <div className="bk-c" {...blockProps(ctx, item.key, "branch", "If")}>
        <ControlHead icon="split">
          <Num ctx={ctx} id={item.key} />
          <span>if</span>
          <Condition
            value={item.condition}
            placeholder="a condition"
            onOpen={(anchor) => {
              ctx.props.onSlot({ id: itemId(item), kind: "condition", key: "if", anchor });
            }}
          />
        </ControlHead>
        <div className="bk-mouth">
          <List
            ctx={ctx}
            items={item.then}
            slot={{ in: "then", owner: item.key }}
            empty="what happens when it holds"
          />
        </div>
        <div className="bk-c-mid">else</div>
        <div className="bk-mouth">
          <List
            ctx={ctx}
            items={item.otherwise}
            slot={{ in: "otherwise", owner: item.key }}
            empty="otherwise (or nothing: skip to the next block)"
          />
        </div>
        <div className="bk-c-foot">then go on after the path taken</div>
      </div>
    );
  }
  return (
    <div className="bk-c" {...blockProps(ctx, item.key, "parallel", "At the same time")}>
      <ControlHead icon="git-branch">
        <Num ctx={ctx} id={item.key} />
        <span>at the same time</span>
      </ControlHead>
      <div className="bk-lanes">
        {item.lanes.map((lane, index) => (
          <div key={index} className="bk-mouth bk-lane">
            <List
              ctx={ctx}
              items={lane}
              slot={{ in: "lane", owner: item.key, lane: index }}
              empty="a path"
            />
          </div>
        ))}
      </div>
      <div className="bk-c-foot">then go on when every path finished</div>
    </div>
  );
}

function StackView({ stack, ctx, hat }: { stack: Stack; ctx: Ctx; hat?: ReactNode }) {
  return (
    <div
      className="bk-stack"
      style={{ left: stack.x, top: stack.y }}
      data-loose={!hat || undefined}
    >
      {hat}
      {!hat && (
        <div className="bk-loose-note">
          <Icon name="triangle-alert" size="sm" />
          {stack.kept
            ? "Kept as written: the blocks cannot show how these connect"
            : "Not connected: snap under a block to use it (not saved)"}
        </div>
      )}
      <List
        ctx={ctx}
        items={stack.items}
        slot={{ in: "main" }}
        empty={hat ? "drag blocks here" : ""}
      />
      {hat && (
        <div className="bk-cap">
          <Icon name="flag" size="sm" /> end of the scenario
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
    (animate: boolean) => {
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
      const view = fitView(world, size, { max: FIT_MAX, min: 0.5, pad: 48 });
      // Keep the top of a tall scenario in view rather than its middle.
      const y = world.height * view.k > size.height ? 48 : view.y;
      setView({ k: view.k, x: view.x - found.left * view.k, y: y - found.top * view.k }, animate);
    },
    [setView, size],
  );
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current || size.width === 0) return;
    fitted.current = true;
    fit(false);
  }, [fit, size.width]);

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

  const hat = (
    <div
      className="bk-hat"
      data-no-pan=""
      onPointerDown={(event) => {
        event.stopPropagation();
        const h = { x: event.clientX, y: event.clientY, sx: props.main.x, sy: props.main.y };
        const move = (moved: PointerEvent) => {
          props.onMoveStack(
            "main",
            h.sx + (moved.clientX - h.x) / pz.view.k,
            h.sy + (moved.clientY - h.y) / pz.view.k,
          );
        };
        const up = () => {
          window.removeEventListener("pointermove", move);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up, { once: true });
      }}
      title="Drag to move the scenario on the canvas"
    >
      <Icon name="flag" size="sm" />
      <span>when the scenario starts</span>
      {props.inputs.length > 0 && <span className="bk-quiet">with {props.inputs.join(", ")}</span>}
    </div>
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
        <StackView stack={props.main} ctx={ctx(props.main.id)} hat={hat} />
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
          fit(true);
        }}
      />
    </div>
  );
}
