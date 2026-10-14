import {
  AppLink,
  AsOfStamp,
  IconButton,
  Icon,
  IdChip,
  IssueLink,
  StatusBadge,
  Time,
  Tooltip,
  copyText,
  sessionIdentity,
  useCopied,
  OutsideLink,
} from "../../components";
import { fmtAgo, fmtClock, fmtDuration, fmtInt, fmtMoney } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { agentSessionHref } from "../sessions-list/AgentSessionList";
import type { Session } from "./queries";
import { durationOf, isOpen, statusOf, tokensText } from "./session-status";

const short = (id: string) => id.replace(/-/g, "").slice(0, 8);

/** "Main agent · 3 subagents: Explore ×2, reviewer"; null when only the main agent acted (S2). */
export function actorsLine(actors: Session["actors"]): string | null {
  const types = new Map<string, number>();
  for (const actor of actors) {
    if (actor.kind !== "subagent") continue;
    const type = actor.type ?? "subagent";
    types.set(type, (types.get(type) ?? 0) + 1);
  }
  const total = [...types.values()].reduce((sum, n) => sum + n, 0);
  if (total === 0) return null;
  const list = [...types].map(([type, n]) => (n > 1 ? `${type} ×${String(n)}` : type)).join(", ");
  return `Main agent · ${String(total)} ${total === 1 ? "subagent" : "subagents"}: ${list}`;
}

export interface HeaderProps {
  session: Session;
  now: number;
  /** The time of the last data when the stream or collector is down, else null. */
  staleSince: Date | null;
}

