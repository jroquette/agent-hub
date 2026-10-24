import "./steps.css";

import {
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { Button, Icon, IconButton } from "../../../components";
import { EffectBadge } from "../parts";
import type { ScenarioAction, ScenarioPlanRow } from "../queries";
import { pace } from "../story";
import { TokenText, ValueToken, cardTitle, tokenOf } from "./CardParts";
import { kindLook } from "./FlowCanvas";
import { conditionWords, shown, text, type BuilderNode, type Json } from "./model";
import { itemId, type Item, type Slot } from "./program";
import type { BuilderProblem } from "./useScenarioDraft";

/* The step list (scenario builder v6): the scenario read top to bottom like a runbook. Each step
 * is a numbered row of two lines (what it does, then its action and the values it sets itself);
 * Repeat, If and At the same time are indented groups. Order is the only thing a position means,
 * so a step always sits in the list: it moves by its handle, by Alt ↑/↓, or by the row menu, and
 * a "+" in each gap adds one there. Selecting a row opens it in the editor on the right. */

export interface InsertTarget {
  slot: Slot;
  index: number;
}

export interface StepListProps {
  scenarioName: string;
  items: readonly Item[];
  numbers: ReadonlyMap<string, string>;
  selected: string | null;
  actionOf: (node: BuilderNode) => ScenarioAction | null;
  problemsOf: (id: string) => readonly BuilderProblem[];
  planOf: (id: string) => ScenarioPlanRow | null;
  planStale: boolean;
  /** The Start row: where the scenario runs and what it asks for. */
  start: { environment: string | null; asks: readonly string[]; selected: boolean };
  onStart: () => void;
  onSelect: (id: string) => void;
  onInsert: (target: InsertTarget, anchor: DOMRect, label: string) => void;
  onMove: (id: string, target: InsertTarget) => void;
  onRowMenu: (id: string, anchor: DOMRect) => void;
  /** A variable picked in the Variables tab: the rows that use it say so. */
  usesVariable?: ((node: BuilderNode) => boolean) | undefined;
  variable?: string | null | undefined;
  /** Claude's proposal under review: its new and changed steps are outlined. */
  suggested?: ReadonlySet<string> | undefined;
  readOnly?: boolean;
  /** Blocks the list cannot place (connected in a way nested paths do not show). */
  loose: readonly BuilderNode[];
  onOpenYaml: () => void;
  footer?: ReactNode;
  /** Shown under the list while it holds no step (start from a shape, describe it). */
  empty?: ReactNode;
  /** A block dragged from the palette: the gap it would land in. */
  externalTarget?: InsertTarget | null;
  /** The list's scrolling element, for a drag from the palette. */
  scrollRef?: RefObject<HTMLDivElement>;
}

function record(value: Json | undefined): Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

const KIND_NAME: Readonly<Record<string, string>> = {
  action: "Run an action",
  expect: "Wait until",
  wait: "Pause",
  approval: "Ask me",
  include: "Run a scenario",
  loop_group: "Repeat",
  if: "If",
  parallel: "At the same time",
};

/** The gap of the list nearest the pointer's height (null when none is within 80 px); `skip`
 * leaves out the gaps inside the step being moved. Shared by a move and a drag from the palette. */
export function nearestGap(
  root: HTMLElement | null,
  y: number,
  skip?: string,
): InsertTarget | null {
  const gaps = root?.querySelectorAll<HTMLElement>("[data-gap]") ?? [];
  let best: { at: InsertTarget; distance: number } | null = null;
  for (const gap of gaps) {
    if (skip && gap.closest(`[data-item="${CSS.escape(skip)}"]`)) continue;
    const box = gap.getBoundingClientRect();
    const distance = Math.abs(box.top + box.height / 2 - y);
    if (!best || distance < best.distance) {
      best = { at: JSON.parse(gap.dataset.gap ?? "null") as InsertTarget, distance };
    }
  }
  return best && best.distance < 80 ? best.at : null;
}

/** Scrolls the list while a drag nears its top or bottom edge. */
export function scrollNear(root: HTMLElement | null, y: number): void {
  const box = root?.getBoundingClientRect();
  if (!box || !root) return;
  if (y < box.top + 40) root.scrollBy(0, -12);
  else if (y > box.bottom - 40) root.scrollBy(0, 12);
}

export function kindName(type: string): string {
  return KIND_NAME[type] ?? type;
}

function compact(value: Json): string {
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (/^[[{]/.test(trimmed)) {
      try {
        return JSON.stringify(JSON.parse(trimmed));
      } catch {
        return trimmed.replace(/\s+/g, " ");
      }
    }
    return trimmed.replace(/\s+/g, " ");
  }
  return shown(value);
}

/** Line 2's values: only what the step sets itself (never a run value it merely repeats). */
function ownValues(node: BuilderNode, action: ScenarioAction | null): [string, Json][] {
  const given = record(node.with);
  const order = action?.inputs.map((input) => input.name) ?? [];
  return Object.entries(given)
    .filter(([name, value]) => value !== `$INPUTS.${name}`)
    .sort((a, b) => {
      const ia = order.indexOf(a[0]);
      const ib = order.indexOf(b[0]);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
}

function Value({ value }: { value: Json }) {
  const written = compact(value);
  if (tokenOf(written)) return <ValueToken value={written} />;
  return <TokenText value={written} />;
}

/** What line 1 and line 2 say for a node (an action, a check, a repeat …). */
function nodeLines(
  node: BuilderNode,
  action: ScenarioAction | null,
  inner: number,
): { title: string; detail: ReactNode; detailText: string } {
  const named = typeof node.description === "string" && node.description.trim() !== "";
  const title = cardTitle(node, action);
  const parts: ReactNode[] = [];
  const words: string[] = [];
  const add = (part: ReactNode, word: string) => {
    parts.push(<span key={parts.length}>{part}</span>);
    words.push(word);
  };
  const ref = text(node.action);
  if (node.type === "action" || node.type === "expect") {
    if (ref) add(<span className="st-mono">{action?.name ?? ref}</span>, ref);
  }
  if (node.type === "expect") {
    if (named && text(node.until_when)) {
      const words_ = `until ${conditionWords(text(node.until_when))}`;
      add(words_, words_);
    }
    const every = text(node.every);
    const timeout = text(node.timeout);
    if (every && timeout) {
      const timing = `every ${pace(every)}, up to ${pace(timeout)}`;
      add(timing, timing);
    }
  }
  if (node.type === "action" || node.type === "expect" || node.type === "include") {
    for (const [name, value] of ownValues(node, action)) {
      add(
        <>
          <span className="st-key">{name}</span> <Value value={value} />
        </>,
        `${name} ${compact(value)}`,
      );
    }
  }
  const kept = Object.keys(record(node.capture));
  if (kept.length > 0) {
    const keep = `keeps ${kept.join(", ")}`;
    add(keep, keep);
  }
  if (node.type === "approval") {
    const asks = node.capture_response === true ? " · asks for a value" : "";
    add(`You approve or reject${asks}`, `You approve or reject${asks}`);
  }
  if (node.type === "loop_group") {
    const rounds = `at most ${text(node.max_iterations, "1")} rounds · ${String(inner)} ${inner === 1 ? "step" : "steps"}`;
    add(rounds, rounds);
  }
  return {
    title,
    detail: parts.length > 0 ? interleave(parts) : null,
    detailText: words.join(" · "),
  };
}

function interleave(parts: ReactNode[]): ReactNode {
  return parts.flatMap((part, index) =>
    index === 0
      ? [part]
      : [
          <span key={`dot-${String(index)}`} className="st-dot" aria-hidden>
            ·
          </span>,
          part,
        ],
  );
}

function countSteps(items: readonly Item[]): number {
  return items.reduce((sum, item) => {
    if (item.kind === "block") return sum + 1;
    if (item.kind === "repeat") return sum + 1 + countSteps(item.body);
    if (item.kind === "if") return sum + countSteps(item.then) + countSteps(item.otherwise);
    return sum + item.lanes.reduce((n, lane) => n + countSteps(lane), 0);
  }, 0);
}

const EFFECT_SPOKEN: Readonly<Record<string, string>> = {
  read: "Reads only",
  write: "Changes data",
  destroy: "Deletes data",
};

const DECISION: Readonly<Record<string, string>> = { ask: "Asks you", deny: "Denied" };

interface Status {
  icon: Parameters<typeof Icon>[0]["name"];
  label: string;
  tone: string;
  title: string;
}

function statusOf(
  problems: readonly BuilderProblem[],
  plan: ScenarioPlanRow | null,
): Status | null {
  const error = problems.find((problem) => problem.severity === "error");
  if (error) return { icon: "circle-x", label: "Problem", tone: "failed", title: error.message };
  if (plan && plan.decision !== "allow") {
    return {
      icon: plan.decision === "ask" ? "hand" : "octagon-x",
      label: DECISION[plan.decision] ?? plan.decision,
      tone: plan.decision === "ask" ? "waiting" : "failed",
      title: plan.reason ?? plan.plan,
    };
  }
  return null;
}

/** The ids of the rows in reading order (for j / k). */
function rowIds(items: readonly Item[]): string[] {
  return items.flatMap((item) => {
    const id = itemId(item);
    if (item.kind === "block") return [id];
    if (item.kind === "repeat") return [id, ...rowIds(item.body)];
    if (item.kind === "if") return [id, ...rowIds(item.then), ...rowIds(item.otherwise)];
    return [id, ...item.lanes.flatMap(rowIds)];
  });
}

export function StepList(props: StepListProps) {
  const {
    scenarioName,
    items,
    numbers,
    selected,
    actionOf,
    problemsOf,
    planOf,
    planStale,
    start,
    onStart,
    onSelect,
    onInsert,
    onMove,
    onRowMenu,
    usesVariable,
    variable,
    suggested,
    readOnly = false,
    loose,
    onOpenYaml,
    footer,
    empty,
    externalTarget = null,
    scrollRef,
  } = props;
  const ownRef = useRef<HTMLDivElement>(null);
  const listRef = scrollRef ?? ownRef;
  const [focused, setFocused] = useState<string | null>(null);
  const [folded, setFolded] = useState<ReadonlySet<string>>(() => new Set());
  const [dragging, setDragging] = useState<{ id: string; target: InsertTarget | null } | null>(
    null,
  );
  const order = ["__start__", ...rowIds(items)];
  const current = focused && order.includes(focused) ? focused : (selected ?? "__start__");

  const focusRow = (id: string) => {
    setFocused(id);
    listRef.current?.querySelector<HTMLElement>(`[data-row="${CSS.escape(id)}"]`)?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const id = target.dataset.row;
    if (!id) return;
    const at = order.indexOf(id);
    const go = (to: number) => {
      const next = order[Math.max(0, Math.min(order.length - 1, to))];
      if (next) focusRow(next);
    };
    if (event.altKey) return; // Alt ↑/↓ moves the step: the builder's keys.
    switch (event.key) {
      case "ArrowDown":
      case "j":
        event.preventDefault();
        go(at + 1);
        break;
      case "ArrowUp":
      case "k":
        event.preventDefault();
        go(at - 1);
        break;
      case "Home":
        event.preventDefault();
        go(0);
        break;
      case "End":
        event.preventDefault();
        go(order.length - 1);
        break;
      case "Enter":
      case "o":
        event.preventDefault();
        if (id === "__start__") onStart();
        else onSelect(id);
        break;
      case "ArrowLeft":
      case "ArrowRight": {
        const isGroup = target.getAttribute("aria-expanded") !== null;
        if (!isGroup) break;
        event.preventDefault();
        const next = new Set(folded);
        if (event.key === "ArrowLeft") next.add(id);
        else next.delete(id);
        setFolded(next);
        break;
      }
      case "a":
        if (readOnly || id === "__start__") break;
        event.preventDefault();
        target
          .closest<HTMLElement>(".st-item")
          ?.querySelector<HTMLElement>(":scope > .st-gap button")
          ?.click();
        break;
      case "F10":
        if (!event.shiftKey || id === "__start__") break;
        event.preventDefault();
        onRowMenu(id, target.getBoundingClientRect());
        break;
      case "ContextMenu":
        if (id === "__start__") break;
        event.preventDefault();
        onRowMenu(id, target.getBoundingClientRect());
        break;
    }
  };

  // Dragging a row by its handle: the gap nearest the pointer is where it lands.
  const startDrag = (event: PointerEvent<HTMLElement>, id: string) => {
    if (readOnly || event.button !== 0) return;
    event.preventDefault();
    const origin = { x: event.clientX, y: event.clientY };
    let moved = false;
    let target: InsertTarget | null = null;
    const nearest = (y: number): InsertTarget | null => nearestGap(listRef.current, y, id);
    const move = (moving: globalThis.PointerEvent) => {
      if (!moved && Math.hypot(moving.clientX - origin.x, moving.clientY - origin.y) < 4) return;
      moved = true;
      target = nearest(moving.clientY);
      setDragging({ id, target });
      scrollNear(listRef.current, moving.clientY);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDragging(null);
      if (moved && target) onMove(id, target);
      else if (!moved) onRowMenu(id, (event.target as HTMLElement).getBoundingClientRect());
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const sameTarget = (a: InsertTarget | null, b: InsertTarget) =>
    a !== null && a.index === b.index && JSON.stringify(a.slot) === JSON.stringify(b.slot);

  const gap = (slot: Slot, index: number, after: string | null) => {
    const at: InsertTarget = { slot, index };
    const label = after
      ? `Add a step after step ${numbers.get(after) ?? after}`
      : "Add a step here";
    return (
      <div
        className="st-gap"
        data-gap={JSON.stringify(at)}
        data-drop={
          (dragging && sameTarget(dragging.target, at)) || sameTarget(externalTarget, at)
            ? "on"
            : undefined
        }
      >
        {!readOnly && !dragging && !externalTarget && (
          <button
            type="button"
            className="st-gap-add"
            aria-label={label}
            title={label}
            tabIndex={-1}
            onClick={(event) => {
              onInsert(at, event.currentTarget.getBoundingClientRect(), label);
            }}
          >
            <Icon name="plus" size="sm" />
          </button>
        )}
      </div>
    );
  };

  const row = (
    id: string,
    level: number,
    look: { icon: Parameters<typeof Icon>[0]["name"]; tint: string; soft: string },
    kind: string,
    title: ReactNode,
    titleText: string,
    detail: ReactNode,
    detailText: string,
    right: ReactNode,
    group: boolean,
    spoken = "",
  ) => {
    const number = numbers.get(id) ?? "";
    const isSelected = selected === id;
    return (
      // The tree handles the keys of its rows (roving focus: j / k, Enter, Alt ↑ / ↓).
      // eslint-disable-next-line jsx-a11y/click-events-have-key-events
      <div
        role="treeitem"
        tabIndex={current === id ? 0 : -1}
        data-row={id}
        aria-level={level}
        aria-selected={isSelected}
        aria-expanded={group ? !folded.has(id) : undefined}
        aria-label={`Step ${number}, ${kindName(kind)}: ${titleText}.${spoken}`}
        className="st-row"
        data-selected={isSelected ? "true" : undefined}
        data-suggested={suggested?.has(id) ? "true" : undefined}
        data-problem={problemsOf(id).some((p) => p.severity === "error") ? "true" : undefined}
        data-dragging={dragging?.id === id ? "true" : undefined}
        title={detailText ? `${titleText}\n${detailText}` : titleText}
        onClick={() => {
          setFocused(id);
          onSelect(id);
        }}
        onFocus={() => {
          setFocused(id);
        }}
        onContextMenu={(event) => {
          if (readOnly) return;
          event.preventDefault();
          onRowMenu(id, event.currentTarget.getBoundingClientRect());
        }}
      >
        {!readOnly && (
          // A drag handle: the row menu (Move up / down) is its keyboard path.
          // eslint-disable-next-line jsx-a11y/click-events-have-key-events
          <span
            className="st-handle"
            role="button"
            tabIndex={-1}
            aria-label={`Move step ${number}`}
            title="Drag to move · click for Move up / down"
            onPointerDown={(event) => {
              event.stopPropagation();
              startDrag(event, id);
            }}
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            <Icon name="grip-vertical" size="sm" />
          </span>
        )}
        <span className="st-num">{number}</span>
        <span
          className="st-tile"
          style={{ ["--tile" as string]: look.tint, ["--tile-soft" as string]: look.soft }}
          aria-hidden
        >
          <Icon name={look.icon} size="sm" />
        </span>
        <span className="st-lines">
          <span className="st-title">{title}</span>
          {detail && <span className="st-detail">{detail}</span>}
        </span>
        <span className="st-right">
          {suggested?.has(id) && <span className="st-chip">Suggested</span>}
          {right}
        </span>
      </div>
    );
  };

  const blockRow = (node: BuilderNode, level: number, inner: number, group: boolean) => {
    const action = actionOf(node);
    const lines = nodeLines(node, action, inner);
    if (action?.description && !lines.title.startsWith(action.description.slice(0, 20))) {
      lines.detailText = `${action.description}\n${lines.detailText}`;
    }
    const plan = planOf(node.id);
    const status = statusOf(problemsOf(node.id), plan);
    const using = variable && usesVariable?.(node);
    const right = (
      <>
        {using ? (
          <span className="st-uses">uses {variable}</span>
        ) : (
          (node.type === "action" || node.type === "expect") &&
          action && <EffectBadge effect={action.effect} words />
        )}
        {status && (
          <span className="st-status" data-tone={status.tone} title={status.title}>
            <Icon name={status.icon} size="sm" /> {status.label}
          </span>
        )}
      </>
    );
    const detail = plan?.plan ? (
      <span className={planStale ? "st-plan st-plan-stale" : "st-plan"}>
        <Icon name={planStale ? "clock" : "scan-eye"} size="sm" />{" "}
        {planStale ? "Planned before your changes · " : ""}
        {plan.plan}
      </span>
    ) : (
      lines.detail
    );
    return row(
      node.id,
      level,
      kindLook(node.type),
      node.type,
      <TokenText value={lines.title} />,
      lines.title,
      detail,
      lines.detailText,
      right,
      group,
      [
        (node.type === "action" || node.type === "expect") && action?.effect
          ? ` ${EFFECT_SPOKEN[action.effect] ?? action.effect}.`
          : "",
        status ? ` ${status.label}.` : "",
      ].join(""),
    );
  };

  const list = (list: readonly Item[], slot: Slot, level: number): ReactNode => {
    if (list.length === 0 && slot.in !== "main") {
      const at: InsertTarget = { slot, index: 0 };
      return (
        <div className="st-gap st-empty" data-gap={JSON.stringify(at)}>
          {readOnly ? (
            <span>Empty.</span>
          ) : (
            <button
              type="button"
              className="st-empty-add"
              onClick={(event) => {
                onInsert(at, event.currentTarget.getBoundingClientRect(), "Add a step here");
              }}
            >
              <Icon name="plus" size="sm" /> Empty. Add a step here.
            </button>
          )}
        </div>
      );
    }
    return (
      <>
        {slot.in !== "main" && gap(slot, 0, null)}
        {list.map((item, index) => (
          <div key={itemId(item)} className="st-item" data-item={itemId(item)}>
            {itemView(item, level)}
            {gap(slot, index + 1, itemId(item))}
          </div>
        ))}
      </>
    );
  };

  const itemView = (item: Item, level: number): ReactNode => {
    if (item.kind === "block") return blockRow(item.node, level, 0, false);
    const id = itemId(item);
    const open = !folded.has(id);
    if (item.kind === "repeat") {
      return (
        <>
          {blockRow(item.node, level, countSteps(item.body), true)}
          {open && (
            <div role="group" className="st-group">
              {list(item.body, { in: "body", owner: id }, level + 1)}
            </div>
          )}
        </>
      );
    }
    if (item.kind === "if") {
      const condition = conditionWords(item.condition);
      return (
        <>
          {row(
            id,
            level,
            kindLook("branch"),
            "if",
            `If ${condition || "…"}`,
            `If ${condition}`,
            open ? null : `${String(countSteps(item.then) + countSteps(item.otherwise))} steps`,
            "",
            null,
            true,
          )}
          {open && (
            <div role="group" className="st-group">
              <span className="st-path">If yes</span>
              {list(item.then, { in: "then", owner: id }, level + 1)}
              <span className="st-path">Otherwise</span>
              {list(item.otherwise, { in: "otherwise", owner: id }, level + 1)}
            </div>
          )}
        </>
      );
    }
    return (
      <>
        {row(
          id,
          level,
          kindLook("parallel"),
          "parallel",
          `Do ${String(item.lanes.length)} paths at the same time`,
          `Do ${String(item.lanes.length)} paths at the same time`,
          "continues when every path ends",
          "continues when every path ends",
          null,
          true,
        )}
        {open && (
          <div role="group" className="st-group">
            {item.lanes.map((lane, index) => (
              <div key={index}>
                <span className="st-path">Path {index + 1}</span>
                {list(lane, { in: "lane", owner: id, lane: index }, level + 1)}
              </div>
            ))}
          </div>
        )}
      </>
    );
  };

  const asks = start.asks.length > 0 ? `Asks for ${start.asks.join(", ")}` : "Asks for nothing";
  return (
    <div className="st-scroll" ref={listRef}>
      <div className="st-column">
        {footer}
        {/* eslint-disable-next-line jsx-a11y/interactive-supports-focus -- the rows hold focus */}
        <div
          role="tree"
          aria-label={`Steps of ${scenarioName}`}
          className="st-tree"
          onKeyDown={onKeyDown}
        >
          <div className="st-item">
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events -- the tree's keys */}
            <div
              role="treeitem"
              aria-level={1}
              aria-selected={start.selected}
              tabIndex={current === "__start__" ? 0 : -1}
              data-row="__start__"
              className="st-row st-start"
              data-selected={start.selected ? "true" : undefined}
              onClick={onStart}
              onFocus={() => {
                setFocused("__start__");
              }}
            >
              <span aria-hidden />
              <span className="st-num" />
              <span
                className="st-tile"
                style={{
                  ["--tile" as string]: "var(--kind-control)",
                  ["--tile-soft" as string]: "var(--kind-control-soft)",
                }}
                aria-hidden
              >
                <Icon name="flag" size="sm" />
              </span>
              <span className="st-lines">
                <span className="st-title">
                  {start.environment
                    ? `Starts in ${start.environment}`
                    : "When the scenario starts"}
                </span>
                <span className="st-detail">{asks}</span>
              </span>
            </div>
            {gap({ in: "main" }, 0, null)}
          </div>
          {list(items, { in: "main" }, 1)}
        </div>
        {items.length === 0 && empty}
        {!readOnly && (
          <div className="st-end">
            <Button
              variant="ghost"
              icon="plus"
              onClick={(event) => {
                onInsert(
                  { slot: { in: "main" }, index: items.length },
                  event.currentTarget.getBoundingClientRect(),
                  "Add step",
                );
              }}
            >
              Add step
            </Button>
          </div>
        )}
        {loose.length > 0 && (
          <section className="st-loose" aria-label="Steps not in the order">
            <span className="ah-overline">Not in the order ({loose.length})</span>
            <span className="ah-small ah-muted">
              These steps connect in a way the list cannot show. Edit them in YAML.
            </span>
            {loose.map((node) => (
              <div key={node.id} className="st-item">
                {blockRow(node, 1, 0, false)}
              </div>
            ))}
            <span>
              <IconButton icon="file-text" label="Open YAML" onClick={onOpenYaml} />
            </span>
          </section>
        )}
      </div>
    </div>
  );
}
