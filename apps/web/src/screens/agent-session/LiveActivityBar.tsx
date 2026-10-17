import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Button, Icon, type IconName } from "../../components";
import { useNow } from "../../lib/clock";
import { cx } from "../../lib/cx";
import { useDrawerWidth } from "./DrawerResize";
import { cutText, OUTPUT_SHOWN } from "./ToolCallCard";
import {
  elapsed,
  QUIET_MS,
  STALLED_MS,
  type FeedItem,
  type LiveActivity,
  type LivePhase,
} from "./liveActivity";

const PHASE: Record<LivePhase, { icon: IconName; text: string }> = {
  waiting: { icon: "hand", text: "Waiting for you" },
  writing: { icon: "message-square", text: "Writing the reply" },
  subagents: { icon: "network", text: "Running subagents" },
  tool: { icon: "terminal", text: "Running" },
  thinking: { icon: "lightbulb", text: "Thinking" },
  planning: { icon: "clipboard-list", text: "Planning" },
};

const since = (iso: string | null | undefined, now: number): number | null => {
  if (!iso) return null;
  const at = Date.parse(iso);
  return Number.isNaN(at) ? null : now - at;
};

function headline(activity: LiveActivity): string {
  const { phase, calls } = activity;
  const subagents = calls.filter((call) => call.subagent).length;
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
      <pre className={cx("as-feed-pre", item.state === "error" && "as-feed-error")}>
        {item.preview.join("\n")}
      </pre>
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

function FeedRow({ item, now }: { item: FeedItem; now: number }) {
  if (item.kind === "thinking") {
    return (
      <li className="as-feed-item as-feed-thinking">
        <div className="as-feed-call">
          <span className="as-feed-mark" aria-hidden>
            ✻
          </span>
          <span className="ah-muted">
            {item.seconds === null ? "Thought" : `Thought for ${String(item.seconds)} s`}
          </span>
        </div>
      </li>
    );
  }
  const ran = item.state === "running" ? since(item.tool.startedAt, now) : null;
  const hidden = item.childCount - item.children.length;
  return (
    <li className={cx("as-feed-item", `as-feed-${item.state}`)}>
      <div className="as-feed-call">
        <span className="as-feed-mark" aria-hidden>
          ●
        </span>
        <b>{item.tool.name}</b>
        {item.summary && (
          <span className="as-feed-summary ah-mono" title={item.summary}>
            ({item.summary})
          </span>
        )}
        {ran !== null && <span className="ah-subtle ah-num">running {elapsed(ran)}</span>}
        {item.state === "waiting" && <span className="as-live-quiet">waiting for you</span>}
        {item.state === "denied" && <span className="ah-subtle">denied</span>}
      </div>
      <Output item={item} />
      {item.children.length > 0 && (
        <ul className="as-feed as-feed-nested">
          {hidden > 0 && (
            <li className="as-feed-earlier ah-subtle">
              +{hidden} more tool {hidden === 1 ? "use" : "uses"}
            </li>
          )}
          {item.children.map((child) => (
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
  const { quiet, stalled, isQuiet, running } = quietness(activity, now);
  if (quiet === null) return null;
  return (
    <span
      className={cx("ah-num", stalled ? "as-live-stuck" : isQuiet ? "as-live-quiet" : "ah-subtle")}
      title="Time since the session's last record. A long command or subagent can be quiet for minutes."
    >
      {stalled
        ? `no event for ${elapsed(quiet)}`
        : isQuiet
          ? `quiet for ${elapsed(quiet)}${running ? ", a call is still running" : ""}`
          : `last event ${elapsed(quiet)} ago`}
    </span>
  );
}

function StallNotice({ activity, now }: { activity: LiveActivity; now: number }) {
  const { quiet, stalled } = quietness(activity, now);
  if (!stalled || quiet === null) return null;
  return (
    <p className="as-live-stall ah-small">
      <Icon name="triangle-alert" size="sm" /> No record for {elapsed(quiet)} and nothing running:
      Claude may be stuck. Stop ends the turn; your next message resumes the session.
    </p>
  );
}

export interface LiveActivityBarProps {
  activity: LiveActivity | null;
  /** Whether the Live activity drawer is open. */
  open: boolean;
  onToggle: () => void;
}

/**
 * One line above the composer while a turn runs: what Claude does now (thinking, a tool,
 * subagents, waiting for you), how many steps so far, how long the turn has run and how long since
 * the last record, so a long quiet stretch never reads as a dead session. It opens the Live
 * activity drawer, where the steps and their output are.
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
      : activity.phase === "tool"
        ? activity.calls[0]?.label
        : activity.todo;
  const total = activity.feed.length + activity.earlier;

  return (
    <section
      className={cx("as-live", `as-live-${activity.phase}`, stalled && "as-live-stalled")}
      aria-label="Live activity"
    >
      <StallNotice activity={activity} now={now} />
      <button
        type="button"
        className="as-live-bar ah-small"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={open ? LIVE_PANEL_ID : undefined}
        title={open ? "Close the Live activity panel" : "Open the turn's steps and their output"}
      >
        <span className="as-live-pulse" aria-hidden />
        <Icon name={PHASE[activity.phase].icon} size="sm" />
        <b>{headline(activity)}</b>
        {detail && <span className="as-live-detail ah-muted">{detail}</span>}
        <span className="ah-grow" />
        {activity.todo && activity.phase !== "thinking" && activity.phase !== "planning" && (
          <span className="as-live-todo ah-muted" title="Todo in progress">
            <Icon name="list-todo" size="sm" /> {activity.todo}
          </span>
        )}
        {total > 0 && (
          <span className="ah-subtle ah-num">
            {total} {total === 1 ? "step" : "steps"}
          </span>
        )}
        {turn !== null && (
          <span className="ah-muted ah-num" title="Time since your message started this turn">
            <Icon name="timer" size="sm" /> {elapsed(turn)}
          </span>
        )}
        <QuietLabel activity={activity} now={now} />
        <span className="as-live-open-label">
          <Icon name="panel-left" size="sm" /> {open ? "Hide steps" : "Show steps"}
        </span>
      </button>
    </section>
  );
}

/** The DOM id of the Live activity drawer, for the bar's `aria-controls`. */
export const LIVE_PANEL_ID = "as-live-panel";

export interface LiveActivityPanelProps {
  /** What runs now; null once the turn ended. */
  activity: LiveActivity | null;
  /** The steps shown: the open turn's, else the last turn's. */
  feed: FeedItem[];
  earlier: number;
  onClose: () => void;
}

/**
 * The turn's steps beside the conversation, as Claude Code prints them: each thought, each call and
 * the first lines of its output (all of it on demand), a subagent with its latest calls. It
 * follows new steps unless you scrolled up; Esc or Close shuts it.
 */
export function LiveActivityPanel({ activity, feed, earlier, onClose }: LiveActivityPanelProps) {
  const now = useNow(1000);
  const heading = useRef<HTMLHeadingElement>(null);
  const list = useRef<HTMLOListElement | null>(null);
  const pinned = useRef(true);
  const drawer = useDrawerWidth();
  const lastKey = feed.at(-1)?.key;
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);
  // New steps keep the list at its end, unless the reader scrolled up in it.
  useEffect(() => {
    const element = list.current;
    if (element && pinned.current) element.scrollTop = element.scrollHeight;
  }, [feed.length, lastKey]);
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
      id={LIVE_PANEL_ID}
      className="as-drawer as-live-panel"
      style={drawer.style}
      aria-labelledby={`${LIVE_PANEL_ID}-title`}
      onKeyDown={onKeyDown}
    >
      <div {...drawer.handle} />
      <div className="as-activity-panel-head">
        <Icon name="activity" size="sm" />
        <h2
          ref={heading}
          id={`${LIVE_PANEL_ID}-title`}
          tabIndex={-1}
          className="ah-h3"
          style={{ margin: 0 }}
        >
          Live activity
        </h2>
        <span className="ah-small ah-muted">
          {activity ? "This turn" : "Last turn"} · {total} {total === 1 ? "step" : "steps"}
        </span>
        <span className="ah-grow" />
        <Button size="sm" variant="ghost" icon="x" onClick={onClose}>
          Close
        </Button>
      </div>
      {activity && (
        <div className="as-live-panel-now ah-small" role="status">
          <span className="as-live-pulse" aria-hidden />
          <b>{headline(activity)}</b>
          <span className="ah-grow" />
          {turn !== null && (
            <span className="ah-muted ah-num">
              <Icon name="timer" size="sm" /> {elapsed(turn)}
            </span>
          )}
          <QuietLabel activity={activity} now={now} />
        </div>
      )}
      {activity && <StallNotice activity={activity} now={now} />}
      {total === 0 ? (
        <p className="ah-muted as-files-empty">
          {activity
            ? "No step yet: Claude is reading your message."
            : "No turn yet. Send a message and its steps show here."}
        </p>
      ) : (
        <ol
          className="as-feed as-live-panel-steps"
          ref={list}
          aria-label="Steps"
          onScroll={(event) => {
            const element = event.currentTarget;
            pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 24;
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
    </aside>
  );
}
