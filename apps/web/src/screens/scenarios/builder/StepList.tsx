import "./steps.css";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { Button, Icon, IconButton } from "../../../components";
import { EffectBadge, PolicyBadge } from "../parts";
import type { ScenarioAction, ScenarioPlanRow } from "../queries";
import { pace } from "../story";
import { TokenText, ValueToken, cardTitle, firstSentence, tokenOf } from "./CardParts";
import { kindLook } from "./FlowCanvas";
import { OpenStep, type StepSources } from "./OpenStep";
import { conditionWords, shown, text, type BuilderNode, type Json } from "./model";
import { itemId, listsOf, type Item, type Slot } from "./program";
import type { BuilderProblem } from "./useScenarioDraft";

/* The step list (scenario builder v6): the scenario read top to bottom like a runbook. Each step
 * is a numbered row of two lines (what it does, then its action and the values it sets itself);
 * Repeat, If and At the same time are indented groups. Order is the only thing a position means,
 * so a step always sits in the list: it moves by its handle, by Alt ↑/↓, or by the row menu, and
 * a "+" in each gap adds one there. Selecting a row opens it in the editor on the right. A
 * scenario written as blocks reads as its stages: a header row per stage (selected, it opens the
 * stage's editor; it moves and is removed as a step is), its steps indented under it, numbered by
 * their block address, and a "+" between stages adds one. */

export interface InsertTarget {
  slot: Slot;
  index: number;
}

/** What a gap takes: a step (in any list of steps) or a stage (between stages). */
export type GapKind = "step" | "stage";

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
  /** A scenario written as blocks: `items` are its stages; a "+" between them adds one. */
  onInsertStage?: ((index: number) => void) | undefined;
  onOpenYaml: () => void;
  footer?: ReactNode;
  /** Shown under the list while it holds no step (start from a shape, describe it). */
  empty?: ReactNode;
  /** A block dragged from the palette: the gap it would land in. */
  externalTarget?: InsertTarget | null;
  /** The list's scrolling element, for a drag from the palette. */
  scrollRef?: RefObject<HTMLDivElement>;
  /** The state of a row in the scenario run shown on the blocks (null: none shown). */
  runStateOf?: ((id: string) => ReactNode) | undefined;
  /** The values a row kept in the scenario run shown, as `name = value` words. */
  keptOf?: ((id: string) => readonly string[]) | undefined;
  /** The row the shown scenario run is at now. */
  current?: string | null | undefined;
  /** Breakpoints before blocks (a scenario written as blocks, off production). */
  breakpoints?:
    | { on: (id: string) => boolean; toggle: (id: string) => void; busy?: boolean }
    | null
    | undefined;
  /** Edits made on the row itself: its sentence, a value it sets, its timing. */
  onEditNode?: ((id: string, node: BuilderNode) => void) | undefined;
  onDuplicate?: ((id: string) => void) | undefined;
  onDelete?: ((id: string) => void) | undefined;
  /** Where a step's values come from (environment, scenario variables, kept values). */
  sources?: StepSources | null | undefined;
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
  stage: "Stage",
};

/** The gap of the list nearest the pointer's height (null when none is within 80 px); `skip`
 * leaves out the gaps inside the step being moved, and only gaps that take `kind` count (a step
 * never lands between stages, a stage never inside one). Shared by a move and a drag from the
 * palette. */
