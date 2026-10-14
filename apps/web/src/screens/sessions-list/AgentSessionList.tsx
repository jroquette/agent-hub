import "../agent-session/agent-session.css";

import { useId } from "react";

import type { components } from "../../api/schema";
import { AppLink, Banner, Button, Money, ProblemError, Time } from "../../components";
import type { ApiProblem } from "../../lib/api";
import { cx } from "../../lib/cx";
import { AgentStatusBadge } from "../agent-session/SessionStatus";
import { modeLabel } from "../agent-session/transcript";

type Schemas = components["schemas"];
export type AgentSession = Schemas["AgentSession"];
export type DriverCapabilities = Schemas["DriverCapabilities"];

/** The problem type of every agent-session route in the container (L2, E2). */
export const SESSIONS_OFF_TYPE = "urn:agent-hub:problem:agent-sessions-off";

/** Where the chat view of an agent session lives (a dot-free segment). */
export function agentSessionHref(id: string): string {
  return `/agent-sessions/${encodeURIComponent(id)}`;
}

export interface Unavailable {
  title: string;
  detail: string;
}

/**
 * Why session control cannot be used from this page (AC-165.55), or null when it can: a missing
 * cookie (401), the container (404 `agent-sessions-off`), no driver (503 with its cause), or
 * capabilities that say `available: false`.
 */
export function sessionControlUnavailable(
  problem: ApiProblem | null | undefined,
  capabilities: DriverCapabilities | null | undefined,
): Unavailable | null {
  if (problem?.status === 401)
    return {
      title: "Session control is locked in this browser",
      detail:
        "Open the link hub web printed when it started (it ends with ?token=…) once in this browser.",
    };
  if (problem?.status === 404 && problem.type === SESSIONS_OFF_TYPE)
    return {
      title: "Session control is off in the container",
      detail: "The Docker image ships no claude. Run hub web on your machine to drive sessions.",
    };
  if (problem?.status === 503)
    return {
      title: "Sessions cannot start here",
      detail: problem.detail ?? "The session driver is unavailable.",
    };
  if (capabilities && !capabilities.available)
    return {
      title: "Sessions cannot start here",
      detail: capabilities.reason ?? "claude is not available on this machine.",
    };
  return null;
}

export interface AgentSessionListProps {
  sessions: readonly AgentSession[];
  /** What the list or capabilities request answered with, when it failed. */
  problem?: ApiProblem | null | undefined;
  capabilities?: DriverCapabilities | null | undefined;
  /** Opens "New session"; the button shows only when sessions can start. */
  onNewSession?: (() => void) | undefined;
  onRetry?: (() => void) | undefined;
}

/**
 * The sessions `hub web` drives (D10): status badges with text, sessions waiting for a permission
 * highlighted with what they wait on, and the reason instead of "New session" when control is
 * unavailable.
 */
export function AgentSessionList({
  sessions,
  problem,
  capabilities,
  onNewSession,
  onRetry,
}: AgentSessionListProps) {
  const titleId = useId();
  const unavailable = sessionControlUnavailable(problem, capabilities);
  const waiting = sessions.filter((s) => s.status === "waiting_permission").length;
  return (
    <section className="ah-stack" style={{ gap: 8 }} aria-labelledby={titleId}>
      <div className="ah-row" style={{ gap: 8 }}>
        <h2 id={titleId} className="ah-h3">
          Driven from hub web
        </h2>
        {waiting > 0 && (
          <span className="ah-small ah-badge ah-badge-waiting">{waiting} waiting for you</span>
        )}
        <span className="ah-grow" />
        {!unavailable && onNewSession && (
          <Button variant="primary" icon="plus" onClick={onNewSession}>
            New session
          </Button>
        )}
      </div>
      {unavailable ? (
        <Banner tone="warning" boxed>
          <b>{unavailable.title}.</b> {unavailable.detail}
        </Banner>
      ) : (
        problem && (
          <ProblemError
            title="Could not load the agent sessions"
            detail={problem.detail}
            status={problem.status}
            type={problem.type}
            onRetry={onRetry}
            compact
          />
        )
      )}
      {sessions.length === 0 && !problem && (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          No session started from hub web yet.
        </p>
      )}
      {sessions.length > 0 && (
        <ul className="as-list" aria-label="Agent sessions">
          {sessions.map((session) => {
            const open = session.open_permission;
            const isWaiting = session.status === "waiting_permission";
            return (
              <li key={session.id} className={cx("as-list-item", isWaiting && "as-list-waiting")}>
                <AppLink href={agentSessionHref(session.id)} className="as-list-title">
                  {session.title ?? "Untitled session"}
                </AppLink>
                <AgentStatusBadge status={session.status} endReason={session.end_reason} />
                {isWaiting && open && (
                  <span className="ah-small">
                    Waiting for you: {open.tool}
                    {open.summary ? ` · ${open.summary.slice(0, 80)}` : ""}
                  </span>
                )}
                <span className="ah-grow" />
                <span className="ah-small ah-muted">{session.workdir_label}</span>
                <span className="ah-small ah-muted">
                  {modeLabel(session.mode)}
                  {session.model ? ` · ${session.model}` : ""}
                </span>
                {session.cost_usd && (
                  <span className="ah-small ah-muted" title="Estimate">
                    <Money value={session.cost_usd} precise />
                  </span>
                )}
                <span className="ah-small ah-subtle">
                  <Time iso={session.updated_at} />
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
