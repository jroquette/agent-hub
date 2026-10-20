import { useMemo, useRef, useState } from "react";

import { AppLink, Button, Icon, IconButton, Skeleton } from "../../components";
import { useNow } from "../../lib/clock";
import { cx } from "../../lib/cx";
import { fmtAgo } from "../../lib/format";
import { useScope } from "../../lib/scope";
import { readStored, writeStored } from "../../lib/storage";
import { agentSessionHref, sessionControlUnavailable } from "../sessions-list/control";
import {
  useAgentCapabilities,
  useAgentSessions,
  useProjects,
  useWorkdirs,
  type AgentSession,
} from "../sessions-list/queries";
import { StartSessionDialog } from "../sessions-list/StartSessionDialog";
import { AGENT_STATUS } from "./SessionStatus";

/** Whether the rail is folded to its strip, kept in this browser. */
export const RAIL_KEY = "ah.chat.rail";
/** How many sessions the "Older" group lists before "Show all". */
const OLDER = 20;
const DAY = 86_400_000;

export interface RailGroup {
  id: "needs" | "today" | "yesterday" | "week" | "older";
  label: string;
  sessions: AgentSession[];
}

/** A session's name in one line: Claude Code's title, else its last prompt. */
export function railName(session: AgentSession): string {
  const text = (session.title ?? session.last_prompt ?? "").replace(/\s+/g, " ").trim();
  return text || "Untitled session";
}

/**
 * The sessions to switch to, as a chat app lists conversations: the ones waiting on you pinned
 * first, then the rest by when they last moved (today, yesterday, the previous 7 days, older), newest
 * first. `filter` matches the name, the project and the folder; `now` is the local clock.
 */
export function railGroups(
  sessions: readonly AgentSession[],
  filter: string,
  now: number,
): RailGroup[] {
  const words = filter.trim().toLowerCase();
  const shown = (
    words
      ? sessions.filter((s) =>
          [railName(s), s.project, s.workdir_label].some((text) =>
            text.toLowerCase().includes(words),
          ),
        )
      : [...sessions]
  ).sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  const today = midnight.getTime();
  const groups: RailGroup[] = [
    { id: "needs", label: "Waiting for you", sessions: [] },
    { id: "today", label: "Today", sessions: [] },
    { id: "yesterday", label: "Yesterday", sessions: [] },
    { id: "week", label: "Previous 7 days", sessions: [] },
    { id: "older", label: "Older", sessions: [] },
  ];
  for (const session of shown) {
    const at = Date.parse(session.updated_at);
    const index =
      session.status === "waiting_permission"
        ? 0
        : at >= today
          ? 1
          : at >= today - DAY
            ? 2
            : at >= today - 7 * DAY
              ? 3
              : 4;
    groups[index]?.sessions.push(session);
  }
  return groups.filter((group) => group.sessions.length > 0);
}

/** "now", "5m", "3h", "2d": the age a list of conversations shows at its right edge. */
function shortAge(ms: number): string {
  const seconds = Math.max(0, ms / 1000);
  if (seconds < 60) return "now";
  return fmtAgo(seconds).replace(" ago", "").replace(/\s+/g, "");
}

/** The status as an icon, never colour alone: live pulses, waiting is a hand, failed a cross. */
function StatusMark({ session }: { session: AgentSession }) {
  const label = AGENT_STATUS[session.status].label;
  const mark =
    session.status === "running" ? (
      <span className="as-rail-live ah-dot ah-pulse" aria-hidden />
    ) : session.status === "waiting_permission" ? (
      <Icon name="hand" size="sm" className="as-rail-waiting" />
    ) : session.status === "failed" ? (
      <Icon name="circle-x" size="sm" className="as-rail-failed" />
    ) : session.status === "idle" ? (
      <Icon name="moon" size="sm" className="as-rail-idle" />
    ) : (
      <span className="as-rail-none" aria-hidden />
    );
  return (
    <span className="as-rail-mark" title={label}>
      {mark}
      <span className="ah-sr">{label}: </span>
    </span>
  );
}

function RailRow({
  session,
  current,
  now,
}: {
  session: AgentSession;
  current: boolean;
  now: number;
}) {
  const name = railName(session);
  const ended = session.status === "ended" || session.status === "failed";
  return (
    <li>
      <AppLink
        href={agentSessionHref(session.id)}
        className={cx("as-rail-row", ended && "as-rail-ended")}
        aria-current={current ? "page" : undefined}
        title={`${name}\n${session.project} · ${session.workdir_label} · ${AGENT_STATUS[session.status].label}`}
      >
        <StatusMark session={session} />
        <span className="as-rail-name">{name}</span>
        <span className="as-rail-age ah-num">{shortAge(now - Date.parse(session.updated_at))}</span>
      </AppLink>
    </li>
  );
}

