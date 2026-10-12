import { useCallback } from "react";
import { useSearchParams } from "react-router";

import { readStored, writeStored } from "./storage";

const KEY = "ah.scope";

/**
 * The project scope (spec 01): `?scope=` on the URL wins, else the last choice in this browser;
 * null is "All projects". Screens pass it to the API as `project`.
 */
export function useScope(): [string | null, (project: string | null) => void] {
  const [params, setParams] = useSearchParams();
  const stored = readStored(KEY);
  const scope = params.get("scope") ?? (stored === null || stored === "" ? null : stored);
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
