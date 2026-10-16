/* Live sessions: tile grouping (spec 11), pure so the screen only renders; the tile order is Sessions' (T11 retires Live). */
import { sortTiles } from "../sessions-list/tiles";
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
