import { useRef, useState, type ReactNode } from "react";

import { Icon, type IconName } from "../../../components";
import { useNodeBoxes, type NodeBox } from "../../../lib/nodeBoxes";
import { EffectBadge } from "../parts";
import type { ScenarioAction, ScenarioStep } from "../queries";
import { KindTile, TokenText } from "./CardParts";
import {
  conditionWords,
  dependsOn,
  edgesOf,
  layersOf,
  shown,
  type BlockKind,
  type BuilderNode,
  type Json,
} from "./model";
import { nodeLines } from "./rowLines";
import type { BuilderProblem } from "./useScenarioDraft";

/* The flow canvas: the scenario's blocks laid out top to bottom in the engine's layers (a block
 * one layer below the last block it waits for), branches side by side, a repeat as a frame
 * holding its own blocks, and an arrow for each `depends_on`. Every block has a "+" under it
 * that opens the add menu; nothing is placed by hand, so the YAML order is the drawn order. */

export const KIND_LOOK: Readonly<
  Record<string, { label: string; icon: IconName; tint: string; soft: string }>
> = {
  action: {
    label: "Run an action",
    icon: "circle-play",
    tint: "var(--kind-do)",
    soft: "var(--kind-do-soft)",
  },
  include: {
    label: "Run a scenario",
    icon: "layers",
    tint: "var(--kind-do)",
    soft: "var(--kind-do-soft)",
  },
  expect: {
    label: "Wait until",
    icon: "timer",
    tint: "var(--kind-check)",
    soft: "var(--kind-check-soft)",
  },
  wait: {
    label: "Pause",
    icon: "hourglass",
    tint: "var(--text-muted)",
    soft: "var(--surface-sunken)",
  },
  loop_group: {
    label: "Repeat",
    icon: "refresh-cw",
    tint: "var(--kind-control)",
    soft: "var(--kind-control-soft)",
  },
  branch: {
    label: "If",
    icon: "split",
    tint: "var(--kind-control)",
    soft: "var(--kind-control-soft)",
  },
  parallel: {
    label: "At the same time",
    icon: "git-branch",
    tint: "var(--kind-control)",
    soft: "var(--kind-control-soft)",
  },
  approval: {
    label: "Ask me",
    icon: "stamp",
    tint: "var(--kind-control)",
    soft: "var(--kind-control-soft)",
  },
  stage: {
    label: "Stage",
    icon: "milestone",
    tint: "var(--kind-control)",
    soft: "var(--kind-control-soft)",
  },
};

export function kindLook(type: string) {
  return (
    KIND_LOOK[type] ?? {
      label: type,
      icon: "circle-dashed" as IconName,
      tint: "var(--text-muted)",
      soft: "var(--surface-sunken)",
    }
  );
}

/** A node as the storyline's words read it (`story.ts` takes the API's step view). */
export function asStep(node: BuilderNode): ScenarioStep {
  const text = (key: string) => {
    const value = node[key];
    return typeof value === "string" ? value : null;
  };
  const record = (key: string) => {
    const value = node[key];
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, Json>)
      : {};
  };
  const retry = record("retry");
  return {
    id: node.id,
    type: node.type,
    action: text("action"),
    depends_on: dependsOn(node),
    description: text("description"),
    with: record("with"),
    capture: Object.fromEntries(
      Object.entries(record("capture")).map(([key, value]) => [key, shown(value)]),
    ),
    every: text("every"),
    timeout: text("timeout"),
    until_when: text("until_when"),
    retry:
      typeof retry.max_attempts === "number"
        ? {
            max_attempts: retry.max_attempts,
            delay: typeof retry.delay === "string" ? retry.delay : "2s",
            on_error: typeof retry.on_error === "string" ? retry.on_error : "transient",
          }
        : null,
  };
}

/** A block on the graph, as the Blocks list says it (`rowLines`): its number, kind tile and
 * title, the sentence of what it does, a quiet technical line that never runs past the card,
 * then its effect and, while a scenario run is shown, its state in it. */
