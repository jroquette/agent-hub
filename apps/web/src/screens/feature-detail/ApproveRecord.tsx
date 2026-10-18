import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import { Button, Icon, MenuItem, Popover } from "../../components";
import { ApiProblem, apiPost, useApi } from "../../lib/api";
import { agentSessionHref } from "../sessions-list/control";

type AgentSession = components["schemas"]["AgentSession"];

/** How many sessions the picker lists besides the ones that worked on the feature. */
const OTHER_SESSIONS = 8;

/** The Discuss panel's conversation about this feature, which is not where the work happens. */
function discussSessionId(project: string, slug: string): string | null {
  try {
    return window.localStorage.getItem(`ah.discuss.session.feature:${project}:${slug}`);
  } catch {
    return null;
  }
}

const pickedKey = (project: string, slug: string) => `ah.approve.session.${project}:${slug}`;

/** The session the owner last sent this feature's approvals to, remembered per feature. */
function readPicked(project: string, slug: string): string | null {
  try {
    return window.localStorage.getItem(pickedKey(project, slug));
  } catch {
    return null;
  }
}

function writePicked(project: string, slug: string, id: string) {
  try {
    window.localStorage.setItem(pickedKey(project, slug), id);
  } catch {
    // Without storage the pick lasts until the page reloads.
  }
}

/** A session's name in one line: its title, else its last prompt. */
export function sessionName(session: AgentSession): string {
  const text = session.title ?? session.last_prompt ?? "";
  const line = text.replace(/\s+/g, " ").trim();
  if (!line) return "Untitled session";
  return line.length > 60 ? `${line.slice(0, 59)}…` : line;
}

/**
 * The sessions that worked on this feature, most recent first: the ones that changed a file of
 * its record folder, or whose title, last prompt or last reply names the feature or a ticket.
 */
export function featureSessions(
  sessions: readonly AgentSession[],
  slug: string,
  tickets: readonly string[],
  exclude: string | null,
): AgentSession[] {
  const folder = `features/${slug}/`;
  const names = [slug, ...tickets];
  // The list route leaves `changed_files` out (only one session's read carries it).
  const touched = (s: AgentSession) => {
    const files = (s as Partial<AgentSession>).changed_files ?? [];
    return files.some((f) => f.path.includes(folder));
  };
  const named = (s: AgentSession) =>
    [s.title, s.last_prompt, s.last_reply].some(
      (text) => text != null && names.some((name) => text.includes(name)),
    );
  return sessions
    .filter((s) => s.id !== exclude && s.kind === "local" && (touched(s) || named(s)))
    .sort(
      (a, b) => Number(touched(b)) - Number(touched(a)) || b.updated_at.localeCompare(a.updated_at),
    );
}

/** The message the approval sends: which record, and that the work goes on from it. */
export function approvalMessage(record: string, path: string): string {
  return [
    `I approve the ${record} (\`${path}\`) as it is now.`,
    "Treat it as approved and go on with the next step of the feature.",
  ].join(" ");
}

/**
 * Approve a feature record (spec, research, plan) from its tab: the approval goes as a message to
 * the session that worked on the feature, so that session goes on from where it asked. The target
 * is the most recent session that touched the feature; the arrow picks another one.
 */
export function ApproveRecord({
  project,
  slug,
  record,
  path,
  tickets,
}: {
  project: string;
  slug: string;
  record: string;
  path: string;
  tickets: readonly string[];
}) {
  const sessions = useApi(
    "/api/v1/agent-sessions",
    { query: { project } },
    { retry: false, refetchInterval: 15_000 },
  );
  const [chosen, setChosen] = useState<string | null>(() => readPicked(project, slug));
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<AgentSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wrap = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: PointerEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Without session control (no cookie, the container) there is nowhere to send it.
  if (!sessions.isSuccess) return null;
  const all = sessions.data.items.filter((s) => s.kind === "local");
  const related = featureSessions(all, slug, tickets, discussSessionId(project, slug));
  const others = all.filter((s) => !related.some((r) => r.id === s.id)).slice(0, OTHER_SESSIONS);
  const target = all.find((s) => s.id === chosen) ?? related[0] ?? null;

  const approve = () => {
    if (!target) {
      setOpen(true);
      return;
    }
    setBusy(true);
    setError(null);
    void apiPost(
      "/api/v1/agent-sessions/{agent_session_id}/messages",
      { text: approvalMessage(record, path) },
      { path: { agent_session_id: target.id } },
    )
      .then(() => {
        writePicked(project, slug, target.id);
        setSent(target);
      })
      .catch((cause: unknown) => {
        setError(
          cause instanceof ApiProblem
            ? (cause.detail ?? cause.title)
            : "The approval could not be sent.",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };

  if (sent) {
    return (
      <div className="ah-row ah-wrap ah-small" style={{ gap: 8 }} role="status">
        <Icon name="check" size="sm" style={{ color: "var(--done)" }} />
        <span>
          Approval of the {record} sent to <b>{sessionName(sent)}</b>.
        </span>
        <Link to={agentSessionHref(sent.id)}>Open session</Link>
      </div>
    );
  }

  const pick = (id: string) => () => {
    setChosen(id);
    writePicked(project, slug, id);
    setOpen(false);
  };
  const item = (s: AgentSession) => (
    <MenuItem
      key={s.id}
      icon="message-square"
      selected={s.id === target?.id}
      onClick={pick(s.id)}
      hint={<span className="ah-subtle ah-small">{s.status}</span>}
    >
      {sessionName(s)}
    </MenuItem>
  );

  return (
    <div className="ah-row ah-wrap ah-small" style={{ gap: 8 }}>
      <Button
        size="sm"
        variant="primary"
        icon="check"
        disabled={busy}
        onClick={approve}
        title={
          target
            ? `Send "${approvalMessage(record, path)}" to ${sessionName(target)}`
            : "Pick the session that worked on this feature"
        }
      >
        Approve {record}
      </Button>
      <span ref={wrap} style={{ position: "relative" }} className="ah-row">
        <button
          type="button"
          className="ah-btn ah-btn-ghost ah-btn-sm"
          aria-haspopup="true"
          aria-expanded={open}
          aria-label={`Approval goes to: ${target ? sessionName(target) : "no session picked"}`}
          onClick={() => {
            setOpen(!open);
          }}
        >
          <span className="ah-muted">to</span>
          <span>{target ? sessionName(target) : "pick a session"}</span>
          <Icon name="chevron-down" size="sm" />
        </button>
        <Popover
          open={open}
          label="Session that gets the approval"
          style={{ top: 30, left: 0, minWidth: 320, maxWidth: 440 }}
        >
          {related.length > 0 && (
            <div className="ah-subtle ah-small" style={{ padding: "6px 10px" }}>
              Worked on {slug}
            </div>
          )}
          {related.map(item)}
          {others.length > 0 && (
            <div className="ah-subtle ah-small" style={{ padding: "6px 10px" }}>
              Other sessions in {project}
            </div>
          )}
          {others.map(item)}
          {all.length === 0 && (
            <div className="ah-muted ah-small" style={{ padding: "6px 10px" }}>
              No session in {project} yet.
            </div>
          )}
        </Popover>
      </span>
      {error && (
        <span role="alert" style={{ color: "var(--failed)" }}>
          {error}
        </span>
      )}
    </div>
  );
}