/** Who did what for which work, how it ended, what it cost (spec 10, "Header"). */
export function Header({ session, now, staleSince }: HeaderProps) {
  const { tz } = usePreferences();
  const [copied, markCopied] = useCopied();
  const status = statusOf(session, now);
  const tokens = tokensText(session.tokens);
  const open = isOpen(session);
  const subagent = Boolean(session.parent_session_id);
  const segments = session.segments.length;
  const { title } = sessionIdentity(session);
  const label = session.label ?? null;
  const where = [label?.repo ?? session.repo, label?.branch].filter(Boolean).join(" · ") || "—";
  const actors = actorsLine(session.actors);
  const crumbs = [
    { label: "Portfolio", href: "/" },
    { label: session.project, href: `/projects/${encodeURIComponent(session.project)}` },
    ...(session.run_id
      ? [
          {
            label: `Run ${session.issue ?? short(session.run_id)}`,
            href: `/runs/${encodeURIComponent(session.run_id)}`,
          },
        ]
      : []),
    ...(session.parent_session_id
      ? [
          {
            label: `Session ${short(session.parent_session_id)}`,
            href: `/sessions/${encodeURIComponent(session.parent_session_id)}`,
          },
        ]
      : []),
    { label: `Session ${short(session.id)}` },
  ];
  const runHref = session.run_id
    ? `/runs/${encodeURIComponent(session.run_id)}${session.step ? `?step=${encodeURIComponent(session.step)}${session.attempt ? `&attempt=${String(session.attempt)}` : ""}` : ""}`
    : null;
  const costTitle =
    session.cost_usd === null
      ? (session.cost_unknown_reason ?? "Cost unknown")
      : `${fmtMoney(session.cost_usd, 4)} · Estimated from transcript`;
  return (
    <div className="sd-header">
      <Breadcrumbs items={crumbs} />
      <div className="ah-row ah-wrap" style={{ gap: 12, marginTop: 10 }}>
        <Icon
          name={subagent ? "network" : "square-terminal"}
          size="lg"
          style={{ color: "var(--text-subtle)" }}
        />
        <h1 className="ah-h1 ah-mono" style={{ fontSize: 20 }}>
          {title}
        </h1>
        <StatusBadge status={status.status} label={status.label} title={status.title} />
        {open && (
          <span className="ah-small ah-subtle">
            last action {fmtAgo((now - Date.parse(session.last_activity_at)) / 1000)}
          </span>
        )}
        {staleSince && (
          <span title={`Live updates paused: collector offline since ${fmtClock(staleSince, tz)}.`}>
            <AsOfStamp stale time={fmtClock(staleSince, tz)} />
          </span>
        )}
        {session.issue && !label?.issue && <IssueLink id={session.issue} />}
        <span className="ah-grow" />
        {session.agent_session_id && (
          <AppLink
            className="ah-row ah-small"
            href={agentSessionHref(session.agent_session_id)}
            style={{ gap: 4, fontWeight: 500 }}
          >
            <Icon name="message-square" size="sm" />
            Open chat
          </AppLink>
        )}
        {runHref && (
          <AppLink className="ah-row ah-small" href={runHref} style={{ gap: 4 }}>
            <Icon name="route" size="sm" />
            Run {session.issue ?? short(session.run_id ?? "")}
            {session.step ? ` › ${session.step}` : ""}
            {session.attempt ? ` · attempt ${String(session.attempt)}` : ""}
          </AppLink>
        )}
        {session.pr ? (
          <OutsideLink className="ah-row ah-small" href={session.pr.url} style={{ gap: 4 }}>
            <Icon name="git-pull-request" size="sm" />
            PR #{session.pr.number} {session.pr.state}
            <Icon name="arrow-up-right" size="sm" />
          </OutsideLink>
        ) : null}
        <IconButton
          icon={copied ? "check" : "link"}
          label={copied ? "Link copied" : "Copy link to this session (y)"}
          onClick={() => {
            copyText(`${window.location.origin}/sessions/${encodeURIComponent(session.id)}`);
            markCopied();
          }}
        />
      </div>
      <div className="ah-row ah-wrap ah-small sd-meta">
        <span>
          {session.project} ›{" "}
          <b className="ah-mono" style={{ color: "var(--text)", fontWeight: 500 }}>
            {where}
          </b>
        </span>
        {actors && (
          <span className="ah-row" style={{ gap: 4 }}>
            <Icon name="network" size="sm" />
            {actors}
          </span>
        )}
        <IdChip id={session.id} kind="session " />
        <span>
          <span className="ah-subtle">Started </span>
          <Time iso={session.started_at} absolute />
        </span>
        <span>
          <span className="ah-subtle">Duration </span>
          <span className="ah-num" style={{ fontWeight: 400 }}>
            {fmtDuration(durationOf(session, now))}
            {open ? " · running" : ""}
          </span>
        </span>
        <span>
          <span className="ah-subtle">Model </span>
          <span className="ah-mono">{session.model ?? "—"}</span>
        </span>
        <span>
          <span className="ah-subtle">Turns </span>
          <span className="ah-num">{fmtInt(session.turns)}</span>
        </span>
        <Tooltip label={tokens.title}>
          {/* Focusable so keyboard users reach the exact split in its tooltip. */}
          {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
          <span tabIndex={0}>
            <span className="ah-subtle">Tokens </span>
            <span className="ah-num">{tokens.text}</span>
          </span>
        </Tooltip>
        <Tooltip label={costTitle}>
          {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
          <span tabIndex={0}>
            <span className="ah-subtle">Cost </span>
            <span className="ah-num">{fmtMoney(session.cost_usd, 4)}</span>
            <span className="ah-subtle"> · estimated</span>
          </span>
        </Tooltip>
        <span className="ah-row" style={{ gap: 4 }}>
          <Icon name="clock" size="sm" />
          Transcript: {session.has_transcript ? "local file" : "—"}
        </span>
        {segments > 1 && (
          <Tooltip
            label={session.segments
              .map(
                (segment) =>
                  `Segment ${String(segment.index + 1)}: ${fmtClock(segment.started_at, tz)}–${segment.ended_at ? fmtClock(segment.ended_at, tz) : "now"}${segment.end_reason ? ` (${segment.end_reason})` : ""}`,
              )
              .join(" · ")}
          >
            {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
            <span className="ah-row" style={{ gap: 4 }} tabIndex={0}>
              <Icon name="rotate-ccw" size="sm" />
              {segments} segments · resumed{" "}
              {segments === 2 ? "once" : `${String(segments - 1)} times`}
            </span>
          </Tooltip>
        )}
        {(session.guard_denials > 0 || session.errors > 0) && (
          <span className="ah-row" style={{ gap: 4 }}>
            <Icon name="shield-x" size="sm" style={{ color: "var(--guard)" }} />
            {session.guard_denials} guard {session.guard_denials === 1 ? "event" : "events"} ·{" "}
            {session.errors} {session.errors === 1 ? "error" : "errors"}
          </span>
        )}
      </div>
    </div>
  );
}
