/*
 * The launch cookie (ADR 0031): hub web prints its address with a token once, and the browser that
 * opens it gets the cookie the owner's changes, runs and sessions need. A page opened without it
 * reads everything but cannot make them. This module is the one place the app knows that:
 *
 * - which operations need the cookie: `LAUNCH_COOKIE_ROUTES`, generated from the API's OpenAPI
 *   document, where the server marks them with the same rule its access checks follow;
 * - whether this page holds it: the shell read's `launch_cookie`, and any real refusal (a 401 from
 *   one of those operations), kept in a small store every control reads.
 */
import { LAUNCH_COOKIE_ROUTES } from "../api/launchCookie";
import type { components } from "../api/schema";

export type LaunchCookie = components["schemas"]["ShellView"]["launch_cookie"];

/** Why a control cannot be used: a short title and what to do. */
export interface LaunchCookieLock {
  title: string;
  detail: string;
}

/** The problem type of the server's own refusal without the cookie. */
export const LAUNCH_COOKIE_UNAUTHORIZED_TYPE = "urn:agent-hub:problem:agent-session-unauthorized";

/** Whether `method` on `path` (a route's template, `/api/v1/x/{id}`) needs the launch cookie. */
export function needsLaunchCookie(method: string, path: string): boolean {
  return LAUNCH_COOKIE_ROUTES.has(`${method.toUpperCase()} ${path}`);
}

/**
 * Why this page cannot make the operations that need the launch cookie, or null when it can or
 * while it is unknown: the cookie is missing, or the container turns them off.
 */
export function launchCookieLock(cookie: LaunchCookie | undefined): LaunchCookieLock | null {
  if (cookie === "missing")
    return {
      title: "Changes are locked in this browser",
      detail:
        "Open the link hub web printed when it started (it ends with ?token=…) once in this browser.",
    };
  if (cookie === "off")
    return {
      title: "Changes are off in the container",
      detail: "The agent-hub container mounts the hubs read-only. Run hub web on your machine.",
    };
  return null;
}

let current: LaunchCookie | undefined;
const listeners = new Set<() => void>();

/** What the app last learned about the cookie; undefined until the shell read answers. */
export function launchCookieState(): LaunchCookie | undefined {
  return current;
}

/** Record what the shell read, or a refusal, says about the cookie; listeners run on a change. */
export function noteLaunchCookie(next: LaunchCookie | undefined): void {
  if (next === current) return;
  current = next;
  for (const listener of listeners) listener();
}

/** Run `listener` on every change of the state (for `useSyncExternalStore`). */
export function subscribeLaunchCookie(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
