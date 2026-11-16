import { keepPreviousData } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";

import { apiQuery, useApi } from "../lib/api";
import {
  launchCookieLock,
  launchCookieState,
  noteLaunchCookie,
  subscribeLaunchCookie,
  type LaunchCookieLock,
} from "../lib/launchCookie";

/**
 * How often the shell rereads its facts: the live sessions behind the Features badge stay as fresh
 * as the live-session list. The server keeps the feature list behind the count 30 s.
 */
export const SHELL_REFRESH_MS = 5_000;

const SHELL = "/api/v1/screens/shell" as const;
const shellParams = (scope: string | null) => ({ query: { project: scope } });

/** The shell read as query options, under the key `useShellRead` reads: the app's early request. */
export function shellReadQuery(scope: string | null) {
  return apiQuery(SHELL, shellParams(scope));
}

/**
 * The shell's facts in one read (ADR 0056): how many hubs are registered (the first-run gate),
 * every project with its live sessions (the switcher), how many features of `scope` need you (the
 * Features badge) and whether any workflow run exists (the sidebar item). The shell, the gate and
 * the app's early request all pass `useScope()`'s project, so they share one request. A scope
 * change keeps the previous answer until the new one arrives: only the badge depends on the scope,
 * so it alone hides while the data is that placeholder.
 */
export function useShellRead(scope: string | null) {
  const read = useApi(SHELL, shellParams(scope), {
    refetchInterval: SHELL_REFRESH_MS,
    placeholderData: keepPreviousData,
  });
  // The launch cookie the server found on this read is what every control locks on.
  const cookie = read.data?.launch_cookie;
  useEffect(() => {
    if (cookie !== undefined) noteLaunchCookie(cookie);
  }, [cookie]);
  return read;
}

/**
 * Whether this page can make the operations that need the launch cookie (the owner's changes,
 * runs, sessions), and why not: `lock` is null while it can or while unknown, `locked` is true
 * only for a missing cookie (not the container). It reads what the shell's own read (`useShellRead`
 * in the app shell) and any refusal since taught the store, so it never sends a request itself. Every control of such an operation disables itself
 * with `lock.detail` as its reason.
 */
export function useLaunchCookie(): { lock: LaunchCookieLock | null; locked: boolean } {
  const cookie = useSyncExternalStore(subscribeLaunchCookie, launchCookieState);
  return { lock: launchCookieLock(cookie), locked: cookie === "missing" };
}
