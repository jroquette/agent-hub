import { Banner, StatusBadge, type Status } from "../../components";
import type { AgentSessionStatus, EndReason } from "./transcript";

/** How each agent-session status reads: icon and text, never colour alone. */
export const AGENT_STATUS: Record<AgentSessionStatus, { status: Status; label: string }> = {
  running: { status: "running", label: "Running" },
  idle: { status: "idle", label: "Idle" },
  waiting_permission: { status: "waiting", label: "Waiting for you" },
  ended: { status: "ended", label: "Ended" },
  failed: { status: "failed", label: "Failed" },
};

const END_REASON: Record<EndReason, string> = {
  closed: "closed",
  idle_timeout: "idle timeout",
  server_stopped: "hub web stopped",
  failed: "failed",
  log_full: "log full",
};

export interface AgentStatusBadgeProps {
  status: AgentSessionStatus;
  endReason?: EndReason | null | undefined;
}

/** The status indicator of an agent session (D10), with why it ended when it did. */
export function AgentStatusBadge({ status, endReason }: AgentStatusBadgeProps) {
  const look = AGENT_STATUS[status];
  const reason = status === "ended" && endReason ? ` · ${END_REASON[endReason]}` : "";
  return <StatusBadge status={look.status} label={`${look.label}${reason}`} />;
}

/** Marks text replayed from the store, where secrets read `[redacted: <kind>]` (E9, plan Q3). */
export function StoredCopyLabel() {
  return (
    <span
      className="as-stored"
      title="Replayed from the hub web database, where secrets are redacted. The live view showed the original."
    >
      stored copy, redacted
    </span>
  );
}

export interface ReconnectBannerProps {
  /** Whether the session stream is open. */
  connected: boolean;
}

/** Shown while the session stream is lost; the browser reconnects and the log resumes (AC-165.45). */
export function ReconnectBanner({ connected }: ReconnectBannerProps) {
  if (connected) return null;
  return (
    <Banner tone="offline">
      Connection to this session lost. Reconnecting… The conversation resumes where it stopped.
    </Banner>
  );
}
