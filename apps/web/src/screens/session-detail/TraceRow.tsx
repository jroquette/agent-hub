import { Fragment } from "react";
import type { ReactNode } from "react";

import {
  Icon,
  RedactionChip,
  StatusBadge,
  TimelineEvent,
  TOOL_ICON,
  type IconName,
  type TimelineEv,
} from "../../components";
import { fmtClock, fmtDuration, fmtInt, type TimeZoneMode } from "../../lib/format";
import { ProblemBadge, type Problem } from "./ProblemsPanel";
import { renderParts, type FlatRow, type TraceEvent } from "./timeline";
import type { Phrase } from "./verbs";

/** The copy every message and reasoning row shows when expanded (AC-200.47). */
export const CONTENT_NOT_STORED =
  "Content not stored. agent-hub keeps metadata only; the transcript stays in Claude Code's folder on this machine.";
export const DIFF_NOT_STORED = "Diff content is not stored in this version.";

/** Text with each `[redacted: kind]` marker shown as a RedactionChip (AC-200.46). */
export function Redacted({ text }: { text: string }) {
  return (
    <>
      {renderParts(text).map((part, i) =>
        "redacted" in part ? (
          <RedactionChip key={i} kind={part.redacted} />
        ) : (
          <Fragment key={i}>{part.text}</Fragment>
        ),
      )}
    </>
  );
}

/** A row's sentence: the verb, its object (a command or path in code) and the tail. */
export function PhraseView({ phrase }: { phrase: Phrase }) {
  return (
    <>
      <span className="sd-verb">{phrase.verb}</span>
      {phrase.object !== undefined && (
        <>
          {" "}
          {phrase.kind === "text" || phrase.kind === undefined ? (
            <span className="sd-object">
              <Redacted text={phrase.object} />
            </span>
          ) : (
            <code className="ah-mono sd-object">
              <Redacted text={phrase.object} />
            </code>
          )}
        </>
      )}
      {phrase.tail && (
        <>
          {" "}
          <span className="sd-tail">
            <Redacted text={phrase.tail} />
          </span>
        </>
      )}
    </>
  );
}

