/* The retired Live sessions screen's bookmarks (ADR 0033 D8, AC-234.2). */
import { WITHINS } from "./filters";

/**
 * Where a `/live` URL lands: the Sessions grid, Live's `group` as `within` (`flat` is none), the
 * project `scope` kept, any other parameter dropped.
 */
export function liveRedirectTarget(search: string): string {
  const live = new URLSearchParams(search);
  const target = new URLSearchParams({ view: "grid" });
  const group = live.get("group");
  if (group && group !== "flat" && WITHINS.some(({ id }) => id === group)) {
    target.set("within", group);
  }
  const scope = live.get("scope");
  if (scope) target.set("scope", scope);
  return `/sessions?${target.toString()}`;
}
