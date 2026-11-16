import type { components } from "../api/schema";

type Workdir = components["schemas"]["Workdir"];

/**
 * The real path of the checkout `make dev` serves, set by Vite's `define` under `vite serve` and null
 * in a build (`vite.config.ts`), so `web_dist` holds no absolute path (O8, AC-260.18).
 */
declare const __AH_DEV_CHECKOUT__: string | null;

/** The checkout the dev server serves, or null outside `make dev`. */
export function servedCheckout(): string | null {
  return import.meta.env.DEV ? __AH_DEV_CHECKOUT__ : null;
}

/** The first 16 hex digits of sha256("<kind>\0<root>"), as core's `workdir_id` (E6). */
export async function derivedWorkdirId(kind: "repo" | "worktree", root: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`${kind}\0${root}`),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 16);
}

/**
 * The listed workdir that is the served checkout, as a repo or a worktree, so a session started from
 * the dev app edits the files Vite hot-reloads; null when there is no root or no match.
 */
export async function matchingWorkdir(
  root: string | null,
  workdirs: readonly Workdir[],
): Promise<string | null> {
  if (root === null || workdirs.length === 0) return null;
  const ids = new Set([
    await derivedWorkdirId("repo", root),
    await derivedWorkdirId("worktree", root),
  ]);
  return workdirs.find((w) => ids.has(w.workdir_id))?.workdir_id ?? null;
}
