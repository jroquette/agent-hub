import { keepPreviousData } from "@tanstack/react-query";

import { apiQuery, useApi } from "../lib/api";

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
  return useApi(SHELL, shellParams(scope), {
    refetchInterval: SHELL_REFRESH_MS,
    placeholderData: keepPreviousData,
  });
}
