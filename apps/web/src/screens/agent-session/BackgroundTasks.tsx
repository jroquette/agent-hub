import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Button, Icon, type IconName } from "../../components";
import { useNow } from "../../lib/clock";
import { cx } from "../../lib/cx";
import { useDrawerWidth } from "./DrawerResize";
import { elapsed, type TaskRow } from "./liveActivity";
import { isCommandTask, type TaskView } from "./model";

/** The session's tasks, as `backgroundTasks` splits them. */
export interface BackgroundTaskList {
  running: TaskRow[];
  done: TaskRow[];
}

/** The DOM id of the Background drawer, for its toggle's `aria-controls`. */
export const BACKGROUND_PANEL_ID = "as-background-panel";

const ENDED: Record<Exclude<TaskView["status"], "running">, { icon: IconName; text: string }> = {
  completed: { icon: "circle-check", text: "completed" },
  failed: { icon: "circle-x", text: "failed" },
  stopped: { icon: "circle-stop", text: "stopped" },
};

const ms = (iso: string | null) => (iso === null ? Number.NaN : Date.parse(iso));

export interface BackgroundChipProps {
  tasks: BackgroundTaskList;
  open: boolean;
  onToggle: () => void;
}

/** The header's way to the Background drawer: how many tasks run now (with a pulse), else how
 * many ended. Hidden until the session started a task. */
export function BackgroundChip({ tasks, open, onToggle }: BackgroundChipProps) {
  const running = tasks.running.length;
  const done = tasks.done.length;
  if (running + done === 0) return null;
  const count = running > 0 ? `${String(running)} running` : `${String(done)} done`;
  return (
    <button
      type="button"
      className={cx("as-files-chip", open && "as-files-chip-open")}
      aria-expanded={open}
      aria-controls={open ? BACKGROUND_PANEL_ID : undefined}
      aria-label={`Background tasks, ${count}`}
      title={`${open ? "Hide" : "Show"} the tasks running in the background`}
      onClick={onToggle}
    >
      {running > 0 ? (
        <span className="as-live-pulse" aria-hidden />
      ) : (
        <Icon name="layers" size="sm" />
      )}
      <span>Background</span>
      <span className="as-steps-count ah-num">{count}</span>
    </button>
  );
}

interface RunningRowProps {
  row: TaskRow;
  now: number;
  onStop: ((taskId: string) => Promise<unknown>) | undefined;
}

/** "commands" when every task is one, "agents" when every one is, else "tasks". */
function noun(rows: TaskRow[], count: number): string {
  const commands = rows.filter((row) => isCommandTask(row.task)).length;
  const word = commands === rows.length ? "command" : commands === 0 ? "agent" : "task";
  return count === 1 ? word : `${word}s`;
}

export interface BackgroundCardProps {
  tasks: BackgroundTaskList;
  /** Ended tasks count from here (the last message's time): older ones are not news. */
  since: string | null;
  onOpen: () => void;
}

/**
 * The conversation's last line while tasks run beside it, as Claude Desktop shows it: "1
 * background command done, 1 running". It shows while one runs or once one ended since the last
 * message, and opens the Background drawer.
 */
export function BackgroundCard({ tasks, since, onOpen }: BackgroundCardProps) {
  const running = tasks.running.length;
  const from = since === null ? Number.NEGATIVE_INFINITY : ms(since);
  const done = tasks.done.filter((row) => ms(row.task.endedAt) >= from);
  if (running === 0 && done.length === 0) return null;
  const rows = [...tasks.running, ...done];
  const parts =
    done.length > 0
      ? [
          `${String(done.length)} background ${noun(rows, done.length)} done`,
          running > 0 ? `${String(running)} running` : null,
        ]
      : [`${String(running)} background ${noun(rows, running)} running`];
  return (
    <button
      type="button"
      className="as-run-files as-bg-card"
      onClick={onOpen}
      title="Show the tasks running in the background"
    >
      {running > 0 ? (
        <span className="as-live-pulse" aria-hidden />
      ) : (
        <Icon name="layers" size="sm" />
      )}
      <span>{parts.filter(Boolean).join(", ")}</span>
      <span className="ah-grow" />
      <Icon name="chevron-right" size="sm" />
    </button>
  );
}

