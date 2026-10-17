/* The list view's cells: one readable line per session, observed or driven (sessions redesign). */
import type { ReactNode } from "react";

import {
  AppLink,
  Icon,
  IssueLink,
  Money,
  StatusBadge,
  Tooltip,
  sessionIdentity,
  type IconName,
  type Status,
} from "../../components";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtClock, fmtDuration, fmtInt, fmtTokens } from "../../lib/format";
import { modeLabel } from "../agent-session/model";
import { badgeOf } from "./badge";
import { rowHref } from "./drivenRows";
import type { AgentSession } from "./queries";
import { isDriven, type SectionRow } from "./sections";
import { problemsLine, troubled, waitingLink } from "./tiles";

type Tz = "local" | "utc";

const TOOL_ICON: Record<string, IconName> = {
  Read: "file-text",
  Edit: "file-pen",
  Write: "file-plus",
  Bash: "terminal",
  Grep: "text-search",
  Glob: "folder-search",
  Agent: "network",
  WebFetch: "globe",
};

const ONE_LINE = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } as const;
const short = (id: string) => id.replace(/-/g, "").slice(0, 8);
const since = (iso: string, now: number) => Math.max(0, (now - Date.parse(iso)) / 1000);

/** Driven statuses read with the same words as observed ones: a turn in progress is "Live". */
const DRIVEN_BADGE: Record<AgentSession["status"], [Status, string]> = {
  running: ["live", "Live"],
  waiting_permission: ["waiting", "Waiting"],
  idle: ["idle", "Idle"],
  ended: ["ended", "Ended"],
  failed: ["failed", "Failed"],
};

/** True when the row's session is driven from hub web (its own row, or an observed twin). */
export function isChat(row: SectionRow): boolean {
  return isDriven(row) || Boolean(row.agent_session_id);
}

/** A row that needs the owner's hand: a problem only they can fix (E11). */
export function needsYou(row: SectionRow): boolean {
  return !isDriven(row) && troubled(row);
}

/** A row whose session waits for the owner. */
export function isWaiting(row: SectionRow): boolean {
  return isDriven(row) ? row.status === "waiting_permission" : row.status === "waiting";
}

/** The searchable text of a row: name, issue, repo, branch, folder. */
export function searchText(row: SectionRow): string {
  if (isDriven(row)) return [row.title, row.workdir_label, row.project].join(" ");
  const { title, detail } = sessionIdentity(row);
  return [title, detail, row.label?.issue, row.issue, row.repo, row.label?.branch, row.project]
    .filter(Boolean)
    .join(" ");
}

/** Lower-case, accents stripped, so "sessoes" finds "sessões". */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function titleOf(row: SectionRow): string {
  return isDriven(row) ? (row.title ?? "Untitled session") : sessionIdentity(row).title;
}

export function StatusCell({ row }: { row: SectionRow }) {
  if (isDriven(row)) {
    const [status, label] = DRIVEN_BADGE[row.status];
    const reason = row.end_reason ? `${label} · ${row.end_reason.replace(/_/g, " ")}` : undefined;
    return <StatusBadge status={status} label={label} title={reason} />;
  }
  const [status, label] = badgeOf(row);
  if (row.end_inferred && !row.outcome)
    return (
      <StatusBadge
        status="ended"
        label="Ended"
        title="Ended · no end event was received (inferred)"
      />
    );
  return <StatusBadge status={status} label={label} />;
}

