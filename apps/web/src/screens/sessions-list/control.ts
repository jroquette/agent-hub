/* Driving sessions from hub web (AGH-165): the chat link and why control is unavailable. */
import type { components } from "../../api/schema";
import type { ApiProblem } from "../../lib/api";

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