export function FlowBlock({
  node,
  action,
  problems,
  selected,
  status,
  number,
  onSelect,
}: {
  node: BuilderNode;
  action: ScenarioAction | null;
  problems: readonly BuilderProblem[];
  selected: boolean;
  status?: ReactNode;
  /** The block's number, as the Blocks list numbers it (`1.2`, `2.1.then.1`). */
  number?: string | undefined;
  onSelect: (id: string) => void;
}) {
  const look = kindLook(node.type);
  const inner = Array.isArray(node.nodes) ? node.nodes.length : 0;
  const lines = nodeLines(node, action, inner);
  const errors = problems.filter((problem) => problem.severity === "error");
  const when = typeof node.when === "string" && node.when !== "" ? node.when : null;
  const calls = node.type === "action" || node.type === "expect";
  return (
    <button
      type="button"
      data-node-id={node.id}
      className="sg-card"
      data-selected={selected || undefined}
      data-invalid={errors.length > 0 || undefined}
      aria-pressed={selected}
      aria-label={`${number ? `Block ${number}, ` : ""}${look.label}: ${lines.title}`}
      title={lines.detailText ? `${lines.title}\n${lines.detailText}` : lines.title}
      onClick={() => {
        onSelect(node.id);
      }}
    >
      {when && (
        <span className="sg-when">
          <Icon name="split" size="sm" /> Only if {conditionWords(when)}
        </span>
      )}
      <span className="sg-head">
        {number && <span className="sg-num">{number}</span>}
        <KindTile look={look} />
        <span className="sg-title">
          <TokenText value={lines.title} />
        </span>
      </span>
      {lines.detail && <span className="sg-sentence">{lines.detail}</span>}
      {lines.tech && <span className="sg-tech">{lines.tech}</span>}
      <span className="sg-foot">
        {calls && action && <EffectBadge effect={action.effect} words />}
        {action?.draft && (
          <span className="sg-quiet" title="Draft: needs acceptance">
            <Icon name="pencil" size="sm" /> Draft
          </span>
        )}
        {errors.length > 0 && (
          <span className="sb-errors" title={errors.map((problem) => problem.message).join("\n")}>
            <Icon name="circle-x" size="sm" /> {errors.length}{" "}
            {errors.length === 1 ? "problem" : "problems"}
          </span>
        )}
        <span className="ah-grow" />
        {status}
      </span>
    </button>
  );
}

export interface AddChoice {
  kind: BlockKind | "branch" | "parallel";
  label: string;
  icon: IconName;
}

export const ADD_CHOICES: readonly AddChoice[] = [
  { kind: "action", label: "Script", icon: "circle-play" },
  { kind: "expect", label: "Check", icon: "timer" },
  { kind: "approval", label: "Manual step", icon: "stamp" },
  { kind: "wait", label: "Pause", icon: "hourglass" },
  { kind: "loop_group", label: "Repeat", icon: "refresh-cw" },
  { kind: "include", label: "Sub-flow", icon: "layers" },
  { kind: "branch", label: "Branch (if / otherwise)", icon: "split" },
];

