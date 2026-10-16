import { memo, useEffect, useRef, type KeyboardEvent } from "react";

import { Button, Icon, TOOL_ICON, type IconName } from "../../components";
import { cx } from "../../lib/cx";
import { useDrawerWidth } from "./DrawerResize";
import { RequestCard, type AnswerPermission } from "./PermissionCard";
import { RunFilesCard, sameRunFiles, type RunFile } from "./RunFilesCard";
import { StoredCopyLabel } from "./SessionStatus";
import { ToolCallCard } from "./ToolCallCard";
import {
  toolState,
  toolSummary,
  type PermissionView,
  type ToolView,
  type TranscriptEntry,
  type TranscriptState,
} from "./model";

type ThinkingEntry = Extract<TranscriptEntry, { kind: "thinking" }>;

/** One step of a run: a thought, or a call and the permission asked for it, when one was. */
export type ActivityStep =
  | { kind: "thinking"; key: string; entry: ThinkingEntry }
  | { kind: "tool"; key: string; tool: ToolView; request?: PermissionView | undefined };

/** A thought, collapsed to its duration. */
export function ThinkingBlock({ entry }: { entry: ThinkingEntry }) {
  return (
    <details className="as-thinking">
      <summary>
        <Icon name="lightbulb" size="sm" />{" "}
        {entry.seconds === null ? "Thinking" : `Thought for ${String(entry.seconds)} s`}
        {entry.redacted && <StoredCopyLabel />}
      </summary>
      <div className="as-thinking-text">{entry.text}</div>
    </details>
  );
}

const plural = (count: number, one: string, many: string) =>
  `${String(count)} ${count === 1 ? one : many}`;

/** How a kind of call reads in a run's summary, by tool name. */
const PHRASE: Record<string, (count: number) => string> = {
  Bash: (n) => `ran ${plural(n, "command", "commands")}`,
  Read: (n) => `read ${plural(n, "file", "files")}`,
  Edit: (n) => `edited ${plural(n, "file", "files")}`,
  MultiEdit: (n) => `edited ${plural(n, "file", "files")}`,
  Write: (n) => `wrote ${plural(n, "file", "files")}`,
  NotebookEdit: (n) => `edited ${plural(n, "notebook", "notebooks")}`,
  Grep: (n) => plural(n, "search", "searches"),
  Glob: (n) => plural(n, "search", "searches"),
  WebFetch: (n) => `fetched ${plural(n, "page", "pages")}`,
  WebSearch: (n) => plural(n, "web search", "web searches"),
  Task: (n) => plural(n, "subagent", "subagents"),
  Agent: (n) => plural(n, "subagent", "subagents"),
};

/** "Ran 3 commands, read 2 files, thought 12 s": the calls counted by kind, first seen first,
 * then the time spent thinking. */
export function activitySummary(steps: readonly ActivityStep[]): string {
  const counts = new Map<string, { phrase: (count: number) => string; count: number }>();
  let seconds = 0;
  let thoughts = 0;
  for (const step of steps) {
    if (step.kind === "thinking") {
      thoughts += 1;
      seconds += step.entry.seconds ?? 0;
      continue;
    }
    const { name } = step.tool;
    const phrase = PHRASE[name] ?? ((n: number) => `${String(n)} ${name}`);
    // Calls that read alike (Grep and Glob) count together.
    const label = phrase(2);
    const known = counts.get(label);
    if (known) known.count += 1;
    else counts.set(label, { phrase, count: 1 });
  }
  const parts = Array.from(counts.values(), ({ phrase, count }) => phrase(count));
  if (thoughts > 0) parts.push(seconds > 0 ? `thought ${String(seconds)} s` : "thought");
  const text = parts.join(", ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The call a running run is on: the latest one without a result. */
function currentCall(steps: readonly ActivityStep[]): ToolView | null {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i];
    if (step?.kind === "tool" && step.tool.result === null) return step.tool;
  }
  return null;
}

const toolIcon = (name: string): IconName =>
  TOOL_ICON[name] ?? (name.startsWith("mcp__") ? "plug" : "box");

export interface ActivityRunProps {
  /** Stable for the run's life (the key of its first entry). */
  runKey: string;
  steps: readonly ActivityStep[];
  /** Whether the side panel shows this run. */
  selected: boolean;
  /** Whether the session is in a turn: only then does a call without a result read as running. */
  live: boolean;
  /** Opens this run in the side panel, or closes the panel when it already shows it. */
  onToggle: (runKey: string) => void;
  onAnswerPermission: AnswerPermission;
  /** The files this run changed, shown as a card under its line (none: no card). */
  files?: readonly RunFile[] | undefined;
  reviewed?: Readonly<Record<string, string>> | undefined;
  /** Opens the Changed files drawer on a file, or on its list (null). */
  onOpenFile?: ((path: string | null) => void) | undefined;
}

const NO_FILES: readonly RunFile[] = [];
const NONE_REVIEWED: Readonly<Record<string, string>> = {};

/**
 * What Claude did between two messages, as one quiet line: the calls counted by kind and the time
 * spent thinking, or the call it is on while it works. The steps open in the side panel
 * (`ActivityPanel`), so the conversation keeps to the messages. A permission asked for a call stays
 * here, under the line, where you can answer it without opening the panel.
 */
