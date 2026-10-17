import { useState } from "react";

import { Icon, TOOL_ICON, type IconName } from "../../components";
import { useNow } from "../../lib/clock";
import { cx } from "../../lib/cx";
import {
  elapsed,
  QUIET_MS,
  type LiveActivity,
  type LiveCall,
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

const since = (iso: string | null, now: number): number | null => {
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

function CallRow({ call, now }: { call: LiveCall; now: number }) {
  const ran = since(call.startedAt, now);
  const icon = call.subagent ? "network" : (TOOL_ICON[call.name] ?? "loader");
  return (
    <li className="as-live-call">
      <div className="as-live-call-row">
        <Icon name={icon} size="sm" />
        <b>{call.subagent ? "Subagent" : call.name}</b>
        <span className="as-live-call-label ah-mono" title={call.label}>
          {call.label}
        </span>
        {call.subagent && call.calls > 0 && (
          <span className="ah-subtle ah-num">
            {call.calls} {call.calls === 1 ? "call" : "calls"}
          </span>
        )}
        {ran !== null && <span className="ah-subtle ah-num">{elapsed(ran)}</span>}
      </div>
      {call.running.length > 0 && (
        <ul className="as-live-calls as-live-nested">
          {call.running.map((child) => (
            <CallRow key={child.id} call={child} now={now} />
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
 * The background work of a running turn, always in view above the composer: what Claude does now
 * (thinking, a tool, subagents, waiting for you), how long the turn has run and how long since the
 * last record, so a long quiet stretch never reads as a dead session. Opens to the running calls,
 * subagents with their own running calls nested.
 */
export function LiveActivityBar({ activity }: LiveActivityBarProps) {
  const [open, setOpen] = useState(false);
  const now = useNow(1000);
  if (!activity) return null;
  const turn = since(activity.turnStartedAt, now);
  const quiet = since(activity.lastEventAt, now);
  const isQuiet = quiet !== null && quiet > QUIET_MS && activity.phase !== "waiting";
  const subagent = activity.calls.find((call) => call.subagent);
  const detail =
    activity.phase === "subagents"
      ? subagent?.label
      : activity.phase === "tool"
        ? activity.calls[0]?.label
        : activity.todo;
  const canOpen = activity.calls.length > 0;

  return (
    <section
      className={cx("as-live", `as-live-${activity.phase}`, open && "as-live-open")}
      aria-label="Live activity"
    >
      {open && canOpen && (
        <ul className="as-live-calls">
          {activity.calls.map((call) => (
            <CallRow key={call.id} call={call} now={now} />
          ))}
        </ul>
      )}
      <button
        type="button"
        className="as-live-bar ah-small"
        onClick={() => {
          setOpen((before) => !before);
        }}
        disabled={!canOpen}
        aria-expanded={canOpen ? open : undefined}
        title={canOpen ? "Show what is running" : undefined}
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
        {turn !== null && (
          <span className="ah-muted ah-num" title="Time since your message started this turn">
            <Icon name="timer" size="sm" /> {elapsed(turn)}
          </span>
        )}
        {quiet !== null && (
          <span
            className={cx("ah-num", isQuiet ? "as-live-quiet" : "ah-subtle")}
            title="Time since the session's last record. Long tools and subagents can be quiet for minutes; the session is still running."
          >
            {isQuiet
              ? `quiet for ${elapsed(quiet)}, still running`
              : `last event ${elapsed(quiet)} ago`}
          </span>
        )}
        {canOpen && <Icon name={open ? "chevron-down" : "chevron-up"} size="sm" />}
      </button>
    </section>
  );
}