/** The session's name as a real link, then where it runs, on one line. */
export function SessionCell({ row, showProject }: { row: SectionRow; showProject: boolean }) {
  let title: string;
  let detail: string | null;
  let named = true;
  let chatTip: string | null = null;
  if (isDriven(row)) {
    title = row.title ?? "Untitled session";
    detail = showProject ? `${row.project} · ${row.workdir_label}` : row.workdir_label;
    chatTip = ["Started from hub web", modeLabel(row.mode), row.model].filter(Boolean).join(" · ");
  } else {
    const identity = sessionIdentity(row);
    title = identity.title;
    named = identity.named;
    detail = showProject
      ? [row.project, identity.detail].filter(Boolean).join(" · ")
      : identity.detail;
    if (row.agent_session_id) chatTip = "Started from hub web: opens the chat";
  }
  return (
    <span className="sl-session">
      <AppLink
        href={rowHref(row)}
        className={named ? "sl-session-title" : "sl-session-title ah-mono"}
        title={title}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        {title}
      </AppLink>
      {chatTip && (
        <Tooltip label={chatTip}>
          <span className="sl-chat-mark">
            <Icon name="message-square" size="sm" />
            <span className="ah-sr">Chat session</span>
          </span>
        </Tooltip>
      )}
      {detail && (
        <span className="sl-session-detail ah-mono ah-small ah-subtle" title={detail}>
          {detail}
        </span>
      )}
    </span>
  );
}

function Line({ icon, tone, children }: { icon?: IconName; tone?: string; children: ReactNode }) {
  const text = typeof children === "string" ? children : undefined;
  return (
    <span className="sl-doing" style={tone ? { color: tone } : undefined} title={text}>
      {icon && <Icon name={icon} size="sm" />}
      <span style={ONE_LINE}>{children}</span>
    </span>
  );
}

/** What the session is doing, or why it needs the owner: one line, first match wins. */
export function DoingNow({ row }: { row: SectionRow }) {
  const now = useNow(isOpen(row) ? 15_000 : 3_600_000);
  if (isDriven(row)) {
    const ask = row.open_permission;
    if (row.status === "waiting_permission")
      return (
        <Line icon="hand">
          {ask
            ? `${ask.tool}: ${ask.summary} · ${fmtAgo(since(ask.asked_at, now))}`
            : "Asks for a permission"}
        </Line>
      );
    if (row.status === "running") return <Line icon="message-square">Working on a turn</Line>;
    if (row.status === "idle")
      return <Line icon="message-square">Ready for your next message</Line>;
    return <span className="ah-subtle">—</span>;
  }
  if (troubled(row))
    return (
      <Line icon="circle-x" tone="var(--failed)">
        {problemsLine(row) ?? "Needs you"}
      </Line>
    );
  if (row.status === "waiting") {
    const reason = row.waiting_reason ?? "Waiting for you";
    const guard = row.waiting_reason === "Guard ask" ? " · no timeout" : "";
    return (
      <Line icon="hand">{`${reason} · ${fmtAgo(since(row.last_activity_at, now))}${guard}`}</Line>
    );
  }
  const tool: IconName = row.last_tool ? (TOOL_ICON[row.last_tool] ?? "terminal") : "activity";
  if (row.status === "live") return <Line icon={tool}>{row.last_action ?? "Starting"}</Line>;
  if (row.status === "idle") {
    if (row.agent_session_id) return <Line icon="message-square">Ready for your next message</Line>;
    return (
      <Line icon={tool}>
        {`Last: ${row.last_action ?? "no tool call yet"} · ${fmtAgo(since(row.last_activity_at, now))}`}
      </Line>
    );
  }
  if (row.failing_notice) return <Line icon="circle-x">{row.failing_notice}</Line>;
  const problems = problemsLine(row);
  if (problems) return <span className="ah-muted sl-doing">{problems}</span>;
  if (row.outcome === "error" && row.last_action) return <Line icon={tool}>{row.last_action}</Line>;
  return <span className="ah-subtle">—</span>;
}

export function IssueCell({ row }: { row: SectionRow }) {
  if (isDriven(row)) return null;
  const issue = row.label?.issue ?? row.issue ?? null;
  const runTip = row.run_id
    ? `Run ${row.run_id}${row.step ? ` · step ${row.step}` : ""}${row.attempt ? ` · attempt ${String(row.attempt)}` : ""}`
    : undefined;
  if (issue)
    return runTip ? (
      <Tooltip label={runTip}>
        <IssueLink id={issue} />
      </Tooltip>
    ) : (
      <IssueLink id={issue} />
    );
  if (row.run_id)
    return (
      <Tooltip label={runTip}>
        <span className="ah-mono ah-small ah-subtle">run {short(row.run_id)}</span>
      </Tooltip>
    );
  return null;
}