function AddPoint({
  label,
  onAdd,
  withBranch,
}: {
  label: string;
  onAdd: (choice: AddChoice) => void;
  withBranch: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="sb-add">
      <button
        type="button"
        className="sb-plus"
        aria-label={label}
        aria-expanded={open}
        title={label}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <Icon name="plus" size="sm" />
      </button>
      {open && (
        <div className="sb-add-menu" role="menu" aria-label={label}>
          {ADD_CHOICES.filter((choice) => withBranch || choice.kind !== "branch").map((choice) => (
            <button
              key={choice.kind}
              type="button"
              role="menuitem"
              style={{ ["--kind" as string]: kindLook(choice.kind).tint }}
              onClick={() => {
                setOpen(false);
                onAdd(choice);
              }}
            >
              <span className="sb-kind" aria-hidden>
                <Icon name={choice.icon} size="sm" />
              </span>
              {choice.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function downPath(a: NodeBox | undefined, b: NodeBox | undefined): string {
  if (!a || !b) return "";
  const x1 = (a.left + a.right) / 2;
  const y1 = a.bottom;
  const x2 = (b.left + b.right) / 2;
  const y2 = b.top;
  const my = (y1 + y2) / 2;
  return `M ${String(x1)} ${String(y1)} C ${String(x1)} ${String(my)}, ${String(x2)} ${String(my)}, ${String(x2)} ${String(y2)}`;
}

export interface CanvasProps {
  nodes: readonly BuilderNode[];
  actionOf: (node: BuilderNode) => ScenarioAction | null;
  problemsOf: (id: string) => readonly BuilderProblem[];
  selected: string | null;
  statusOf?: (id: string) => ReactNode;
  /** A block's number, as the Blocks list numbers it. */
  numberOf?: (id: string) => string | undefined;
  onSelect: (id: string | null) => void;
  onAdd: (choice: AddChoice, after: string | null, group: string | null) => void;
  readOnly?: boolean;
}

function Layers({
  nodes,
  group,
  props,
}: {
  nodes: readonly BuilderNode[];
  group: string | null;
  props: CanvasProps;
}) {
  const layers = layersOf(nodes);
  return (
    <div className="sb-layers">
      {layers.map((layer, index) => (
        <div key={index} className="sb-layer">
          {layer.map((node) => (
            <div key={node.id} className="sb-slot">
              {node.type === "loop_group" ? (
                <div
                  className="sb-frame"
                  data-node-id={node.id}
                  data-selected={props.selected === node.id || undefined}
                  style={{ ["--kind" as string]: kindLook(node.type).tint }}
                >
                  <FlowBlock
                    node={node}
                    action={null}
                    problems={props.problemsOf(node.id)}
                    selected={props.selected === node.id}
                    status={props.statusOf?.(node.id)}
                    number={props.numberOf?.(node.id)}
                    onSelect={props.onSelect}
                  />
                  <div className="sb-frame-body">
                    {Array.isArray(node.nodes) && node.nodes.length > 0 ? (
                      <Layers nodes={node.nodes as BuilderNode[]} group={node.id} props={props} />
                    ) : (
                      <span className="ah-small ah-subtle">Add the blocks each round runs.</span>
                    )}
                    {!props.readOnly && (
                      <AddPoint
                        label={`Add a block inside ${node.id}`}
                        withBranch={false}
                        onAdd={(choice) => {
                          props.onAdd(choice, null, node.id);
                        }}
                      />
                    )}
                  </div>
                </div>
              ) : (
                <FlowBlock
                  node={node}
                  action={props.actionOf(node)}
                  problems={props.problemsOf(node.id)}
                  selected={props.selected === node.id}
                  status={props.statusOf?.(node.id)}
                  number={props.numberOf?.(node.id)}
                  onSelect={props.onSelect}
                />
              )}
              {!props.readOnly && (
                <AddPoint
                  label={`Add a block after ${node.id}`}
                  withBranch
                  onAdd={(choice) => {
                    props.onAdd(choice, node.id, group);
                  }}
                />
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function FlowCanvas(props: CanvasProps) {
  const root = useRef<HTMLDivElement>(null);
  const all = flatten(props.nodes);
  const edges = all.flatMap((list) => edgesOf(list));
  const shape = JSON.stringify([
    all.map((list) => list.map((node) => [node.id, node.when ?? null, node.type])),
    props.selected,
  ]);
  const { boxes, size } = useNodeBoxes(root, shape);
  return (
    <div ref={root} className="sb-canvas">
      <svg className="sb-edges" width={size.width} height={size.height} aria-hidden>
        <defs>
          <marker
            id="sb-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--border-strong)" />
          </marker>
        </defs>
        {edges.map(([from, to]) => (
          <path
            key={`${from}->${to}`}
            d={downPath(boxes[from], boxes[to])}
            fill="none"
            stroke="var(--border-strong)"
            strokeWidth={1.5}
            markerEnd="url(#sb-arrow)"
          />
        ))}
      </svg>
      <div className="sb-start">
        <Icon name="flag" size="sm" /> Start
      </div>
      {props.nodes.length === 0 ? (
        <div className="sb-empty">
          <span>Start with a first step.</span>
          {!props.readOnly && (
            <AddPoint
              label="Add the first block"
              withBranch={false}
              onAdd={(choice) => {
                props.onAdd(choice, null, null);
              }}
            />
          )}
        </div>
      ) : (
        <Layers nodes={props.nodes} group={null} props={props} />
      )}
      {props.nodes.length > 0 && (
        <div className="sb-end">
          <Icon name="flag" size="sm" /> End
        </div>
      )}
    </div>
  );
}

function flatten(nodes: readonly BuilderNode[]): BuilderNode[][] {
  return [
    [...nodes],
    ...nodes.flatMap((node) =>
      Array.isArray(node.nodes) ? flatten(node.nodes as BuilderNode[]) : [],
    ),
  ];
}