function Facts({ facts }: { facts: [string, string][] }) {
  if (facts.length === 0) return null;
  return (
    <dl className="sd-facts">
      {facts.map(([label, value]) => (
        <Fragment key={label}>
          <dt>{label}</dt>
          <dd>
            <Redacted text={value} />
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}

/** The expanded body of a row: metadata only, never content (D11). */
export function detailOf(row: TraceEvent): ReactNode {
  const facts: [string, string][] = [...row.facts];
  if (row.content) {
    const role =
      row.content.role === "reasoning" ? "Recorded reasoning summary" : `Role ${row.content.role}`;
    const size =
      row.content.chars === null ? "size unknown" : `${fmtInt(row.content.chars)} characters`;
    return (
      <div className="ah-stack" style={{ gap: 6 }}>
        <div className="ah-small ah-muted">
          {role} · {size} · turn {row.turn}
        </div>
        <div className="ah-small ah-subtle">{CONTENT_NOT_STORED}</div>
      </div>
    );
  }
  if (row.exit !== undefined) facts.unshift(["Exit code", String(row.exit)]);
  if (row.durationS !== undefined) facts.push(["Duration", fmtDuration(row.durationS)]);
  const bytes = row.events[1]?.payload.output_bytes;
  if (typeof bytes === "number") facts.push(["Output", `${fmtInt(bytes)} bytes (not stored)`]);
  if (row.note) facts.push(["Note", row.note]);
  const command = row.tool === "Bash" || row.label === "Stop blocked" ? row.text : null;
  const edits = row.plus !== undefined || row.minus !== undefined;
  if (!command && !edits && facts.length === 0) return null;
  return (
    <div className="ah-stack" style={{ gap: 6 }}>
      {command && (
        <div className="ah-code" role="group" aria-label="Command">
          <span className="ah-code-prompt">$</span>
          <pre style={{ whiteSpace: "pre-wrap" }}>
            <Redacted text={command} />
          </pre>
        </div>
      )}
      {edits && <div className="ah-small ah-subtle">{DIFF_NOT_STORED}</div>}
      <Facts facts={facts} />
    </div>
  );
}

/** The canonical event behind a row, as the Raw disclosure shows it (redacted at ingestion). */
export function rawOf(row: TraceEvent): Record<string, unknown> {
  const [event] = row.events;
  if (!event) return {};
  return {
    type: event.type,
    timestamp: event.timestamp,
    source: event.source,
    source_id: event.source_id,
    received_at: event.received_at,
    latency:
      event.latency_ms === null
        ? null
        : `received ${(event.latency_ms / 1000).toFixed(2)} s after the event`,
    merged_sources: event.merged_sources,
    conflict: event.conflict,
    project: event.project,
    session: event.session,
    repo: event.repo,
    agent: event.agent,
    workflow: event.workflow,
    step: event.step,
    payload: event.payload,
  };
}

function toEv(row: TraceEvent, time: string, problem: Problem | undefined): TimelineEv {
  const tone =
    row.cat === "error" ? "var(--failed)" : row.cat === "guard" ? "var(--guard)" : undefined;
  return {
    id: row.id,
    time,
    iso: row.at,
    cat: row.cat,
    kind: row.label,
    actor: row.actor,
    icon: row.icon,
    tool: row.tool,
    text: <PhraseView phrase={row.phrase} />,
    mono: false,
    exit: row.exit,
    duration: row.durationS,
    plus: row.plus,
    minus: row.minus,
    derived: row.derived,
    badge: (
      <>
        {row.running && <StatusBadge status="running" />}
        {row.label === "Denied by guard" && <StatusBadge status="guard" />}
        {problem ? (
          <ProblemBadge problem={problem} />
        ) : (
          row.cat === "error" && <StatusBadge status="failed" label="Failed" />
        )}
        {row.note && (
          <span className="ah-small" style={{ color: tone ?? "var(--text-subtle)" }}>
            <Redacted text={row.note} />
          </span>
        )}
      </>
    ),
    raw: rawOf(row),
    detail: detailOf(row),
  };
}

export interface TraceRowProps {
  row: FlatRow;
  axis: "time" | "turn";
  tz: TimeZoneMode;
  sessionId: string;
  selected: string | null;
  /** The session's problems by event id (a row matches its call's or result's id). */
  problems?: ReadonlyMap<string, Problem> | undefined;
  openRows: ReadonlySet<string>;
  newIds: ReadonlySet<string>;
  laneLive: boolean;
  onSelect: (id: string) => void;
  onToggleRow: (id: string, open: boolean) => void;
  onToggleGroup: (id: string) => void;
  onToggleLane: (id: string, open: boolean) => void;
  onOpenTurn: (n: number) => void;
  onShowHidden: () => void;
}

const short = (id: string) => id.replace(/-/g, "").slice(0, 8);

/** One virtualised row of the trace. */
export function TraceRow(props: TraceRowProps) {
  const { row, axis, tz } = props;
  const timeOf = (at: string, turn: number) =>
    axis === "turn" ? `T${String(turn)}` : fmtClock(at, tz, true);
  switch (row.t) {
    case "turn":
      return (
        <div className="ah-turn">
          Turn {row.turn.n}
          <span className="ah-mono">{fmtClock(row.turn.at, tz, true)}</span>
        </div>
      );
    case "turnSummary": {
      const seconds = (Date.parse(row.turn.end) - Date.parse(row.turn.at)) / 1000;
      return (
        <button
          type="button"
          className="sd-turn-summary"
          onClick={() => {
            props.onOpenTurn(row.turn.n);
          }}
        >
          <Icon name="chevron-right" size="sm" />
          Turn {row.turn.n} · {fmtInt(row.turn.eventCount)} events
          {row.turn.tools ? ` · ${row.turn.tools}` : ""} · {fmtDuration(seconds)}
        </button>
      );
    }
    case "hidden":
      return (
        <div className="sd-divider">
          <button type="button" onClick={props.onShowHidden}>
            {fmtInt(row.count)} {row.count === 1 ? "event" : "events"} hidden
          </button>
        </div>
      );
    case "gap":
      return <div className="sd-divider">{fmtDuration(row.seconds)} later</div>;
    case "lane": {
      const { lane, open } = row;
      const seconds = (Date.parse(lane.end) - Date.parse(lane.at)) / 1000;
      return (
        <div
          className="sd-lane-head"
          role="group"
          aria-label={`${lane.actor.label}${lane.description ? `: ${lane.description}` : ""}`}
        >
          <div className="ah-lane-head">
            <button
              type="button"
              className="ah-group-toggle"
              aria-expanded={open}
              onClick={() => {
                props.onToggleLane(lane.id, !open);
              }}
            >
              <Icon name="chevron-right" size="sm" />
              <Icon name="network" size="sm" style={{ color: "var(--ev-tool)" }} />
              <span className="ah-actor" data-actor="subagent">
                {lane.actor.label}
              </span>
              {lane.description && (
                <span className="sd-lane-task">
                  <Redacted text={lane.description} />
                </span>
              )}
            </button>
            <span className="ah-mono ah-subtle ah-small">{short(lane.id)}</span>
            {props.laneLive && <StatusBadge status="running" label="Still running" />}
            <span className="ah-subtle ah-small ah-grow">
              {fmtInt(lane.eventCount)} {lane.eventCount === 1 ? "event" : "events"}
              {lane.errors > 0
                ? ` · ${String(lane.errors)} ${lane.errors === 1 ? "error" : "errors"}`
                : ""}
            </span>
            <span className="ah-mono ah-subtle ah-small">{fmtDuration(seconds)}</span>
            <span className="ah-mono ah-subtle ah-small">{timeOf(lane.at, lane.turn)}</span>
          </div>
        </div>
      );
    }
    case "group": {
      const { group, open } = row;
      const icon: IconName = TOOL_ICON[group.tool] ?? "layers";
      return (
        <div className={row.depth > 0 ? `sd-depth-${String(row.depth)}` : undefined}>
          <div className="ah-ev" data-c="tool">
            <div className="ah-ev-time" title={group.at}>
              {timeOf(group.at, group.turn)}
            </div>
            <div className="ah-ev-rail">
              <span className="ah-ev-mark" aria-hidden="true">
                <Icon name={icon} />
              </span>
            </div>
            <div className="ah-ev-body">
              <div className="ah-ev-line">
                <span className="ah-ev-kind">
                  <span className="ah-actor" data-actor={group.actor.kind}>
                    {group.actor.label}
                  </span>
                  <span className="ah-sr"> · </span>
                </span>
                <div className="ah-ev-main">
                  <button
                    type="button"
                    className="ah-group-toggle"
                    aria-expanded={open}
                    onClick={() => {
                      props.onToggleGroup(group.id);
                    }}
                  >
                    <Icon name="chevron-right" size="sm" />
                    <span>
                      <Redacted text={group.summary} />
                    </span>
                  </button>
                  <span className="ah-exit ah-exit-ok">ok</span>
                </div>
              </div>
            </div>
            <div />
          </div>
        </div>
      );
    }
    case "event": {
      const ev = row.row;
      const open = props.openRows.has(ev.id);
      const problem = ev.events
        .map((event) => props.problems?.get(event.event_id))
        .find((found) => found !== undefined);
      return (
        <div className={row.depth > 0 ? `sd-depth-${String(row.depth)}` : undefined}>
          <TimelineEvent
            key={`${ev.id}:${open ? "open" : "shut"}`}
            ev={toEv(ev, timeOf(ev.at, ev.turn), problem)}
            current={props.selected === ev.id}
            expanded={open}
            isNew={props.newIds.has(ev.id)}
            permalink={`${window.location.origin}/sessions/${encodeURIComponent(props.sessionId)}?event=${encodeURIComponent(ev.id)}`}
            onSelect={() => {
              props.onSelect(ev.id);
            }}
            onToggle={(next) => {
              props.onToggleRow(ev.id, next);
            }}
          />
        </div>
      );
    }
  }
}
