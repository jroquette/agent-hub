/* Live sessions: tile order and grouping (spec 11), pure so the screen only renders. */
import type { LiveTile } from "./queries";

export type Grouping = "repo" | "run" | "workflow" | "flat";
export const GROUPINGS: { id: Grouping; label: string }[] = [
  { id: "repo", label: "Project › repo" },
  { id: "run", label: "Run" },
  { id: "workflow", label: "Workflow" },
  { id: "flat", label: "Flat" },
];
/** Above this many tiles, each group shows its first GROUP_CAP and a "Show N more" button. */
export const MANY_TILES = 24;
export const GROUP_CAP = 6;

export function isGrouping(value: string | null): value is Grouping {
  return GROUPINGS.some((grouping) => grouping.id === value);
}

/** A red edge only when a problem needs the owner (E11); a failing notice alone stays text. */
export function troubled(tile: LiveTile): boolean {
  return tile.problems.needs_you > 0;
}

const count = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`;

/**
 * The tile's problems line (AC-201.14): the first problem that needs the owner, else what the agent
 * handled, is still on, or the owner interrupted; null without problems.
 */
export function problemsLine(tile: LiveTile): string | null {
  const { needs_you, handled, open, by_you } = tile.problems;
  if (needs_you > 0) {
    return tile.needs_you_problem ?? `Needs you: ${count(needs_you, "problem", "problems")}`;
  }
  const parts = [
    handled > 0 ? `${count(handled, "problem", "problems")}, handled by the agent` : "",
    open > 0 ? `${count(open, "problem", "problems")}, agent is on it` : "",
    by_you > 0 ? `${String(by_you)} handled by you` : "",
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** Inside a group: idle last, troubled first, then the oldest start first. */
export function sortTiles(tiles: LiveTile[]): LiveTile[] {
  return [...tiles].sort(
    (a, b) =>
      Number(a.status === "idle") - Number(b.status === "idle") ||
      Number(troubled(b)) - Number(troubled(a)) ||
      Date.parse(a.started_at) - Date.parse(b.started_at) ||
      a.id.localeCompare(b.id),
  );
}

export interface TileGroup {
  key: string;
  label: string;
  tiles: LiveTile[];
}

function keyOf(tile: LiveTile, grouping: Grouping): [string, string] {
  switch (grouping) {
    case "repo":
      return [`${tile.project}/${tile.repo ?? ""}`, `${tile.project} › ${tile.repo ?? "no repo"}`];
    case "run":
      return tile.run_id
        ? [tile.run_id, `Run ${tile.issue ?? tile.run_id}${tile.step ? ` · ${tile.step}` : ""}`]
        : ["", "Not in a run"];
    case "workflow":
      return tile.label?.workflow
        ? [tile.label.workflow, tile.label.workflow]
        : ["", "No workflow"];
    case "flat":
      return ["flat", "All sessions"];
  }
}

/** Running tiles (live and idle) by `grouping`; "Not in a run" and "No workflow" go last. */
export function groupTiles(tiles: LiveTile[], grouping: Grouping): TileGroup[] {
  const groups = new Map<string, TileGroup>();
  for (const tile of sortTiles(tiles)) {
    const [key, label] = keyOf(tile, grouping);
    const group = groups.get(key);
    if (group) group.tiles.push(tile);
    else groups.set(key, { key, label, tiles: [tile] });
  }
  return [...groups.values()].sort((a, b) => Number(a.key === "") - Number(b.key === ""));
}

/** "2 live · 1 idle". */
export function groupCounts(tiles: LiveTile[]): string {
  const live = tiles.filter((tile) => tile.status === "live").length;
  const idle = tiles.filter((tile) => tile.status === "idle").length;
  return [live ? `${String(live)} live` : "", idle ? `${String(idle)} idle` : ""]
    .filter(Boolean)
    .join(" · ");
}

export interface Split {
  waiting: LiveTile[];
  running: LiveTile[];
  ended: LiveTile[];
}

/** Waiting first (oldest wait first, as the API sends them), running, ended in the last 2 min. */
export function splitTiles(tiles: LiveTile[]): Split {
  return {
    waiting: tiles.filter((tile) => tile.group === "waiting"),
    running: tiles.filter((tile) => tile.group === "live" || tile.group === "idle"),
    ended: tiles.filter((tile) => tile.group === "ended_recently"),
  };
}

/** The wait a permission prompt shows (an agent session hub web drives, or a hook-observed one). */
export const PERMISSION_WAIT = "Permission prompt";

/**
 * Where a waiting tile sends the owner: a permission prompt to its session (whose header opens
 * the chat when hub web drives it, AC-165.25), any other wait to the approvals.
 */
export function waitingLink(tile: LiveTile): { href: string; label: string } {
  if (tile.waiting_reason === PERMISSION_WAIT)
    return { href: `/sessions/${encodeURIComponent(tile.id)}`, label: "Open session" };
  return { href: "/approvals", label: "Open approval" };
}
