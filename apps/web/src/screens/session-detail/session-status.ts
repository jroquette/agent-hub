import type { components } from "../../api/schema";
import type { Status } from "../../components";
import { fmtInt, fmtTokens } from "../../lib/format";

type Session = components["schemas"]["Session"];

export interface StatusView {
  status: Status;
  label: string;
  inferred: boolean;
  title?: string | undefined;
}

const OUTCOME: Record<NonNullable<Session["outcome"]>, [Status, string]> = {
  done: ["done", "Done"],
  stopped: ["stopped", "Stopped"],
  blocked: ["blocked", "Blocked"],
  error: ["error", "Error"],
};

/** The header's status badge (spec 10, "Status badge copy"); `now` in ms. */
export function statusOf(session: Session, now: number): StatusView {
  const title = session.end_reason ? `end_reason: ${session.end_reason}` : undefined;
  switch (session.status) {
    case "live":
      return { status: "live", label: "Live", inferred: false };
    case "waiting":
      return { status: "waiting", label: "Waiting", inferred: false };
    case "idle": {
      const minutes = Math.max(
        1,
        Math.round((now - Date.parse(session.last_activity_at)) / 60_000),
      );
      return { status: "idle", label: `Idle · ${String(minutes)} min`, inferred: false };
    }
    case "ended": {
      if (session.outcome) {
        const [status, label] = OUTCOME[session.outcome];
        return { status, label, inferred: false, title };
      }
      if (session.end_inferred) {
        return { status: "ended", label: "Ended · no end event", inferred: false, title };
      }
      return { status: "ended", label: "Ended", inferred: false, title };
    }
  }
}

/** Seconds from start to end (or `now` while it runs). */
export function durationOf(session: Pick<Session, "started_at" | "ended_at">, now: number): number {
  const end = session.ended_at ? Date.parse(session.ended_at) : now;
  return Math.max(0, (end - Date.parse(session.started_at)) / 1000);
}

/** "412,330 in · 38,904 out · 2.22 M cache" and its exact tooltip. */
export function tokensText(tokens: Session["tokens"]): { text: string; title: string } {
  if (!tokens) return { text: "—", title: "No token usage in the transcript yet." };
  return {
    text: `${fmtInt(tokens.input)} in · ${fmtInt(tokens.output)} out · ${fmtTokens(tokens.cache_read + tokens.cache_write)} cache`,
    title: `Input ${fmtInt(tokens.input)} · output ${fmtInt(tokens.output)} · cache read ${fmtInt(tokens.cache_read)} · cache write ${fmtInt(tokens.cache_write)}`,
  };
}

/** True while the session can still change (live mode, spec 10). */
export function isOpen(session: Pick<Session, "status">): boolean {
  return session.status !== "ended";
}