/** "New session" in the project on screen: the same dialog as the sessions list. */
function NewSession({ project }: { project: string | null }) {
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const ready = capabilities.data !== undefined && unavailable === null && project !== null;
  const workdirs = useWorkdirs(project, ready);
  const projects = useProjects();
  const [open, setOpen] = useState(false);
  const reason = unavailable
    ? `${unavailable.title}.`
    : project === null
      ? "Pick a project to start a session in."
      : !ready || workdirs.isPending
        ? "Checking whether this machine can drive Claude…"
        : null;
  return (
    <>
      <Button
        size="sm"
        icon="plus"
        className="as-rail-new"
        disabled={reason !== null}
        title={reason ?? `Start a session in ${project ?? ""}`}
        onClick={() => {
          setOpen(true);
        }}
      >
        New session
      </Button>
      {open && project !== null && capabilities.data && (
        <StartSessionDialog
          project={project}
          projects={projects.data?.items.map((p) => p.name)}
          workdirs={workdirs.data?.items}
          capabilities={capabilities.data}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}

/**
 * The chat's left rail: every session hub web drives, one click from its chat, so you switch
 * between agents as you switch conversations in a chat app. Folds to a strip of status marks.
 */
export function SessionRail({ current }: { current: string }) {
  const [scope] = useScope();
  const sessions = useAgentSessions(scope);
  const [open, setOpen] = useState(() => readStored(RAIL_KEY) !== "closed");
  const [filter, setFilter] = useState("");
  const filterBox = useRef<HTMLInputElement>(null);
  const now = useNow(30_000);
  const items = sessions.data?.items;
  const groups = useMemo(() => railGroups(items ?? [], filter, now), [items, filter, now]);
  const project = scope ?? items?.find((s) => s.id === current)?.project ?? null;
  const toggle = () => {
    writeStored(RAIL_KEY, open ? "closed" : "open");
    setOpen(!open);
  };

  if (!open) {
    const live = (items ?? []).filter((s) => s.status !== "ended" && s.status !== "failed");
    return (
      <nav className="as-rail as-rail-folded" aria-label="Sessions">
        <IconButton icon="panel-left" label="Show sessions" size="sm" onClick={toggle} />
        <ul className="as-rail-strip">
          {live.slice(0, 12).map((session) => (
            <li key={session.id}>
              <AppLink
                href={agentSessionHref(session.id)}
                className="as-rail-strip-item"
                aria-current={session.id === current ? "page" : undefined}
                title={`${railName(session)} · ${AGENT_STATUS[session.status].label}`}
              >
                <StatusMark session={session} />
                <span className="ah-sr">{railName(session)}</span>
              </AppLink>
            </li>
          ))}
        </ul>
      </nav>
    );
  }

  const total = items?.length ?? 0;
  return (
    <nav className="as-rail" aria-label="Sessions">
      <div className="as-rail-head">
        <NewSession project={project} />
        <span className="ah-grow" />
        <IconButton icon="panel-left" label="Hide sessions" size="sm" onClick={toggle} />
      </div>
      <label className="as-rail-filter">
        <Icon name="search" size="sm" />
        <span className="ah-sr">Filter sessions</span>
        <input
          ref={filterBox}
          type="search"
          className="ah-input"
          value={filter}
          placeholder="Filter sessions"
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
          <div style={{ padding: "8px 8px" }}>
            <Skeleton lines={6} />
          </div>
        )}
        {sessions.isError && <p className="as-rail-empty">Sessions are not available here.</p>}
        {sessions.isSuccess && groups.length === 0 && (
          <p className="as-rail-empty">{filter ? "No session matches." : "No session yet."}</p>
        )}
        {groups.map((group) => {
          const list = group.id === "older" ? group.sessions.slice(0, OLDER) : group.sessions;
          return (
            <section key={group.id} aria-labelledby={`as-rail-${group.id}`}>
              <h2 id={`as-rail-${group.id}`} className="as-rail-group">
                {group.label}
              </h2>
              <ul className="as-rail-list">
                {list.map((session) => (
                  <RailRow
                    key={session.id}
                    session={session}
                    current={session.id === current}
                    now={now}
                  />
                ))}
              </ul>
            </section>
          );
        })}
        {sessions.isSuccess && total > 0 && (
          <AppLink href="/sessions" className="as-rail-all">
            Show all {total} sessions
            <Icon name="arrow-right" size="sm" />
          </AppLink>
        )}
      </div>
    </nav>
  );
}