const startOf = (row: SectionRow) => (isDriven(row) ? row.created_at : row.started_at);
const isOpen = (row: SectionRow) =>
  isDriven(row) ? row.status !== "ended" && row.status !== "failed" : row.status !== "ended";

/** When it started: "12 min ago" within a day, else the date and time; the other form on hover. */
export function StartedCell({ row, tz }: { row: SectionRow; tz: Tz }) {
  const iso = startOf(row);
  const now = useNow(60_000);
  const age = since(iso, now);
  const absolute = `${new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })} ${fmtClock(iso, tz)}`;
  return (
    <time dateTime={iso} title={age < 86_400 ? absolute : fmtAgo(age)} className="ah-small">
      {age < 86_400 ? (age < 60 ? "just now" : fmtAgo(age)) : absolute}
    </time>
  );
}

function RunningFor({ start }: { start: string }) {
  const now = useNow(1000);
  return <>{fmtDuration((now - Date.parse(start)) / 1000)}</>;
}

export function DurationCell({ row }: { row: SectionRow }) {
  const start = startOf(row);
  const end = row.ended_at;
  if (end) return <>{fmtDuration((Date.parse(end) - Date.parse(start)) / 1000)}</>;
  if (!isOpen(row)) return <span className="ah-subtle">—</span>;
  return <RunningFor start={start} />;
}

export function CostCell({ row }: { row: SectionRow }) {
  if (isDriven(row)) {
    return row.cost_usd ? (
      <Money value={row.cost_usd} />
    ) : (
      <span className="ah-subtle" title="Cost appears after the first turn ends.">
        —
      </span>
    );
  }
  if (row.cost_usd === null)
    return (
      <span className="ah-subtle" title={row.cost_unknown_reason ?? "Cost unknown."}>
        —
      </span>
    );
  return <Money value={row.cost_usd} />;
}

function tokensOf(row: SectionRow) {
  return isDriven(row) ? (row.usage ?? null) : row.tokens;
}

export function TokensCell({ row }: { row: SectionRow }) {
  const t = tokensOf(row);
  if (!t) return <span className="ah-subtle">—</span>;
  const tip = `Input ${fmtInt(t.input)} · output ${fmtInt(t.output)} · cache read ${fmtInt(t.cache_read)} · cache write ${fmtInt(t.cache_write)}`;
  return <span title={tip}>{fmtTokens(t.input + t.output + t.cache_read + t.cache_write)}</span>;
}

export function TurnsCell({ row }: { row: SectionRow }) {
  if (isDriven(row))
    return (
      <span className="ah-subtle" title="Counted once Claude Code's transcript reaches agent-hub.">
        —
      </span>
    );
  return <>{fmtInt(row.turns)}</>;
}

/** The row's visible action: Answer when it waits, Open chat for a chat, else Open; plus Resume. */
export function ActionCell({ row, resume }: { row: SectionRow; resume: ReactNode }) {
  const title = titleOf(row);
  let href = rowHref(row);
  let label = isChat(row) ? "Open chat" : "Open";
  if (isWaiting(row)) {
    label = "Answer";
    if (!isDriven(row)) href = waitingLink(row).href;
  }
  return (
    <span className="sl-actions">
      {resume}
      <AppLink
        href={href}
        className={label === "Answer" ? "ah-btn ah-btn-sm ah-btn-primary" : "ah-btn ah-btn-sm"}
        aria-label={`${label} ${title}`}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        {label}
      </AppLink>
    </span>
  );
}

/** Where Enter or `o` takes the owner from a row. */
export function openHref(row: SectionRow): string {
  if (isWaiting(row) && !isDriven(row)) return waitingLink(row).href;
  return rowHref(row);
}