export function nearestGap(
  root: HTMLElement | null,
  y: number,
  skip?: string,
  kind: GapKind = "step",
): InsertTarget | null {
  const gaps = root?.querySelectorAll<HTMLElement>("[data-gap]") ?? [];
  let best: { at: InsertTarget; distance: number } | null = null;
  for (const gap of gaps) {
    if (skip && gap.closest(`[data-item="${CSS.escape(skip)}"]`)) continue;
    if ((gap.dataset.gapKind ?? "step") !== kind) continue;
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

/** A value written on the row can be edited there: a plain string, number or boolean. */
function editableValue(value: Json): boolean {
  if (typeof value === "number" || typeof value === "boolean") return true;
  if (typeof value !== "string") return false;
  const trimmed = value.trim();
  return !/^[[{]/.test(trimmed) && !trimmed.includes("\n") && !trimmed.includes("$");
}

/** What was typed, as the value's own type. */
function typedAs(previous: Json, typed: string): Json {
  if (typeof previous === "number") {
    const n = Number(typed);
    return typed.trim() !== "" && Number.isFinite(n) ? n : typed;
  }
  if (typeof previous === "boolean") {
    if (typed.trim() === "true") return true;
    if (typed.trim() === "false") return false;
  }
  return typed;
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
): { title: string; detail: ReactNode; tech: ReactNode; detailText: string } {
  const named = typeof node.description === "string" && node.description.trim() !== "";
  const title = cardTitle(node, action);
  const parts: ReactNode[] = [];
  const words: string[] = [];
  const add = (part: ReactNode, word: string) => {
    parts.push(<span key={parts.length}>{part}</span>);
    words.push(word);
  };
  // Line 2 says what the step does, in words; the action and the values it sets go on a quieter
  // technical line under it (and open as chips to edit while the row is selected).
  const ref = text(node.action);
  if (node.type === "action" && action?.description) {
    const said = firstSentence(action.description).replace(/\.$/, "");
    if (said !== title.replace(/\.$/, "")) add(said, said);
  }
  if (node.type === "expect") {
    if (named && text(node.until_when)) {
      const words_ = `until ${conditionWords(text(node.until_when))}`;
      add(words_, words_);
    }
    const every = text(node.every);
    const timeout = text(node.timeout);
    if (every && timeout) {
      const timing = `checks every ${pace(every)}, up to ${pace(timeout)}`;
      add(timing, timing);
    }
  }
  const techParts: ReactNode[] = [];
  const techWords: string[] = [];
  if ((node.type === "action" || node.type === "expect") && ref) {
    techParts.push(
      <span key="ref" className="st-mono">
        {action?.name ?? ref}
      </span>,
    );
    techWords.push(ref);
  }
  if (node.type === "action" || node.type === "expect" || node.type === "include") {
    let more = 0;
    for (const [name, value] of ownValues(node, action)) {
      // A long or structured value (a JSON body) is the open row's: here it is only counted.
      if (!editableValue(value) || compact(value).length > 40) {
        more += 1;
        techWords.push(`${name} ${compact(value)}`);
        continue;
      }
      techParts.push(
        <span key={name}>
          <span className="st-key">{name}</span> <Value value={value} />
        </span>,
      );
      techWords.push(`${name} ${compact(value)}`);
    }
    if (more > 0) {
      techParts.push(
        <span key="more" className="st-key">
          +{more} {more === 1 ? "value" : "values"}
        </span>,
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
    tech: techParts.length > 0 ? interleave(techParts) : null,
    detailText: [...words, ...techWords].join(" · "),
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
    return sum + listsOf(item).reduce((n, list) => n + countSteps(list), 0);
  }, 0);
}

function plural(count: number, one: string): string {
  return `${String(count)} ${count === 1 ? one : `${one}s`}`;
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
  /** A plan's decision, shown as the run panel shows it (an ask is neutral until it waits). */
  decision?: string;
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
      tone: plan.decision === "ask" ? "quiet" : "failed",
      title: plan.reason ?? plan.plan,
      decision: plan.decision,
    };
  }
  return null;
}

/** The ids of the rows in reading order (for j / k). */
function rowIds(items: readonly Item[]): string[] {
  return items.flatMap((item) => [itemId(item), ...listsOf(item).flatMap(rowIds)]);
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
    onInsertStage,
    onOpenYaml,
    footer,
    empty,
    externalTarget = null,
    scrollRef,
  } = props;
  const stages = items.filter((item) => item.kind === "stage");
  const tree = onInsertStage !== undefined;
  const ownRef = useRef<HTMLDivElement>(null);
  const listRef = scrollRef ?? ownRef;
  const [focused, setFocused] = useState<string | null>(null);
  const [folded, setFolded] = useState<ReadonlySet<string>>(() => new Set());
  const [dragging, setDragging] = useState<{ id: string; target: InsertTarget | null } | null>(
    null,
  );
  // Edited on the row: its sentence (`title`), one value it sets (`with:<name>`) or a timing.
  const [editing, setEditing] = useState<{ id: string; field: string } | null>(null);
  // The row an edit on it ended on: focus goes back to it once the field is gone.
  // A new object each time, so the same row can be focused again.
  const [refocus, setRefocus] = useState<{ id: string } | null>(null);
  useEffect(() => {
    if (refocus === null) return;
    listRef.current?.querySelector<HTMLElement>(`[data-row="${CSS.escape(refocus.id)}"]`)?.focus();
  }, [refocus, listRef]);
  const order = ["__start__", ...rowIds(items)];
  const current = focused && order.includes(focused) ? focused : (selected ?? "__start__");

  const focusRow = (id: string) => {
    setFocused(id);
    listRef.current?.querySelector<HTMLElement>(`[data-row="${CSS.escape(id)}"]`)?.focus();
  };

  const {
    runStateOf,
    keptOf,
    current: runAt = null,
    breakpoints,
    onEditNode,
    onDuplicate,
    onDelete,
    sources = null,
  } = props;
  const nodeOfRow = (id: string): BuilderNode | null => {
    const find = (list: readonly Item[]): BuilderNode | null => {
      for (const item of list) {
        if (itemId(item) === id) {
          return item.kind === "block" || item.kind === "repeat" ? item.node : null;
        }
        for (const inner of listsOf(item)) {
          const found = find(inner);
          if (found) return found;
        }
      }
      return null;
    };
    return find(items);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const id = target.dataset.row;
    if (!id) return;
    if (event.key === "F2" && !readOnly && onEditNode && nodeOfRow(id)) {
      event.preventDefault();
      setEditing({ id, field: "title" });
      return;
    }
    if (
      event.key === "b" &&
      !event.metaKey &&
      !event.ctrlKey &&
      breakpoints &&
      id !== "__start__"
    ) {
      event.preventDefault();
      breakpoints.toggle(id);
      return;
    }
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
    const kind: GapKind = stages.some((stage) => itemId(stage) === id) ? "stage" : "step";
    const nearest = (y: number): InsertTarget | null => nearestGap(listRef.current, y, id, kind);
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
    // Between the stages of a scenario written as blocks, a gap takes a stage.
    const kind: GapKind = tree && slot.in === "main" ? "stage" : "step";
    const noun = kind === "stage" ? "stage" : "step";
    const label = after
      ? `Add a ${noun} after ${noun} ${numbers.get(after) ?? after}`
      : `Add a ${noun} here`;
    return (
      <div
        className="st-gap"
        data-gap={JSON.stringify(at)}
        data-gap-kind={kind}
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
            // The "+" is the pointer's way: a tree holds only its items, and the keys add from
            // a row ("a"), the Blocks tab and Add step / Add stage below.
            aria-hidden
            onClick={(event) => {
              if (kind === "stage") onInsertStage?.(index);
              else onInsert(at, event.currentTarget.getBoundingClientRect(), label);
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
    stage = false,
    extra: {
      news?: ReactNode;
      titleEditor?: ReactNode;
      tech?: ReactNode;
      open?: ReactNode;
    } = {},
  ) => {
    const number = numbers.get(id) ?? "";
    const isSelected = selected === id;
    const noun = stage ? "stage" : "step";
    const state = runStateOf?.(id) ?? null;
    const isCurrent = runAt === id;
    const marked = breakpoints?.on(id) ?? false;
    const quick =
      readOnly || id === "__start__" ? null : (
        <span className="st-quick" data-pinned={marked ? "true" : undefined}>
          {breakpoints && (
            <button
              type="button"
              className={marked ? "st-quick-btn st-break-on" : "st-quick-btn"}
              tabIndex={-1}
              aria-pressed={marked}
              aria-label={`Breakpoint before block ${number || id} (b)`}
              title={
                marked
                  ? `The scenario run pauses before block ${number || id}. Press to remove the breakpoint (b).`
                  : `Pause the scenario run before block ${number || id} (b).`
              }
              aria-disabled={breakpoints.busy === true || undefined}
              onClick={(event) => {
                event.stopPropagation();
                if (!breakpoints.busy) breakpoints.toggle(id);
              }}
            >
              <Icon name={marked ? "circle-dot" : "circle"} size="sm" />
            </button>
          )}
          {!stage && onEditNode && nodeOfRow(id) && (
            <button
              type="button"
              className="st-quick-btn st-quick-hover"
              tabIndex={-1}
              aria-label={`Rename ${noun} ${number} (F2)`}
              title={`Rename ${noun} ${number} (F2)`}
              onClick={(event) => {
                event.stopPropagation();
                setEditing({ id, field: "title" });
              }}
            >
              <Icon name="pencil" size="sm" />
            </button>
          )}
          {!stage && onDuplicate && (
            <button
              type="button"
              className="st-quick-btn st-quick-hover"
              tabIndex={-1}
              aria-label={`Duplicate ${noun} ${number} (⌘D)`}
              title={`Duplicate ${noun} ${number} (⌘D)`}
              onClick={(event) => {
                event.stopPropagation();
                onDuplicate(id);
              }}
            >
              <Icon name="copy" size="sm" />
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              className="st-quick-btn st-quick-hover"
              tabIndex={-1}
              aria-label={`Delete ${noun} ${number} (Delete)`}
              title={`Delete ${noun} ${number} (Delete)`}
              onClick={(event) => {
                event.stopPropagation();
                onDelete(id);
              }}
            >
              <Icon name="trash" size="sm" />
            </button>
          )}
          <button
            type="button"
            className="st-quick-btn st-quick-hover"
            tabIndex={-1}
            aria-label={`More for ${noun} ${number} (Shift F10)`}
            title={`More for ${noun} ${number} (Shift F10)`}
            onClick={(event) => {
              event.stopPropagation();
              onRowMenu(id, event.currentTarget.getBoundingClientRect());
            }}
          >
            <Icon name="ellipsis" size="sm" />
          </button>
        </span>
      );
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
        aria-label={
          stage
            ? `Stage ${number}: ${titleText}, ${detailText}.`
            : `Step ${number}, ${kindName(kind)}: ${titleText}.${spoken}`
        }
        className={stage ? "st-row st-stage" : "st-row"}
        data-selected={isSelected ? "true" : undefined}
        data-suggested={suggested?.has(id) ? "true" : undefined}
        data-problem={problemsOf(id).some((p) => p.severity === "error") ? "true" : undefined}
        data-dragging={dragging?.id === id ? "true" : undefined}
        data-current={isCurrent ? "true" : undefined}
        data-run={state !== null ? "true" : undefined}
        aria-current={isCurrent ? "step" : undefined}
        // Open, the row shows it all: no tooltip over the open part.
        title={extra.open ? undefined : detailText ? `${titleText}\n${detailText}` : titleText}
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
            aria-label={`Move ${noun} ${number}`}
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
          {extra.titleEditor ?? <span className="st-title">{title}</span>}
          {detail && <span className="st-detail">{detail}</span>}
          {extra.tech && <span className="st-tech">{extra.tech}</span>}
          {extra.news}
        </span>
        <span className="st-right">
          {suggested?.has(id) && <span className="st-chip">Suggested</span>}
          {right}
          {state !== null && <span className="st-run-state">{state}</span>}
          {quick}
        </span>
        {extra.open}
      </div>
    );
  };

  const blockRow = (
    id: string,
    node: BuilderNode,
    level: number,
    inner: number,
    group: boolean,
  ) => {
    const action = actionOf(node);
    const lines = nodeLines(node, action, inner);
    if (action?.description && !lines.title.startsWith(action.description.slice(0, 20))) {
      lines.detailText = `${action.description}\n${lines.detailText}`;
    }
    const plan = planOf(id);
    const status = statusOf(problemsOf(id), plan);
    const using = variable && usesVariable?.(node);
    const right = (
      <>
        {using ? (
          <span className="st-uses">uses {variable}</span>
        ) : (
          (node.type === "action" || node.type === "expect") &&
          action && <EffectBadge effect={action.effect} words />
        )}
        {status?.decision !== undefined ? (
          <PolicyBadge decision={status.decision} reason={null} />
        ) : (
          status && (
            <span className="st-status" data-tone={status.tone} title={status.title}>
              <Icon name={status.icon} size="sm" /> {status.label}
            </span>
          )
        )}
      </>
    );
    const kept = keptOf?.(id) ?? [];
    const news =
      plan?.plan || kept.length > 0 ? (
        <span className="st-news">
          {plan?.plan && (
            <span className={planStale ? "st-plan st-plan-stale" : "st-plan"}>
              <Icon name={planStale ? "clock" : "scan-eye"} size="sm" />{" "}
              {planStale ? "Planned before your changes · " : "Plan: "}
              {plan.plan}
            </span>
          )}
          {kept.length > 0 && (
            <span className="st-kept">
              <Icon name="bookmark" size="sm" /> Kept {kept.join(" · ")}
            </span>
          )}
        </span>
      ) : null;
    const editable = !readOnly && onEditNode !== undefined;
    const commitEdit = (next: BuilderNode) => {
      setEditing(null);
      onEditNode?.(id, next);
    };
    const field = (
      name: string,
      label: string,
      initial: string,
      write: (typed: string) => BuilderNode,
    ) => (
      <input
        key={name}
        className="ah-input st-inline-input"
        aria-label={label}
        defaultValue={initial}
        // A field opened on purpose takes focus.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        size={Math.max(8, Math.min(48, initial.length + 2))}
        onClick={(event) => {
          event.stopPropagation();
        }}
        onKeyDown={(event) => {
          event.stopPropagation();
          if (event.key === "Enter") {
            event.preventDefault();
            commitEdit(write(event.currentTarget.value));
            setRefocus({ id });
          } else if (event.key === "Escape") {
            event.preventDefault();
            setEditing(null);
            setRefocus({ id });
          }
        }}
        onBlur={(event) => {
          if (editing?.id === id && editing.field === name) {
            const typed = event.currentTarget.value;
            if (typed !== initial) commitEdit(write(typed));
            else setEditing(null);
          }
        }}
      />
    );
    const editingHere = editing?.id === id ? editing.field : null;
    const titleEditor =
      editable && editingHere === "title"
        ? field("title", `What ${numbers.get(id) ?? id} does`, lines.title, (typed) => ({
            ...node,
            description: typed.trim(),
          }))
        : undefined;
    // Selected, the row opens in place: what it does in full, the action it runs, each value it
    // sends (a JSON body indented, its references drawn as tokens), the values that come from
    // elsewhere, what it keeps. Plain values and the timing edit right there.
    const detail: ReactNode = lines.detail;
    const values =
      node.type === "action" || node.type === "expect" || node.type === "include"
        ? ownValues(node, action)
        : [];
    const isOpen = selected === id && (node.type === "action" || node.type === "expect");
    const given = record(node.with);
    const number = numbers.get(id) ?? id;
    const editor = (name: string): ReactNode => {
      if (!editable || editingHere !== name) return null;
      if (name === "timing") {
        const every = text(node.every);
        return field("timing", `How often ${number} checks`, every, (typed) => ({
          ...node,
          every: typed.trim() || every,
        }));
      }
      const key = name.slice("with:".length);
      const value = given[key];
      if (value === undefined) return null;
      return field(name, `${key} of ${number}`, compact(value), (typed) => ({
        ...node,
        with: { ...given, [key]: typedAs(value, typed) },
      }));
    };
    const open = isOpen ? (
      <OpenStep
        node={node}
        action={action}
        sources={sources}
        values={values}
        editor={editor}
        onEdit={
          editable
            ? (name) => {
                setEditing({ id, field: name });
              }
            : null
        }
        onSet={
          editable
            ? (name, value) => {
                onEditNode(id, { ...node, with: { ...given, [name]: value } });
              }
            : null
        }
      />
    ) : null;
    return row(
      id,
      level,
      kindLook(node.type),
      node.type,
      <TokenText value={lines.title} />,
      lines.title,
      // Open, the operation's header says what it does: line 2 would say it twice.
      isOpen ? null : detail,
      lines.detailText,
      right,
      group,
      [
        (node.type === "action" || node.type === "expect") && action?.effect
          ? ` ${EFFECT_SPOKEN[action.effect] ?? action.effect}.`
          : "",
        status ? ` ${status.label}.` : "",
      ].join(""),
      false,
      { news, titleEditor, tech: isOpen ? null : lines.tech, open },
    );
  };

  const list = (list: readonly Item[], slot: Slot, level: number): ReactNode => {
    if (list.length === 0 && slot.in !== "main") {
      const at: InsertTarget = { slot, index: 0 };
      const add = readOnly ? (
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
      );
      return (
        <div className="st-gap st-empty" data-gap={JSON.stringify(at)}>
          {tree ? (
            // Written as blocks, the empty list is an item of the tree, holding its button.
            <div role="treeitem" aria-level={level} aria-selected={false} aria-label="Empty">
              {add}
            </div>
          ) : (
            add
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
    const id = itemId(item);
    if (item.kind === "block") return blockRow(id, item.node, level, 0, false);
    const open = !folded.has(id);
    if (item.kind === "stage") {
      const count = plural(item.steps.length, "step");
      const number = numbers.get(id) ?? id;
      const look = kindLook("stage");
      return (
        <>
          {row(
            id,
            level,
            look,
            "stage",
            item.name || "A stage with no name",
            item.name || "A stage with no name",
            count,
            count,
            null,
            true,
            "",
            true,
          )}
          {open && (
            <div
              role="group"
              className="st-group"
              aria-label={`Stage ${number}: ${item.name || "A stage with no name"}`}
            >
              {list(item.steps, { in: "stage", owner: id }, level + 1)}
            </div>
          )}
        </>
      );
    }
    if (item.kind === "repeat") {
      return (
        <>
          {blockRow(id, item.node, level, countSteps(item.body), true)}
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
        {!readOnly && !tree && (
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
        {!readOnly && tree && (
          <div className="st-end">
            {(() => {
              const last = stages.at(-1);
              return last?.kind === "stage" ? (
                <Button
                  variant="ghost"
                  icon="plus"
                  onClick={(event) => {
                    onInsert(
                      { slot: { in: "stage", owner: last.key }, index: last.steps.length },
                      event.currentTarget.getBoundingClientRect(),
                      "Add step",
                    );
                  }}
                >
                  Add step
                </Button>
              ) : null;
            })()}
            <Button
              variant="ghost"
              icon="milestone"
              onClick={() => {
                onInsertStage(items.length);
              }}
            >
              Add stage
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
                {blockRow(node.id, node, 1, 0, false)}
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
