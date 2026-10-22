import { useMemo, useState } from "react";

import {
  AppLink,
  Icon,
  IconButton,
  Skeleton,
  ticketName,
  type TicketLookup,
} from "../../components";
import { useApi } from "../../lib/api";
import { cx } from "../../lib/cx";
import { useScope } from "../../lib/scope";
import { readStored, writeStored } from "../../lib/storage";
import { useTicketLookup } from "../features/queries";
import { agentSessionHref } from "../sessions-list/control";
import { useAgentSessions, type AgentSession, type Session } from "../sessions-list/queries";
import { AGENT_STATUS } from "./SessionStatus";

/** Whether the rail is folded to its strip, kept in this browser. */
export const RAIL_KEY = "ah.chat.rail";
/** How many ended sessions "Recent" lists. */
const RECENT = 20;
/** How many observed sessions are read for their tickets, newest first. */
const SESSIONS_READ = 200;

/** The ticket an observed session works on, as the tracker writes it (`ACME-12`). */
function issueOf(session: Session): string | null {
  const issue = session.label?.issue ?? session.issue ?? null;
  return issue === null ? null : issue.toUpperCase();
}

export interface RailGroup {
  id: "needs" | "active" | "recent";
  label: string;
  sessions: AgentSession[];
}

/** What a session is about: its ticket and the feature that plans it (as chips), and the name its
 * ticket gives it (`ACME-12: Export orders as CSV`), as the chat's header names it. */
export interface RailTags {
  ticket: string | null;
  feature: string | null;
  name: string | null;
}

const NO_TAGS: RailTags = { ticket: null, feature: null, name: null };

/** A session's name in one line, as the chat's header says it: its ticket's name, else Claude
 * Code's title, else its last prompt. */
export function railName(session: AgentSession, tags: RailTags = NO_TAGS): string {
  const text = (tags.name ?? session.title ?? session.last_prompt ?? "")
    .replace(/\s+/g, " ")
    .trim();
  return text || "Untitled session";
}

/**
 * The sessions to switch to: the ones waiting on you first, then the ones still open, then the
 * newest ended ones. Newest first in each; `filter` matches the name, the project, the folder and
 * the tags.
 */
export function railGroups(
  sessions: readonly AgentSession[],
  filter: string,
  tagsOf: (session: AgentSession) => RailTags = () => NO_TAGS,
): RailGroup[] {
  const words = filter.trim().toLowerCase();
  const shown = (
    words
      ? sessions.filter((s) => {
          const tags = tagsOf(s);
          return [railName(s, tags), s.project, s.workdir_label, tags.ticket, tags.feature].some(
            (text) => text?.toLowerCase().includes(words),
          );
        })
      : [...sessions]
  ).sort((a, b) => b.updated_at.localeCompare(a.updated_at));
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

/** The tags of each driven session, from its observed twin's ticket and the hub's features. */
export function railTagsOf(
  observed: readonly Session[],
  tickets: TicketLookup,
): (session: AgentSession) => RailTags {
  const twins = new Map(observed.map((session) => [session.id, session]));
  return (session) => {
    const twin = session.observed_session_id ? twins.get(session.observed_session_id) : undefined;
    const ticket = twin ? issueOf(twin) : null;
    if (!twin || !ticket) return NO_TAGS;
    return {
      ticket,
      feature: tickets.get(ticket)?.slug ?? null,
      name: ticketName(twin.label, tickets),
    };
  };
}

/** The status as a dot, with its word for screen readers: live pulses, ended has none. */
function StatusDot({ session }: { session: AgentSession }) {
  const look = AGENT_STATUS[session.status];
  return (
    <>
      <span
        className={cx(
          "as-rail-dot",
          session.status !== "ended" && "ah-dot",
          `as-rail-dot-${look.status}`,
          session.status === "running" && "ah-pulse",
        )}
        title={look.label}
        aria-hidden
      />
      <span className="ah-sr">{look.label}: </span>
    </>
  );
}

function RailRow({
  session,
  tags,
  current,
  showProject,
}: {
  session: AgentSession;
  tags: RailTags;
  current: boolean;
  showProject: boolean;
}) {
  const name = railName(session, tags);
  const chips = [
    showProject ? { kind: "project", text: session.project } : null,
    tags.ticket ? { kind: "ticket", text: tags.ticket } : null,
    tags.feature ? { kind: "feature", text: tags.feature } : null,
  ].filter((chip): chip is { kind: string; text: string } => chip !== null);
  return (
    <li>
      <AppLink
        href={agentSessionHref(session.id)}
        className={cx("as-rail-row", current && "as-rail-current")}
        aria-current={current ? "page" : undefined}
        title={`${name}\n${session.project} · ${session.workdir_label} · ${AGENT_STATUS[session.status].label}`}
      >
        <StatusDot session={session} />
        <span className="as-rail-text">
          <span className="as-rail-name">{name}</span>
          {chips.length > 0 && (
            <span className="as-rail-tags">
              {chips.map((chip) => (
                <span key={chip.kind} className={`as-rail-tag as-rail-tag-${chip.kind}`}>
                  {chip.text}
                </span>
              ))}
            </span>
          )}
        </span>
      </AppLink>
    </li>
  );
}

/**
 * The chat's left rail: every session hub web drives, one click from its chat, so you switch
 * between agents as you switch conversations in a chat app. Each row says what the session is
 * about (its ticket and feature); the rail folds to a strip of status dots.
 */
export function SessionRail({ current }: { current: string }) {
  const [scope] = useScope();
  const sessions = useAgentSessions(scope);
  const observed = useApi("/api/v1/sessions", {
    query: {
      ...(scope ? { project: scope } : {}),
      limit: SESSIONS_READ,
      sort: "-last_activity_at",
    },
  });
  const tickets = useTicketLookup(scope);
  const [open, setOpen] = useState(() => readStored(RAIL_KEY) !== "closed");
  const [filter, setFilter] = useState("");
  const items = sessions.data?.items;
  const tagsOf = useMemo(
    () => railTagsOf(observed.data?.items ?? [], tickets),
    [observed.data, tickets],
  );
  const groups = useMemo(() => railGroups(items ?? [], filter, tagsOf), [items, filter, tagsOf]);
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
                title={`${railName(session, tagsOf(session))} · ${AGENT_STATUS[session.status].label}`}
              >
                <StatusDot session={session} />
                <span className="ah-sr">{railName(session, tagsOf(session))}</span>
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
        <Icon name="search" size="sm" />
        <span className="ah-sr">Filter sessions</span>
        <input
          type="search"
          className="ah-input"
          value={filter}
          placeholder="Filter"
          onChange={(event) => {
            setFilter(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Escape" || filter === "") return;
            event.preventDefault();
            setFilter("");
          }}
        />
      </label>
      <div className="as-rail-scroll">
        {sessions.isPending && (
          <div style={{ padding: 8 }}>
            <Skeleton lines={6} />
          </div>
        )}
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
                  tags={tagsOf(session)}
                  current={session.id === current}
                  showProject={scope === null}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </nav>
  );
}