function ActivityRunView({
  runKey,
  steps,
  selected,
  live,
  onToggle,
  onAnswerPermission,
  files = NO_FILES,
  reviewed = NONE_REVIEWED,
  onOpenFile,
}: ActivityRunProps) {
  const states = steps.flatMap((step) =>
    step.kind === "tool" ? [toolState(step.tool, step.request)] : [],
  );
  const failed = states.filter((state) => state === "error" || state === "denied").length;
  const waiting = states.includes("waiting");
  const current = live ? currentCall(steps) : null;
  const summary = activitySummary(steps);
  const running = current !== null && !waiting;
  const label = [
    running ? [current.name, toolSummary(current.input)].filter(Boolean).join(" ") : summary,
    failed > 0 && `${String(failed)} failed`,
  ]
    .filter(Boolean)
    .join(", ");
  const requests = steps.flatMap((step) =>
    step.kind === "tool" && step.request ? [step.request] : [],
  );
  return (
    <div className={cx("as-activity", selected && "as-activity-selected")}>
      <button
        type="button"
        className="as-activity-head"
        data-run-key={runKey}
        aria-expanded={selected}
        aria-controls={selected ? ACTIVITY_PANEL_ID : undefined}
        aria-label={label}
        onClick={() => {
          onToggle(runKey);
        }}
      >
        {running ? (
          <>
            <Icon name="loader" size="sm" className="as-spin" />
            <span className="as-activity-now">
              <b>{current.name}</b>
              {toolSummary(current.input) && (
                <span className="ah-mono"> {toolSummary(current.input)}</span>
              )}
            </span>
          </>
        ) : (
          <>
            <Icon name={waiting ? "hand" : "layers"} size="sm" />
            <span className="as-activity-now">{summary}</span>
          </>
        )}
        {failed > 0 && (
          <span className="as-activity-failed">
            <Icon name="circle-x" size="sm" />
            {`${String(failed)} failed`}
          </span>
        )}
        <Icon name="chevron-right" size="sm" className="as-activity-chevron" />
      </button>
      {requests.map((request) => (
        <RequestCard
          key={request.requestId}
          request={request}
          onAnswerPermission={onAnswerPermission}
        />
      ))}
      {files.length > 0 && onOpenFile && (
        <RunFilesCard files={files} reviewed={reviewed} onOpenFile={onOpenFile} />
      )}
    </div>
  );
}

/** Equal when every step is the same object: a delta elsewhere skips the run. */
function sameRun(a: ActivityRunProps, b: ActivityRunProps): boolean {
  return (
    a.runKey === b.runKey &&
    a.selected === b.selected &&
    a.live === b.live &&
    a.onToggle === b.onToggle &&
    a.onAnswerPermission === b.onAnswerPermission &&
    a.onOpenFile === b.onOpenFile &&
    a.reviewed === b.reviewed &&
    sameRunFiles(a.files ?? NO_FILES, b.files ?? NO_FILES) &&
    sameSteps(a.steps, b.steps)
  );
}

export function sameSteps(a: readonly ActivityStep[], b: readonly ActivityStep[]): boolean {
  return (
    a.length === b.length &&
    a.every((step, i) => {
      const other = b[i];
      if (step.kind === "thinking") return other?.kind === "thinking" && other.entry === step.entry;
      return other?.kind === "tool" && other.tool === step.tool && other.request === step.request;
    })
  );
}

export const ActivityRun = memo(ActivityRunView, sameRun);

/** The DOM id of the side panel, for the run lines' `aria-controls`. */
export const ACTIVITY_PANEL_ID = "as-activity-panel";

export interface ActivityPanelProps {
  steps: readonly ActivityStep[];
  tools: TranscriptState["tools"];
  calls: TranscriptState["children"];
  requests: TranscriptState["permissions"];
  onClose: () => void;
}

/** A run's steps in order, beside the conversation: each thought and each call, expandable to
 * its input and result. Esc or Close shuts it. */
function ActivityPanelView({ steps, tools, calls, requests, onClose }: ActivityPanelProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const drawer = useDrawerWidth();
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || event.shiftKey) return;
    event.preventDefault();
    event.stopPropagation();
    onClose();
  };
  const callCount = steps.filter((step) => step.kind === "tool").length;
  return (
    // Esc closes it from anywhere inside.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <aside
      id={ACTIVITY_PANEL_ID}
      className="as-drawer as-activity-panel"
      style={drawer.style}
      aria-labelledby={`${ACTIVITY_PANEL_ID}-title`}
      onKeyDown={onKeyDown}
    >
      <div {...drawer.handle} />
      <div className="as-activity-panel-head">
        <h2
          ref={heading}
          id={`${ACTIVITY_PANEL_ID}-title`}
          tabIndex={-1}
          className="ah-h3"
          style={{ margin: 0 }}
        >
          Activity
        </h2>
        <span className="ah-small ah-muted">
          {plural(callCount, "call", "calls")} · {activitySummary(steps)}
        </span>
        <span className="ah-grow" />
        <Button size="sm" variant="ghost" icon="x" onClick={onClose}>
          Close
        </Button>
      </div>
      <ol className="as-activity-steps">
        {steps.map((step) => (
          <li key={step.key} className="as-activity-step">
            <span className="as-activity-dot" aria-hidden="true">
              <Icon
                name={step.kind === "thinking" ? "lightbulb" : toolIcon(step.tool.name)}
                size="sm"
              />
            </span>
            <div className="as-activity-step-body">
              {step.kind === "thinking" ? (
                <ThinkingBlock entry={step.entry} />
              ) : (
                <ToolCallCard
                  tool={step.tool}
                  tools={tools}
                  calls={calls}
                  request={step.request}
                  requests={requests}
                />
              )}
            </div>
          </li>
        ))}
      </ol>
    </aside>
  );
}

/** Equal when every step is the same object: a delta elsewhere re-renders no card in the panel. */
export const ActivityPanel = memo(
  ActivityPanelView,
  (a, b) =>
    a.tools === b.tools &&
    a.calls === b.calls &&
    a.requests === b.requests &&
    a.onClose === b.onClose &&
    sameSteps(a.steps, b.steps),
);
