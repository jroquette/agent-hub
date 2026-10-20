import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Button, Icon, type IconName } from "../../components";
import { useNow } from "../../lib/clock";
import { cx } from "../../lib/cx";
import { BACKGROUND_PANEL_ID } from "./BackgroundTasks";
import { useDrawerWidth } from "./DrawerResize";
import { cutText, OUTPUT_SHOWN } from "./ToolCallCard";
import {
  elapsed,
  QUIET_MS,
  STALLED_MS,
  SUBAGENT_SHOWN,
  type FeedItem,
  type LiveActivity,
  type LivePhase,
  type TurnSteps,
} from "./liveActivity";

const PHASE: Record<LivePhase, { icon: IconName; text: string }> = {
  waiting: { icon: "hand", text: "Waiting for you" },
  writing: { icon: "message-square", text: "Writing the reply" },
  subagents: { icon: "network", text: "Running subagents" },
  tool: { icon: "terminal", text: "Running" },
  thinking: { icon: "lightbulb", text: "Thinking" },
  planning: { icon: "clipboard-list", text: "Planning" },
  background: { icon: "network", text: "Working in the background" },
};

const since = (iso: string | null | undefined, now: number): number | null => {
  if (!iso) return null;
  const at = Date.parse(iso);
  return Number.isNaN(at) ? null : now - at;
};

function headline(activity: LiveActivity): string {
  const { phase, calls } = activity;
  const subagents = calls.filter((call) => call.subagent).length;
  if (phase === "background") {
    const commands = calls.filter((call) => !call.subagent).length;
    const agents = calls.length - commands;
    const words = [
      agents > 0 ? `${String(agents)} ${agents === 1 ? "agent" : "agents"}` : null,
      commands > 0 ? `${String(commands)} ${commands === 1 ? "command" : "commands"}` : null,
    ];
    return `Running in the background: ${words.filter(Boolean).join(", ")}`;
  }
  if (phase === "subagents")
    return `${PHASE.subagents.text}: ${String(subagents)} ${subagents === 1 ? "agent" : "agents"}`;
  if (phase === "tool") {
    const latest = calls[0];
    const more = calls.length > 1 ? ` (+${String(calls.length - 1)})` : "";
    return latest ? `Running ${latest.name}${more}` : PHASE.tool.text;
  }
  return PHASE[phase].text;
}

type ToolItem = Extract<FeedItem, { kind: "tool" }>;

function Output({ item }: { item: ToolItem }) {
  const [full, setFull] = useState(false);
  if (item.preview.length === 0) return null;
  if (full && item.output !== null) {
    const cut = cutText(item.output, OUTPUT_SHOWN);
    return (
      <div className="as-feed-out">
        <pre className="as-feed-pre as-feed-full">{cut ? cut.shown : item.output}</pre>
        <button
          type="button"
          className="as-feed-more"
          onClick={() => {
            setFull(false);
          }}
        >
          {cut
            ? `First ${OUTPUT_SHOWN.toLocaleString("en-US")} of ${cut.total.toLocaleString("en-US")} characters · collapse`
            : "Collapse"}
        </button>
      </div>
    );
  }
  return (
    <div className="as-feed-out">
      <pre className="as-feed-pre">{item.preview.join("\n")}</pre>
      {item.more > 0 && (
        <button
          type="button"
          className="as-feed-more"
          onClick={() => {
            setFull(true);
          }}
        >
          … +{item.more} {item.more === 1 ? "line" : "lines"}
        </button>
      )}
    </div>
  );
}

/** Scrolls the conversation to a request's card and puts the keyboard on it. */
function showRequest(id: string) {
  const card = Array.from(document.querySelectorAll<HTMLElement>("[data-request-id]")).find(
    (element) => element.dataset.requestId === id,
  );
  if (!card) return;
  card.scrollIntoView({ block: "center" });
  (card.querySelector<HTMLElement>("button:not(:disabled)") ?? card).focus({ preventScroll: true });
}

function ThoughtRow({ seconds }: { seconds: number | null }) {
  return (
    <li className="as-feed-item as-feed-thinking">
      <div className="as-feed-call">
        <span className="as-feed-mark" aria-hidden>
          ✻
        </span>
        <span className="ah-muted">
          {seconds === null ? "Thought" : `Thought for ${String(seconds)} s`}
        </span>
      </div>
    </li>
  );
}

