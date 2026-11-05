import { useCallback } from "react";
import { useSearchParams } from "react-router";

import { readStored, writeStored } from "./storage";

const KEY = "ah.scope";

/**
 * The project scope of a URL's query `params` (spec 01): `?scope=` wins, else the last choice in
 * this browser; null is "All projects". `useScope` reads it, and so does a request the app makes
 * before its router exists.
 */
export function scopeOf(params: URLSearchParams): string | null {
  const stored = readStored(KEY);
  return params.get("scope") ?? (stored === null || stored === "" ? null : stored);
}

/** The project scope of the current URL (`scopeOf`). Screens pass it to the API as `project`. */
export function useScope(): [string | null, (project: string | null) => void] {
  const [params, setParams] = useSearchParams();
  const scope = scopeOf(params);
  const setScope = useCallback(
    (project: string | null) => {
      writeStored(KEY, project ?? "");
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (project === null) next.delete("scope");
          else next.set("scope", project);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  return [scope, setScope];
}
