import { useEffect, useRef, useState } from "react";

import { Icon, type IconName } from "../../components";
import { useNow } from "../../lib/clock";
import { cx } from "../../lib/cx";
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

const FEED_KEY = "ah.agent-session.live-feed";

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

/** Whether the feed starts open: it does, unless the owner closed it before. */
function useFeedOpen(): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(FEED_KEY) !== "closed";
    } catch {
      return true;
    }
  });
  const set = (next: boolean) => {
    setOpen(next);
    try {
      localStorage.setItem(FEED_KEY, next ? "open" : "closed");
    } catch {
      // Without storage the choice holds for this page only.
    }
  };
  return [open, set];
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

export interface LiveActivityBarProps {
  activity: LiveActivity | null;
}

/**
 * The background work of a running turn, always in view above the composer, as Claude Code prints
 * it: each step of the turn (a thought, a call and the first lines of its output, a subagent and its
 * latest calls), then one line with what Claude does now, how long the turn has run and how long
 * since the last record. A long quiet stretch with nothing running reads as likely stuck.
 */
export function LiveActivityBar({ activity }: LiveActivityBarProps) {
  const [open, setOpen] = useFeedOpen();
  const now = useNow(1000);
  const feedRef = useRef<HTMLUListElement | null>(null);
  const pinned = useRef(true);
  const steps = activity?.feed.length ?? 0;
  const lastKey = activity?.feed.at(-1)?.key;
  // New steps keep the feed at its end, unless the reader scrolled up in it.
  useEffect(() => {
    const feed = feedRef.current;
    if (feed && pinned.current) feed.scrollTop = feed.scrollHeight;
  }, [steps, lastKey, open]);
  if (!activity) return null;
  const turn = since(activity.turnStartedAt, now);
  const quiet = since(activity.lastEventAt, now);
  const waiting = activity.phase === "waiting";
  const running = activity.calls.length > 0;
  const stalled = quiet !== null && quiet > STALLED_MS && !running && !waiting;
  const isQuiet = quiet !== null && quiet > QUIET_MS && !waiting;
  const subagent = activity.calls.find((call) => call.subagent);
  const detail =
    activity.phase === "subagents"
      ? subagent?.label
      : activity.phase === "tool"
        ? activity.calls[0]?.label
        : activity.todo;
  const total = steps + activity.earlier;
  const canOpen = steps > 0;

  return (
    <section
      className={cx("as-live", `as-live-${activity.phase}`, stalled && "as-live-stalled")}
      aria-label="Live activity"
    >
      {open && canOpen && (
        <ul
          className="as-feed as-feed-root"
          ref={feedRef}
          aria-label="This turn's steps"
          onScroll={(event) => {
            const el = event.currentTarget;
            pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          }}
        >
          {activity.earlier > 0 && (
            <li className="as-feed-earlier ah-subtle">
              +{activity.earlier} earlier {activity.earlier === 1 ? "step" : "steps"} (in the
              conversation)
            </li>
          )}
          {activity.feed.map((item) => (
            <FeedRow key={item.key} item={item} now={now} />
          ))}
        </ul>
      )}
      {stalled && (
        <p className="as-live-stall ah-small">
          <Icon name="triangle-alert" size="sm" /> No record for {elapsed(quiet)} and nothing
          running: Claude may be stuck. Stop ends the turn; your next message resumes the session.
        </p>
      )}
      <button
        type="button"
        className="as-live-bar ah-small"
        onClick={() => {
          setOpen(!open);
        }}
        disabled={!canOpen}
        aria-expanded={canOpen ? open : undefined}
        title={canOpen ? (open ? "Hide this turn's steps" : "Show this turn's steps") : undefined}
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
        {canOpen && (
          <span className="ah-subtle ah-num">
            {total} {total === 1 ? "step" : "steps"}
          </span>
        )}
        {turn !== null && (
          <span className="ah-muted ah-num" title="Time since your message started this turn">
            <Icon name="timer" size="sm" /> {elapsed(turn)}
          </span>
        )}
        {quiet !== null && (
          <span
            className={cx(
              "ah-num",
              stalled ? "as-live-stuck" : isQuiet ? "as-live-quiet" : "ah-subtle",
            )}
            title="Time since the session's last record. A long command or subagent can be quiet for minutes."
          >
            {stalled
              ? `no event for ${elapsed(quiet)}`
              : isQuiet
                ? `quiet for ${elapsed(quiet)}${running ? ", a call is still running" : ""}`
                : `last event ${elapsed(quiet)} ago`}
          </span>
        )}
        {canOpen && <Icon name={open ? "chevron-down" : "chevron-up"} size="sm" />}
      </button>
    </section>
  );
}