function FeedRow({ item, now }: { item: FeedItem; now: number }) {
  // A running subagent starts open on its latest calls; a finished one starts closed.
  const [open, setOpen] = useState<boolean | null>(null);
  const [all, setAll] = useState(false);
  if (item.kind === "thinking") return <ThoughtRow seconds={item.seconds} />;
  const ran = item.state === "running" ? since(item.tool.startedAt, now) : null;
  const group = item.childCount > 0;
  const expanded = open ?? item.state === "running";
  const shown = all ? item.children : item.children.slice(-SUBAGENT_SHOWN);
  const hidden = item.children.length - shown.length;
  const uses = `${String(item.childCount)} tool ${item.childCount === 1 ? "use" : "uses"}`;
  const call = (
    <>
      <span className="as-feed-mark" aria-hidden>
        ●
      </span>
      <b>{item.tool.name}</b>
      {item.summary && (
        <span className="as-feed-summary ah-mono" title={item.summary}>
          ({item.summary})
        </span>
      )}
      {group && <span className="ah-subtle ah-num">· {uses}</span>}
      {ran !== null && <span className="ah-subtle ah-num">running {elapsed(ran)}</span>}
      {item.state === "error" && <span className="ah-subtle">didn't work, Claude moved on</span>}
      {item.state === "denied" && <span className="ah-subtle">denied</span>}
    </>
  );
  return (
    <li className={cx("as-feed-item", `as-feed-${item.state}`)}>
      {group ? (
        <button
          type="button"
          className="as-feed-call as-feed-group"
          aria-expanded={expanded}
          onClick={() => {
            setOpen(!expanded);
          }}
        >
          <Icon name={expanded ? "chevron-down" : "chevron-right"} size="sm" />
          {call}
        </button>
      ) : (
        <div className="as-feed-call">{call}</div>
      )}
      {item.state === "waiting" && (
        <div className="as-feed-out">
          <span className="as-live-quiet">Waiting for you</span>{" "}
          <button
            type="button"
            className="as-feed-more"
            onClick={() => {
              showRequest(item.tool.id);
            }}
          >
            Show request
          </button>
        </div>
      )}
      {(!group || expanded) && <Output item={item} />}
      {group && expanded && (
        <ul className="as-feed as-feed-nested">
          {hidden > 0 && (
            <li>
              <button
                type="button"
                className="as-feed-more"
                onClick={() => {
                  setAll(true);
                }}
              >
                +{hidden} more tool {hidden === 1 ? "use" : "uses"}
              </button>
            </li>
          )}
          {shown.map((child) => (
            <FeedRow key={child.key} item={child} now={now} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Quiet, stalled or fresh: how long since the last record reads. */
function quietness(activity: LiveActivity, now: number) {
  const quiet = since(activity.lastEventAt, now);
  const waiting = activity.phase === "waiting";
  const running = activity.calls.length > 0;
  const stalled = quiet !== null && quiet > STALLED_MS && !running && !waiting;
  const isQuiet = quiet !== null && quiet > QUIET_MS && !waiting;
  return { quiet, stalled, isQuiet, running };
}

function QuietLabel({ activity, now }: { activity: LiveActivity; now: number }) {
  const { quiet, stalled, isQuiet } = quietness(activity, now);
  if (quiet === null || !isQuiet || stalled) return null;
  return (
    <span
      className="ah-subtle ah-num"
      title="Time since the session's last record. A long command or subagent can be quiet for minutes."
    >
      quiet for {elapsed(quiet)}
    </span>
  );
}

function StallNotice({ activity, now }: { activity: LiveActivity; now: number }) {
  const { quiet, stalled } = quietness(activity, now);
  if (!stalled || quiet === null) return null;
  return (
    <p className="as-live-stall ah-small">
      <Icon name="info" size="sm" /> Claude has been quiet for {elapsed(quiet)}. If it does not pick
      up again, press Stop and send your message again.
    </p>
  );
}

export interface LiveActivityBarProps {
  activity: LiveActivity | null;
  /** Whether the Steps drawer is open. */
  open: boolean;
  onToggle: () => void;
}

/**
 * One line above the composer while a turn runs: what Claude does now (thinking, a tool,
 * subagents, waiting for you), how many steps so far, how long the turn has run and how long since
 * the last record, so a long quiet stretch never reads as a dead session. It opens the Steps
 * drawer, where the calls and their output are.
 */
export function LiveActivityBar({ activity, open, onToggle }: LiveActivityBarProps) {
  const now = useNow(1000);
  if (!activity) return null;
  const turn = since(activity.turnStartedAt, now);
  const { stalled } = quietness(activity, now);
  const subagent = activity.calls.find((call) => call.subagent);
  const detail =
    activity.phase === "subagents"
      ? subagent?.label
      : activity.phase === "background"
        ? activity.calls[0]?.label
        : activity.phase === "tool"
          ? activity.calls[0]?.label
          : activity.todo;
  const ask =
    activity.phase === "waiting"
      ? activity.feed.find(
          (item): item is Extract<FeedItem, { kind: "tool" }> =>
            item.kind === "tool" && item.state === "waiting",
        )
      : undefined;
  // Between turns the bar opens the Background drawer, not the Steps one.
  const tasks = activity.phase === "background";
  const what = tasks ? "tasks" : "steps";
  return (
    <section
      className={cx("as-live", `as-live-${activity.phase}`, stalled && "as-live-stalled")}
      aria-label="Live activity"
    >
      <StallNotice activity={activity} now={now} />
      <button
        type="button"
        className="as-live-bar ah-small"
        onClick={
          ask
            ? () => {
                showRequest(ask.tool.id);
              }
            : onToggle
        }
        aria-expanded={ask ? undefined : open}
        aria-controls={!ask && open ? (tasks ? BACKGROUND_PANEL_ID : STEPS_PANEL_ID) : undefined}
        aria-keyshortcuts={ask || tasks ? undefined : STEPS_KEYS}
        title={
          ask
            ? "Go to the request that waits for you"
            : tasks
              ? `${open ? "Hide" : "Show"} the tasks running in the background`
              : open
                ? `Hide the turn's steps (${STEPS_KEY_LABEL})`
                : `Show the turn's steps (${STEPS_KEY_LABEL})`
        }
      >
        <span className="as-live-pulse" aria-hidden />
        <Icon name={PHASE[activity.phase].icon} size="sm" />
        <b>{headline(activity)}</b>
        {detail && <span className="as-live-detail ah-muted">{detail}</span>}
        <span className="ah-grow" />
        {turn !== null && (
          <span
            className="ah-muted ah-num"
            title={
              activity.phase === "background"
                ? "Time since the oldest background agent started"
                : "Time since your message started this turn"
            }
          >
            <Icon name="timer" size="sm" /> {elapsed(turn)}
          </span>
        )}
        <QuietLabel activity={activity} now={now} />
        <span className="as-live-open-label">
          <span className="as-live-open-text">
            {ask ? "Show request" : `${open ? "Hide" : "Show"} ${what}`}
          </span>
          <Icon name={ask ? "arrow-up" : open ? "chevron-right" : "chevron-left"} size="sm" />
        </span>
      </button>
    </section>
  );
}

/** The DOM id of the Steps drawer, for its toggles' `aria-controls`. */
export const STEPS_PANEL_ID = "as-live-panel";
/** The chord that shows or hides the Steps drawer (Ctrl is Cmd on a Mac). */
export const STEPS_KEYS = "Control+Alt+Period Meta+Alt+Period";
export const STEPS_KEY_LABEL = "Ctrl Alt .";

export interface StepsToggleProps {
  steps: TurnSteps;
  open: boolean;
  onToggle: () => void;
}

/** The header's way to the Steps drawer, beside Review changes: a pulse while the turn runs. */
export function StepsToggle({ steps, open, onToggle }: StepsToggleProps) {
  if (steps.end === null) return null;
  const total = steps.feed.length + steps.earlier;
  const running = steps.activity !== null;
  return (
    <button
      type="button"
      className={cx("as-files-chip", open && "as-files-chip-open")}
      aria-expanded={open}
      aria-controls={open ? STEPS_PANEL_ID : undefined}
      aria-keyshortcuts={STEPS_KEYS}
      aria-label={`Steps, ${String(total)}${running ? ", turn running" : ""}`}
      title={`${open ? "Hide" : "Show"} the turn's steps (${STEPS_KEY_LABEL})`}
      onClick={onToggle}
    >
      <Icon name="list" size="sm" />
      <span>Steps</span>
      <span className="as-steps-count ah-num">{total}</span>
    </button>
  );
}

function stepsHeadline(steps: TurnSteps): string {
  const took = steps.tookMs === null ? "" : ` in ${elapsed(steps.tookMs)}`;
  switch (steps.end) {
    case "interrupted":
      return `Turn interrupted${steps.tookMs === null ? "" : ` after ${elapsed(steps.tookMs)}`}`;
    case "ended":
      return "Session ended";
    case "failed":
      return "Session failed";
    default:
      return `Turn finished${took}`;
  }
}

export interface StepsPanelProps {
  steps: TurnSteps;
  onClose: () => void;
  /** Opened by the owner just now (not restored on page load): the keyboard goes to it. */
  focusOnOpen?: boolean;
}

/**
 * The turn's steps beside the conversation, as Claude Code prints them: what runs now pinned on
 * top, then each thought and each call with the first lines of its output (all of it on demand), a
 * subagent as a group of its own calls. It follows new steps unless you scrolled up; Esc or Close
 * shuts it. Earlier turns stay in the conversation's activity lines.
 */
export function StepsPanel({ steps, onClose, focusOnOpen = true }: StepsPanelProps) {
  const now = useNow(1000);
  const heading = useRef<HTMLHeadingElement>(null);
  const list = useRef<HTMLOListElement | null>(null);
  const [pinned, setPinned] = useState(true);
  const [seen, setSeen] = useState(steps.feed.length);
  const drawer = useDrawerWidth();
  const { activity, feed, earlier } = steps;
  const lastKey = feed.at(-1)?.key;
  useEffect(() => {
    if (focusOnOpen) heading.current?.focus({ preventScroll: true });
    // Only on open: a later prop change never steals focus.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // New steps keep the list at its end, unless the reader scrolled up in it.
  useEffect(() => {
    const element = list.current;
    if (element && pinned) element.scrollTop = element.scrollHeight;
  }, [feed.length, lastKey, pinned]);
  if (pinned && seen !== feed.length) setSeen(feed.length);
  const unseen = pinned ? 0 : Math.max(0, feed.length - seen);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || event.shiftKey) return;
    event.preventDefault();
    event.stopPropagation();
    onClose();
  };
  const total = feed.length + earlier;
  const turn = activity ? since(activity.turnStartedAt, now) : null;

  return (
    // Esc closes it from anywhere inside.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <aside
      id={STEPS_PANEL_ID}
      className="as-drawer as-live-panel"
      style={drawer.style}
      aria-labelledby={`${STEPS_PANEL_ID}-title`}
      onKeyDown={onKeyDown}
    >
      <div {...drawer.handle} />
      <div className="as-activity-panel-head">
        <Icon name="list" size="sm" />
        <h2
          ref={heading}
          id={`${STEPS_PANEL_ID}-title`}
          tabIndex={-1}
          className="ah-h3"
          style={{ margin: 0 }}
        >
          Steps
        </h2>
        <span className="ah-small ah-muted ah-num">
          {total} {total === 1 ? "step" : "steps"}
        </span>
        <span className="ah-grow" />
        <Button
          size="sm"
          variant="ghost"
          icon="maximize-2"
          aria-pressed={drawer.wide}
          onClick={drawer.toggleWide}
        >
          {drawer.wide ? "Narrow" : "Widen"}
        </Button>
        <Button size="sm" variant="ghost" icon="x" onClick={onClose}>
          Close
        </Button>
      </div>
      <div className="as-live-panel-now ah-small">
        {activity ? (
          <>
            <Icon name={PHASE[activity.phase].icon} size="sm" />
            <b>{headline(activity)}</b>
            <span className="ah-grow" />
            {turn !== null && (
              <span className="ah-muted ah-num">
                <Icon name="timer" size="sm" /> {elapsed(turn)}
              </span>
            )}
            <QuietLabel activity={activity} now={now} />
          </>
        ) : (
          <>
            <Icon
              name={
                steps.end === "failed"
                  ? "circle-x"
                  : steps.end === "interrupted"
                    ? "circle-stop"
                    : "circle-check"
              }
              size="sm"
            />
            <b>{stepsHeadline(steps)}</b>
          </>
        )}
      </div>
      {activity && <StallNotice activity={activity} now={now} />}
      {total === 0 ? (
        <p className="ah-muted as-files-empty">
          {activity
            ? "No steps yet. Claude's calls and thoughts show here as they happen."
            : "No steps in the last turn: Claude answered without a call."}
        </p>
      ) : (
        <ol
          className="as-feed as-live-panel-steps"
          ref={list}
          aria-label="Steps"
          onScroll={(event) => {
            const element = event.currentTarget;
            setPinned(element.scrollHeight - element.scrollTop - element.clientHeight < 24);
          }}
        >
          {earlier > 0 && (
            <li className="as-feed-earlier ah-subtle">
              +{earlier} earlier {earlier === 1 ? "step" : "steps"} (in the conversation)
            </li>
          )}
          {feed.map((item) => (
            <FeedRow key={item.key} item={item} now={now} />
          ))}
        </ol>
      )}
      {!pinned && (
        <button
          type="button"
          className="as-steps-jump ah-small"
          aria-label={unseen > 0 ? `Jump to latest, ${String(unseen)} new` : "Jump to latest"}
          onClick={() => {
            const element = list.current;
            if (element) element.scrollTop = element.scrollHeight;
            setPinned(true);
          }}
        >
          <Icon name="arrow-down" size="sm" />
          <span aria-hidden="true">
            {unseen > 0 ? `Jump to latest · ${String(unseen)} new` : "Jump to latest"}
          </span>
        </button>
      )}
    </aside>
  );
}
