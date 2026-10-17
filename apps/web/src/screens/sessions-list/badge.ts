import type { Status } from "../../components";
import type { Session } from "./queries";

const OUTCOME_BADGE: Record<NonNullable<Session["outcome"]>, [Status, string]> = {
  done: ["done", "Done"],
  stopped: ["stopped", "Stopped"],
  blocked: ["blocked", "Blocked"],
  error: ["error", "Error"],
};

/** A session's status badge: live, waiting or idle while open, else how it ended. */
export function badgeOf(session: Session): [Status, string] {
  if (session.status === "live") return ["live", "Live"];
  if (session.status === "waiting") return ["waiting", "Waiting"];
  if (session.status === "idle") return ["idle", "Idle"];
  if (session.outcome) return OUTCOME_BADGE[session.outcome];
  return ["ended", session.end_inferred ? "Ended · no end event" : "Ended"];
}