function RunningRow({ row, now, onStop }: RunningRowProps) {
  const [open, setOpen] = useState(false);
  // Asked to stop: the row stays until the task's end arrives on the stream.
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState(false);
  const { task, label, call } = row;
  const command = isCommandTask(task);
  const took = now - ms(task.startedAt);
  const nested = call?.running ?? [];
  const uses = call?.calls ?? 0;
  const head = (
    <>
      <Icon name={command ? "terminal" : "network"} size="sm" />
      <span className="as-bg-label" title={label}>
        {label}
      </span>
      <span className="ah-grow" />
      {Number.isFinite(took) && <span className="ah-subtle ah-num">{elapsed(took)}</span>}
    </>
  );
  return (
    <li className="as-bg-row as-bg-running">
      <div className="as-bg-top">
        {nested.length > 0 || uses > 0 ? (
          <button
            type="button"
            className="as-bg-head"
            aria-expanded={open}
            onClick={() => {
              setOpen(!open);
            }}
          >
            <Icon name={open ? "chevron-down" : "chevron-right"} size="sm" />
            {head}
          </button>
        ) : (
          <div className="as-bg-head">{head}</div>
        )}
        {onStop && (
          <Button
            size="sm"
            variant="ghost"
            icon="square"
            disabled={stopping}
            aria-label={`Stop ${label}`}
            title={stopping ? "Stopping…" : "Stop this task"}
            onClick={() => {
              setStopping(true);
              setStopError(false);
              onStop(task.id).catch(() => {
                setStopping(false);
                setStopError(true);
              });
            }}
          />
        )}
      </div>
      {stopError && (
        <div className="as-bg-sub ah-small" role="alert">
          Could not stop it. Try again.
        </div>
      )}
      {!command && (
        <div className="as-bg-sub ah-small ah-subtle">
          {uses} tool {uses === 1 ? "use" : "uses"}
          {nested.length > 0 && `, ${String(nested.length)} running`}
        </div>
      )}
      {open && nested.length > 0 && (
        <ul className="as-bg-calls ah-small">
          {nested.map((child) => (
            <li key={child.id}>
              <b>{child.name}</b>{" "}
              <span className="ah-mono ah-muted" title={child.label}>
                {child.label}
              </span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function DoneRow({ row }: { row: TaskRow }) {
  const { task, label } = row;
  const end = task.status === "running" ? null : ENDED[task.status];
  const took = ms(task.endedAt) - ms(task.startedAt);
  return (
    <li className={cx("as-bg-row", `as-bg-${task.status}`)}>
      <div className="as-bg-head">
        {end && (
          <Icon
            name={end.icon}
            size="sm"
            title={task.status === "completed" ? end.text : undefined}
          />
        )}
        <span className="as-bg-label" title={label}>
          {label}
        </span>
        <span className="ah-grow" />
        {task.status !== "completed" && <span className="ah-subtle">{end?.text}</span>}
        {Number.isFinite(took) && took >= 0 && (
          <span className="ah-subtle ah-num">{elapsed(took)}</span>
        )}
      </div>
    </li>
  );
}

export interface BackgroundPanelProps {
  tasks: BackgroundTaskList;
  onClose: () => void;
  /** Stops a running task; without it (an ended or cloud session) no stop button shows. */
  onStop?: ((taskId: string) => Promise<unknown>) | undefined;
}

/**
 * The tasks Claude started that run beside the conversation (background agents and commands):
 * the running ones on top with how long they have run and, for an agent, its calls so far; the
 * ended ones folded under "Completed". Esc or Close shuts it.
 */
export function BackgroundPanel({ tasks, onClose, onStop }: BackgroundPanelProps) {
  const now = useNow(1000);
  const heading = useRef<HTMLHeadingElement>(null);
  const drawer = useDrawerWidth();
  const { running, done } = tasks;
  const [showDone, setShowDone] = useState(running.length === 0);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || event.shiftKey) return;
    event.preventDefault();
    event.stopPropagation();
    onClose();
  };
  return (
    // Esc closes it from anywhere inside.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <aside
      id={BACKGROUND_PANEL_ID}
      className="as-drawer as-bg-panel"
      style={drawer.style}
      aria-labelledby={`${BACKGROUND_PANEL_ID}-title`}
      onKeyDown={onKeyDown}
    >
      <div {...drawer.handle} />
      <div className="as-activity-panel-head">
        <Icon name="layers" size="sm" />
        <h2
          ref={heading}
          id={`${BACKGROUND_PANEL_ID}-title`}
          tabIndex={-1}
          className="ah-h3"
          style={{ margin: 0 }}
        >
          Background tasks
        </h2>
        <span className="ah-grow" />
        <Button size="sm" variant="ghost" icon="x" onClick={onClose}>
          Close
        </Button>
      </div>
      <div className="as-bg-body">
        <section aria-labelledby="as-bg-running">
          <h3 id="as-bg-running" className="as-bg-section ah-small ah-muted">
            Running
          </h3>
          {running.length === 0 ? (
            <p className="ah-small ah-subtle as-bg-empty">Nothing runs in the background now.</p>
          ) : (
            <ul className="as-bg-list">
              {running.map((row) => (
                <RunningRow key={row.task.id} row={row} now={now} onStop={onStop} />
              ))}
            </ul>
          )}
        </section>
        {done.length > 0 && (
          <section>
            <button
              type="button"
              className="as-bg-section as-bg-toggle ah-small ah-muted"
              aria-expanded={showDone}
              onClick={() => {
                setShowDone(!showDone);
              }}
            >
              Completed <span className="ah-num">{done.length}</span>
              <Icon name={showDone ? "chevron-down" : "chevron-right"} size="sm" />
            </button>
            {showDone && (
              <ul className="as-bg-list">
                {done.map((row) => (
                  <DoneRow key={row.task.id} row={row} />
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </aside>
  );
}
