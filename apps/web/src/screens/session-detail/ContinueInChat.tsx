import { useState } from "react";
import { useNavigate } from "react-router";

import { Button, Icon } from "../../components";
import { ApiProblem, apiGet, apiPost } from "../../lib/api";
import { agentSessionHref } from "../sessions-list/control";
import { useAgentCapabilities } from "../sessions-list/queries";
import type { Session } from "./queries";

type Workdir = Awaited<ReturnType<typeof listWorkdirs>>["items"][number];

function listWorkdirs(project: string) {
  return apiGet("/api/v1/agent-sessions/workdirs", { query: { project } });
}

/** The folders to look in, the session's own repo first (its checkout, then its worktrees). */
export function candidates(workdirs: readonly Workdir[], repo: string | null): Workdir[] {
  const rank = (w: Workdir) => (repo && w.repo === repo ? (w.kind === "repo" ? 0 : 1) : 2);
  return [...workdirs].sort((a, b) => rank(a) - rank(b));
}

/** The workdir whose past Claude sessions hold `sessionId`, or null. */
async function findWorkdir(session: Session): Promise<Workdir | null> {
  const { items } = await listWorkdirs(session.project);
  const repo = session.label?.repo ?? session.repo;
  for (const workdir of candidates(items, repo)) {
    const past = await apiGet("/api/v1/agent-sessions/resumable", {
      query: { project: session.project, workdir_id: workdir.workdir_id },
    });
    if (past.items.some((item) => item.session_id === session.id)) return workdir;
  }
  return null;
}

function problemText(error: unknown): string {
  if (error instanceof ApiProblem)
    return error.detail ? `${error.title}: ${error.detail}` : error.title;
  return "Could not continue this session here. Try again.";
}

/**
 * "Continue in chat" for a session run in a terminal: once it has ended there, hub web resumes the
 * same Claude conversation (same id) in its folder and opens its chat. While it is still open in the
 * terminal, a second process would write to the same conversation, so the button waits.
 */
export function ContinueInChat({ session }: { session: Session }) {
  const navigate = useNavigate();
  const capabilities = useAgentCapabilities();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (capabilities.data?.available !== true) return null;

  if (session.status !== "ended") {
    return (
      <span
        className="ah-row ah-small ah-subtle"
        style={{ gap: 4 }}
        title="Exit it in the terminal (/exit) to continue this conversation in the chat."
      >
        <Icon name="message-square" size="sm" />
        Running in a terminal
      </span>
    );
  }

  const go = () => {
    setBusy(true);
    setError(null);
    void (async () => {
      try {
        const workdir = await findWorkdir(session);
        if (!workdir) {
          setError("Claude has no resumable copy of this session in a registered folder.");
          return;
        }
        const created = await apiPost("/api/v1/agent-sessions", {
          project: session.project,
          workdir_id: workdir.workdir_id,
          resume_session_id: session.id,
          // The chat's header changes the mode afterwards; the default asks before edits.
          mode: "default",
          fork: false,
        });
        await navigate(agentSessionHref(created.id));
      } catch (cause) {
        setError(problemText(cause));
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <span className="ah-row ah-small" style={{ gap: 8 }}>
      {error && (
        <span role="alert" className="ah-small" style={{ color: "var(--failed)" }}>
          {error}
        </span>
      )}
      <Button size="sm" icon="message-square" disabled={busy} onClick={go}>
        {busy ? "Opening chat…" : "Continue in chat"}
      </Button>
    </span>
  );
}
