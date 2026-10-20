import { useMemo, useState } from "react";

import { AppLink, Icon, IconButton } from "../../components";
import { useNow } from "../../lib/clock";
import { cx } from "../../lib/cx";
import { fmtRelative } from "../../lib/format";
import { useScope } from "../../lib/scope";
import { readStored, writeStored } from "../../lib/storage";
import { agentSessionHref } from "../sessions-list/control";
import { useAgentSessions, type AgentSession } from "../sessions-list/queries";
import { AGENT_STATUS } from "./SessionStatus";

/** Whether the rail is folded to its strip, kept in this browser. */
export const RAIL_KEY = "ah.chat.rail";
/** How many ended sessions "Recent" lists. */
const RECENT = 20;

export interface RailGroup {
  id: "needs" | "active" | "recent";
  label: string;
  sessions: AgentSession[];
}

/** A session's name in one line: Claude Code's title, else its last prompt. */
export function railName(session: AgentSession): string {
  const text = (session.title ?? session.last_prompt ?? "").replace(/\s+/g, " ").trim();
  return text || "Untitled session";
}

/**
 * The sessions to switch to, as the chat apps list conversations: the ones waiting on you first,
 * then the ones still open, then the newest ended ones. Newest first in each; `filter` matches the
 * name, the project and the folder.
 */
export function railGroups(sessions: readonly AgentSession[], filter: string): RailGroup[] {
  const words = filter.trim().toLowerCase();
  const shown = words
    ? sessions.filter((s) =>
        [railName(s), s.project, s.workdir_label].some((text) =>
          text.toLowerCase().includes(words),
        ),
      )
    : [...sessions];
  shown.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const ended = (s: AgentSession) => s.status === "ended" || s.status === "failed";
  const groups: RailGroup[] = [
    {
      id: "needs",
      label: "Waiting for you",
      sessions: shown.filter((s) => s.status === "waiting_permission"),
    },
    {
      id: "active",
      label: "Open",
      sessions: shown.filter((s) => !ended(s) && s.status !== "waiting_permission"),
    },
    { id: "recent", label: "Recent", sessions: shown.filter(ended).slice(0, RECENT) },
  ];
  return groups.filter((group) => group.sessions.length > 0);
}

/** The status as a dot: live pulses, waiting is amber, idle is quiet, ended has none. */
function StatusDot({ session }: { session: AgentSession }) {
  const look = AGENT_STATUS[session.status];
  if (session.status === "ended") return <span className="as-rail-dot" aria-hidden />;
  return (
    <span
      className={cx(
        "as-rail-dot ah-dot",
        `as-rail-dot-${look.status}`,
        session.status === "running" && "ah-pulse",
      )}
      aria-hidden
    />
  );
}

function RailRow({
  session,
  current,
  showProject,
  now,
}: {
  session: AgentSession;
  current: boolean;
  showProject: boolean;
  now: number;
}) {
  const name = railName(session);
  const status = AGENT_STATUS[session.status].label;
  const age = fmtRelative(Math.max(0, (now - Date.parse(session.updated_at)) / 1000));
  return (
    <li>
      <AppLink
        href={agentSessionHref(session.id)}
        className={cx("as-rail-row", current && "as-rail-current")}
        aria-current={current ? "page" : undefined}
        title={`${name} · ${status}`}
      >
        <StatusDot session={session} />
        <span className="as-rail-text">
          <span className="as-rail-name">{name}</span>
          <span className="as-rail-meta">
            <span className="ah-sr">{status}, </span>
            {showProject ? `${session.project} · ` : ""}
            {age}
          </span>
        </span>
      </AppLink>
    </li>
  );
}

/**
 * The chat's left rail: every session hub web drives, one click from its chat, so you switch
 * between agents as you switch conversations in a chat app. Folds to a strip of status dots.
 */
export function SessionRail({ current }: { current: string }) {
  const [scope] = useScope();
  const sessions = useAgentSessions(scope);
  const [open, setOpen] = useState(() => readStored(RAIL_KEY) !== "closed");
  const [filter, setFilter] = useState("");
  const now = useNow(30_000);
  const items = sessions.data?.items;
  const groups = useMemo(() => railGroups(items ?? [], filter), [items, filter]);
  const toggle = () => {
    writeStored(RAIL_KEY, open ? "closed" : "open");
    setOpen(!open);
  };

  if (!open) {
    const live = groups.filter((g) => g.id !== "recent").flatMap((g) => g.sessions);
    return (
      <nav className="as-rail as-rail-folded" aria-label="Sessions">
        <IconButton icon="panel-left" label="Show sessions" size="sm" onClick={toggle} />
        <ul className="as-rail-strip">
          {live.slice(0, 12).map((session) => (
            <li key={session.id}>
              <AppLink
                href={agentSessionHref(session.id)}
                className={cx("as-rail-strip-item", session.id === current && "as-rail-current")}
                aria-current={session.id === current ? "page" : undefined}
                title={`${railName(session)} · ${AGENT_STATUS[session.status].label}`}
              >
                <StatusDot session={session} />
                <span className="ah-sr">{railName(session)}</span>
              </AppLink>
            </li>
          ))}
        </ul>
      </nav>
    );
  }

  return (
    <nav className="as-rail" aria-label="Sessions">
      <div className="as-rail-head">
        <b className="as-rail-title">Sessions</b>
        <span className="ah-grow" />
        <AppLink href="/sessions" className="ah-btn ah-btn-ghost ah-btn-sm" title="All sessions">
          All
        </AppLink>
        <IconButton icon="panel-left" label="Hide sessions" size="sm" onClick={toggle} />
      </div>
      <label className="as-rail-filter">
        <Icon name="text-search" size="sm" />
        <span className="ah-sr">Filter sessions</span>
        <input
          type="search"
          value={filter}
          placeholder="Filter"
          onChange={(event) => {
            setFilter(event.target.value);
          }}
        />
      </label>
      <div className="as-rail-scroll">
        {sessions.isError && <p className="as-rail-empty">Sessions are not available here.</p>}
        {sessions.isSuccess && groups.length === 0 && (
          <p className="as-rail-empty">
            {filter ? "No session matches." : "No other session yet."}
          </p>
        )}
        {groups.map((group) => (
          <section key={group.id} aria-labelledby={`as-rail-${group.id}`}>
            <h2 id={`as-rail-${group.id}`} className="as-rail-group">
              {group.label}
              <span className="ah-num"> {group.sessions.length}</span>
            </h2>
            <ul className="as-rail-list">
              {group.sessions.map((session) => (
                <RailRow
                  key={session.id}
                  session={session}
                  current={session.id === current}
                  showProject={scope === null}
                  now={now}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </nav>
  );
}
