import { Fragment, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { cx } from "../lib/cx";
import { fmtDuration } from "../lib/format";
import { Button, IconButton, AppLink, PathText, copyText, useCopied } from "./core";
import { Icon, type IconName } from "./Icon";
import { DerivedLabel, ExpiredContent, RedactionChip } from "./status";

/* ---------- Code / command block with copy ---------- */
export interface CodeBlockProps {
  code: string;
  prompt?: string;
  label?: string | undefined;
  noCopy?: boolean | undefined;
  wrap?: boolean | undefined;
}
export function CodeBlock({ code, prompt = "$", label, noCopy, wrap }: CodeBlockProps) {
  const [copied, markCopied] = useCopied();
  return (
    <div className="ah-code" role={label ? "group" : undefined} aria-label={label}>
      {prompt && <span className="ah-code-prompt">{prompt}</span>}
      {/* A command that does not wrap scrolls sideways, so the keyboard must reach it (axe). */}
      <pre style={wrap ? { whiteSpace: "pre-wrap" } : undefined} tabIndex={wrap ? undefined : 0}>
        {code}
      </pre>
      {!noCopy && (
        <Button
          size="sm"
          variant="ghost"
          icon={copied ? "check" : "copy"}
          onClick={() => {
            copyText(code);
            markCopied();
          }}
          aria-label={copied ? "Copied" : "Copy command"}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
      )}
    </div>
  );
}

/* ---------- JSON viewer (canonical event, already redacted) ---------- */
const REDACTED = /^\[redacted: (.+)\]$/;

function jsonNodes(value: unknown, indent: number, key?: string | number): ReactNode[] {
  const pad = "  ".repeat(indent);
  const keyNodes =
    key === undefined || typeof key === "number"
      ? []
      : [
          <span key="k" className="ah-json-k">
            &quot;{key}&quot;
          </span>,
          <span key="c" className="ah-json-p">
            :{" "}
          </span>,
        ];
  if (value === null || typeof value === "number" || typeof value === "boolean") {
    return [
      pad,
      ...keyNodes,
      <span key="v" className="ah-json-n">
        {String(value)}
      </span>,
    ];
  }
  if (typeof value === "string") {
    const match = REDACTED.exec(value);
    return [
      pad,
      ...keyNodes,
      match ? (
        <RedactionChip key="v" kind={match[1] ?? "secret"} />
      ) : (
        <span key="v" className="ah-json-s">
          &quot;{value}&quot;
        </span>
      ),
    ];
  }
  if (typeof value !== "object") {
    // undefined, bigint, symbol or function: not JSON, shown by type.
    return [pad, ...keyNodes, <span key="v">{typeof value}</span>];
  }
  const isArray = Array.isArray(value);
  const entries: [string | number, unknown][] = isArray
    ? (value as unknown[]).map((item, i) => [i, item])
    : Object.entries(value);
  const out: ReactNode[] = [
    pad,
    ...keyNodes,
    <span key="o" className="ah-json-p">
      {isArray ? "[" : "{"}
    </span>,
    "\n",
  ];
  entries.forEach(([childKey, childValue], i) => {
    out.push(...jsonNodes(childValue, indent + 1, childKey));
    if (i < entries.length - 1) {
      out.push(
        <span key={`s${String(i)}`} className="ah-json-p">
          ,
        </span>,
      );
    }
    out.push("\n");
  });
  out.push(
    pad,
    <span key="x" className="ah-json-p">
      {isArray ? "]" : "}"}
    </span>,
  );
  return out;
}

export interface JsonViewerProps {
  value: unknown;
  maxHeight?: number;
}
/** Pretty JSON; `[redacted: kind]` strings render as a RedactionChip with no reveal control. */
export function JsonViewer({ value, maxHeight = 320 }: JsonViewerProps) {
  return (
    // A scrollable region must be reachable by keyboard.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <pre className="ah-json" style={{ maxHeight }} tabIndex={0}>
      {jsonNodes(value, 0).map((node, i) =>
        typeof node === "string" || node === null || node === undefined ? (
          node
        ) : (
          <Fragment key={i}>{node}</Fragment>
        ),
      )}
    </pre>
  );
}

/* ---------- Diff viewer ---------- */
export interface DiffLine {
  t: " " | "+" | "-" | "@";
  a?: number | undefined;
  b?: number | undefined;
  s: string;
}
export interface DiffViewerProps {
  file?: string | undefined;
  lines: DiffLine[];
  plus?: number | undefined;
  minus?: number | undefined;
  maxHeight?: number | undefined;
}
export function DiffViewer({ file, lines, plus, minus, maxHeight }: DiffViewerProps) {
  return (
    <div className="ah-diff">
      {file && (
        <div className="ah-diff-head">
          <Icon name="file-pen" size="sm" />
          <PathText path={file} max={72} />
          <span className="ah-grow" />
          <span className="ah-plus">+{plus}</span>
          <span className="ah-minus">−{minus}</span>
        </div>
      )}
      <div style={{ maxHeight, overflow: "auto" }}>
        {lines.map((line, i) =>
          line.t === "@" ? (
            <div key={i} className="ah-diff-hunk">
              {line.s}
            </div>
          ) : (
            <div
              key={i}
              className={cx(
                "ah-diff-line",
                line.t === "+" && "ah-diff-add",
                line.t === "-" && "ah-diff-del",
              )}
            >
              <span>{line.a ?? ""}</span>
              <span>{line.b ?? ""}</span>
              <span>{line.t === " " ? "" : line.t === "-" ? "−" : "+"}</span>
              <span>{line.s}</span>
            </div>
          ),
        )}
      </div>
    </div>
  );
}

/* ---------- File tree: touched files by repo ---------- */
export type FileStatus = "read" | "created" | "edited" | "deleted";
export interface FileNode {
  name: string;
  path?: string | undefined;
  repo?: boolean | undefined;
  status?: FileStatus | undefined;
  plus?: number | undefined;
  minus?: number | undefined;
  children?: FileNode[] | undefined;
}
const FILE_ICON: Record<FileStatus, IconName> = {
  created: "file-plus",
  deleted: "file-x",
  edited: "file-pen",
  read: "file-text",
};
export interface FileTreeProps {
  nodes: FileNode[];
  selected?: string | undefined;
  onSelect?: ((path: string) => void) | undefined;
  depth?: number;
  label?: string | undefined;
}
export function FileTree({ nodes, selected, onSelect, depth = 0, label }: FileTreeProps) {
  return (
    <ul className="ah-tree" role={depth ? "group" : "tree"} aria-label={depth ? undefined : label}>
      {nodes.map((node) => {
        const icon: IconName = node.children
          ? node.repo
            ? "book"
            : "folder-open"
          : node.status
            ? FILE_ICON[node.status]
            : "file-text";
        const row = (
          <>
            <Icon name={icon} size="sm" />
            <span
              className="ah-tree-name"
              title={node.path}
              style={
                node.repo
                  ? { fontWeight: 600, fontFamily: "var(--font-sans)", fontSize: 13 }
                  : undefined
              }
            >
              {node.name}
            </span>
            {node.status && (
              <span className={`ah-fbadge ah-fbadge-${node.status}`}>{node.status}</span>
            )}
            {node.plus !== undefined && <span className="ah-plus">+{node.plus}</span>}
            {node.minus !== undefined && <span className="ah-minus">−{node.minus}</span>}
          </>
        );
        const isSelected = node.path !== undefined && selected === node.path;
        return (
          <li
            key={node.path ?? node.name}
            // A tree (spec 10, Files tab): items are its rows, chosen with their buttons.
            // eslint-disable-next-line jsx-a11y/no-noninteractive-element-to-interactive-role
            role="treeitem"
            aria-expanded={node.children ? true : undefined}
            aria-selected={node.children ? undefined : isSelected}
          >
            {node.children || !onSelect || node.path === undefined ? (
              <div className="ah-tree-item" data-selected={isSelected || undefined}>
                {row}
              </div>
            ) : (
              <button
                type="button"
                className="ah-tree-item"
                data-selected={isSelected || undefined}
                onClick={() => {
                  if (node.path !== undefined) onSelect(node.path);
                }}
              >
                {row}
              </button>
            )}
            {node.children && (
              <FileTree
                nodes={node.children}
                selected={selected}
                onSelect={onSelect}
                depth={depth + 1}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

/* ---------- Timeline event row ---------- */
export const TOOL_ICON: Readonly<Record<string, IconName>> = {
  Read: "file-text",
  Edit: "file-pen",
  Write: "file-plus",
  Bash: "terminal",
  Grep: "text-search",
  Glob: "folder-search",
  Agent: "network",
  WebFetch: "globe",
  MCP: "plug",
  Skill: "scroll-text",
};

export type EventCategory =
  | "prompt"
  | "message"
  | "reasoning"
  | "tool"
  | "gate"
  | "decision"
  | "learning"
  | "lifecycle"
  | "error"
  | "guard";

export const EVENT_CATEGORIES: Readonly<Record<EventCategory, { icon: IconName; kind: string }>> = {
  prompt: { icon: "user", kind: "Prompt" },
  message: { icon: "message-square", kind: "Agent message" },
  reasoning: { icon: "message-square-dashed", kind: "Recorded reasoning summary" },
  tool: { icon: "terminal", kind: "Tool call" },
  gate: { icon: "hourglass", kind: "Gate" },
  decision: { icon: "split", kind: "Decision" },
  learning: { icon: "sprout", kind: "Learning proposed" },
  lifecycle: { icon: "play", kind: "Session" },
  error: { icon: "circle-x", kind: "Tool error" },
  guard: { icon: "shield-x", kind: "Guard" },
};

function toolIcon(tool: string | undefined): IconName | undefined {
  return tool === undefined ? undefined : TOOL_ICON[tool];
}

export interface TimelineEv {
  id: string;
  /** Clock time shown in the gutter, e.g. "14:02:11". */
  time: string;
  iso?: string | undefined;
  cat: EventCategory;
  kind?: string | undefined;
  /** Who did it ("Main agent", "Subagent · Explore"); shown in place of the kind and tool. */
  actor?: { kind: string; label: string } | undefined;
  icon?: IconName | undefined;
  tool?: string | undefined;
  text: ReactNode;
  mono?: boolean | undefined;
  exit?: number | null | undefined;
  /** Seconds. */
  duration?: number | null | undefined;
  plus?: number | null | undefined;
  minus?: number | null | undefined;
  badge?: ReactNode;
  derived?: boolean | string | undefined;
  expired?: string | undefined;
  raw?: unknown;
  detail?: ReactNode;
}

export interface TimelineEventProps {
  ev: TimelineEv;
  current?: boolean | undefined;
  expanded?: boolean | undefined;
  onToggle?: ((open: boolean) => void) | undefined;
  isNew?: boolean | undefined;
  onSelect?: (() => void) | undefined;
  /** The absolute link to this event; defaults to this page with `?event=<id>`. */
  permalink?: string | undefined;
}
export function TimelineEvent({
  ev,
  current,
  expanded,
  onToggle,
  isNew,
  onSelect,
  permalink,
}: TimelineEventProps) {
  const [open, setOpen] = useState(Boolean(expanded));
  const [raw, setRaw] = useState(false);
  const category = EVENT_CATEGORIES[ev.cat];
  const icon = ev.icon ?? (ev.cat === "tool" ? toolIcon(ev.tool) : undefined) ?? category.icon;
  const hasDetail = Boolean(ev.detail ?? ev.expired);
  const toggle = () => {
    setOpen(!open);
    onToggle?.(!open);
  };
  const text = (
    <span
      className={cx("ah-ev-text", ev.mono && "ah-mono")}
      style={ev.mono ? { fontSize: 13 } : undefined}
    >
      {ev.text}
    </span>
  );
  const link =
    permalink ??
    `${window.location.origin}${window.location.pathname}?event=${encodeURIComponent(ev.id)}`;
  return (
    // Rows are selected with j/k and Enter (spec 01 keyboard map); the click is a mouse shortcut.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
    <div
      className={cx("ah-ev", `ah-ev-${ev.cat}`, isNew && "ah-ev-new")}
      data-c={ev.cat}
      aria-current={current ? true : undefined}
      id={`ev-${ev.id}`}
      onClick={onSelect}
    >
      <div className="ah-ev-time" title={ev.iso}>
        {ev.time}
      </div>
      <div className="ah-ev-rail">
        <span className="ah-ev-mark" aria-hidden="true">
          <Icon name={icon} />
        </span>
      </div>
      <div className="ah-ev-body">
        <div className="ah-ev-line">
          {ev.actor ? (
            <span className="ah-ev-kind">
              <span className="ah-actor" data-actor={ev.actor.kind} title={ev.actor.label}>
                {ev.actor.label}
              </span>
              <span className="ah-sr"> · </span>
            </span>
          ) : (
            <span className="ah-ev-kind">
              {ev.kind ?? category.kind}
              {ev.tool && (
                <span className="ah-tool">
                  <Icon name={toolIcon(ev.tool) ?? "plug"} />
                  {ev.tool}
                </span>
              )}
            </span>
          )}
          <div className="ah-ev-main">
            {hasDetail ? (
              <button
                type="button"
                className="ah-group-toggle"
                aria-expanded={open}
                onClick={(e) => {
                  e.stopPropagation();
                  toggle();
                }}
              >
                <Icon name="chevron-right" size="sm" />
                {text}
              </button>
            ) : (
              text
            )}
            {ev.exit !== undefined && ev.exit !== null && (
              <span className={cx("ah-exit", ev.exit === 0 ? "ah-exit-ok" : "ah-exit-bad")}>
                exit {ev.exit}
              </span>
            )}
            {ev.duration !== undefined && ev.duration !== null && (
              <span className="ah-subtle ah-small ah-mono">{fmtDuration(ev.duration)}</span>
            )}
            {ev.plus !== undefined && ev.plus !== null && (
              <span className="ah-plus">+{ev.plus}</span>
            )}
            {ev.minus !== undefined && ev.minus !== null && (
              <span className="ah-minus">−{ev.minus}</span>
            )}
            {ev.badge}
            {ev.derived && (
              <DerivedLabel>
                {ev.derived === true ? "Extracted from transcript" : ev.derived}
              </DerivedLabel>
            )}
          </div>
        </div>
        {open && ev.expired && (
          <div className="ah-ev-detail">
            <ExpiredContent date={ev.expired} />
          </div>
        )}
        {open && ev.detail && <div className="ah-ev-detail">{ev.detail}</div>}
        {raw && ev.raw !== undefined && (
          <div className="ah-ev-detail">
            <JsonViewer value={ev.raw} />
          </div>
        )}
      </div>
      <div className="ah-ev-actions">
        <IconButton
          size="sm"
          icon="link"
          label="Copy permalink to this event"
          onClick={(e) => {
            e.stopPropagation();
            copyText(link);
          }}
        />
        <IconButton
          size="sm"
          icon="hash"
          label={`Copy event id ${ev.id}`}
          onClick={(e) => {
            e.stopPropagation();
            copyText(ev.id);
          }}
        />
        {ev.raw !== undefined && (
          <IconButton
            size="sm"
            icon="braces"
            label={raw ? "Hide raw event" : "Show raw event (redacted JSON)"}
            onClick={(e) => {
              e.stopPropagation();
              setRaw(!raw);
            }}
          />
        )}
      </div>
    </div>
  );
}

/* ---------- Collapsed run of consecutive reads/searches ---------- */
export interface ToolGroupItem {
  time: string;
  path: string;
  tool?: string | undefined;
  note?: string | undefined;
}
export interface ToolGroupProps {
  time: string;
  tool?: string;
  count: number;
  summary: string;
  items?: ToolGroupItem[];
  expanded?: boolean | undefined;
}
export function ToolGroup({
  time,
  tool = "Read",
  count,
  summary,
  items = [],
  expanded,
}: ToolGroupProps) {
  const [open, setOpen] = useState(Boolean(expanded));
  return (
    <div className="ah-ev" data-c="tool">
      <div className="ah-ev-time">{time}</div>
      <div className="ah-ev-rail">
        <span className="ah-ev-mark" aria-hidden="true">
          <Icon name={toolIcon(tool) ?? "layers"} />
        </span>
      </div>
      <div className="ah-ev-body">
        <div className="ah-ev-line">
          <span className="ah-ev-kind">
            {count} calls
            <span className="ah-tool">
              <Icon name={toolIcon(tool) ?? "plug"} />
              {tool}
            </span>
          </span>
          <div className="ah-ev-main">
            <button
              type="button"
              className="ah-group-toggle"
              aria-expanded={open}
              onClick={() => {
                setOpen(!open);
              }}
            >
              <Icon name="chevron-right" size="sm" />
              <span>{summary}</span>
            </button>
          </div>
        </div>
        {open && (
          <ul className="ah-group-list">
            {items.map((item, i) => (
              <li key={i}>
                <span className="ah-mono ah-subtle" style={{ width: 56 }}>
                  {item.time}
                </span>
                <Icon name={toolIcon(item.tool ?? tool) ?? "plug"} size="sm" />
                <PathText path={item.path} max={64} dimDir />
                {item.note && <span className="ah-subtle">{item.note}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div />
    </div>
  );
}

/* ---------- Nested subagent lane ---------- */
export interface SubagentLaneProps {
  agent: string;
  sessionId: string;
  status?: ReactNode;
  summary?: string | undefined;
  duration?: number | undefined;
  cost?: string | undefined;
  children?: ReactNode;
  collapsed?: boolean | undefined;
}
export function SubagentLane({
  agent,
  sessionId,
  status,
  summary,
  duration,
  cost,
  children,
  collapsed: collapsedProp,
}: SubagentLaneProps) {
  const [collapsed, setCollapsed] = useState(Boolean(collapsedProp));
  return (
    <div
      className="ah-lane"
      data-collapsed={collapsed}
      role="group"
      aria-label={`Subagent ${agent}`}
    >
      <div className="ah-lane-head">
        <button
          type="button"
          className="ah-group-toggle"
          aria-expanded={!collapsed}
          onClick={() => {
            setCollapsed(!collapsed);
          }}
        >
          <Icon name="chevron-right" size="sm" />
          <Icon name="network" size="sm" style={{ color: "var(--ev-tool)" }} />
          <span className="ah-mono" style={{ fontSize: 13, fontWeight: 500 }}>
            {agent}
          </span>
        </button>
        {status}
        <span
          className="ah-subtle ah-small ah-grow"
          style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {summary}
        </span>
        {duration !== undefined && (
          <span className="ah-mono ah-subtle ah-small">{fmtDuration(duration)}</span>
        )}
        {cost && <span className="ah-mono ah-small">{cost}</span>}
        <AppLink className="ah-small" href={`/sessions/${encodeURIComponent(sessionId)}`}>
          Open session {sessionId.replace(/-/g, "").slice(0, 8)}
        </AppLink>
      </div>
      {!collapsed && <div className="ah-lane-body">{children}</div>}
    </div>
  );
}

/* ---------- Minimap / scrubber ---------- */
const CAT_COLOR: Record<EventCategory, string> = {
  prompt: "--ev-prompt",
  message: "--ev-message",
  reasoning: "--ev-reasoning",
  tool: "--ev-tool",
  gate: "--ev-gate",
  decision: "--ev-decision",
  learning: "--ev-learning",
  lifecycle: "--ev-lifecycle",
  error: "--failed",
  guard: "--guard",
};
export type MinimapMarkKind = "error" | "decision" | "gate" | "guard" | "learning";
const MARK_COLOR: Record<MinimapMarkKind, string> = {
  error: "--failed",
  decision: "--ev-decision",
  gate: "--ev-gate",
  guard: "--guard",
  learning: "--ev-learning",
};
export interface MinimapProps {
  bins?: { cat: EventCategory; n: number }[];
  marks?: { at: number; kind: MinimapMarkKind; label: string }[];
  /** Visible window as fractions of the whole. */
  view?: { top: number; height: number };
  height?: number;
  onJump?: ((fraction: number) => void) | undefined;
}
export function Minimap({
  bins = [],
  marks = [],
  view = { top: 0, height: 0.2 },
  height = 480,
  onJump,
}: MinimapProps) {
  const max = Math.max(1, ...bins.map((b) => b.n));
  const binHeight = height / Math.max(1, bins.length);
  const onKeyDown = (event: KeyboardEvent) => {
    const step = { ArrowDown: 0.1, PageDown: 0.25, ArrowUp: -0.1, PageUp: -0.25 }[event.key];
    if (step === undefined || !onJump) return;
    event.preventDefault();
    onJump(Math.min(1, Math.max(0, view.top + step)));
  };
  return (
    <div
      className="ah-minimap"
      style={{ height }}
      role="slider"
      aria-label="Session minimap: click to jump"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(view.top * 100)}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onClick={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        onJump?.((e.clientY - rect.top) / (rect.height > 0 ? rect.height : 1));
      }}
    >
      {bins.map((bin, i) => (
        <span
          key={i}
          className="ah-minimap-bin"
          style={{
            top: i * binHeight + binHeight / 2 - 1,
            width: Math.max(3, (bin.n / max) * 34),
            background: `var(${CAT_COLOR[bin.cat]})`,
            height: Math.max(2, binHeight - 1),
          }}
        />
      ))}
      {marks.map((mark, i) => (
        <span
          key={i}
          title={mark.label}
          className="ah-minimap-mark"
          style={{ top: mark.at * height - 2, background: `var(${MARK_COLOR[mark.kind]})` }}
        />
      ))}
      <span
        className="ah-minimap-view"
        style={{ top: view.top * height, height: view.height * height }}
      />
    </div>
  );
}
