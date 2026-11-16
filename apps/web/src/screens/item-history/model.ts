import type { IconName } from "../../components";
import type { ApiProblem } from "../../lib/api";
import { unifiedDiff } from "../agent-session/model";
import type { ItemVersion, ItemVersionPage, VersionFile } from "./queries";

/* The History panel's words (AGH-295): origin, author, state and refusals in plain language,
 * and a folder version's file-by-file changes (S6). */

/** A content hash as the panel shows it: eight hex characters, without the `sha256:` prefix. */
export function shortHash(hash: string): string {
  return hash.replace(/^sha256:/, "").slice(0, 8);
}

/** Where a version came from, in words (AC-295.29); `byId` finds a restore's source. */
export function originWords(version: ItemVersion, byId: ReadonlyMap<string, ItemVersion>): string {
  if (version.origin === "publish") return "Published";
  if (version.origin === "restore") {
    const source = version.restored_from === null ? undefined : byId.get(version.restored_from);
    return source
      ? `Restored from ${shortHash(source.content_hash)}`
      : "Restored from an older version";
  }
  return version.first ? "First seen" : "Changed outside the app";
}

/** The icon beside the origin words (never the only signal). */
export function originIcon(version: ItemVersion): IconName {
  if (version.origin === "publish") return "file-pen";
  if (version.origin === "restore") return "rotate-ccw";
  return version.first ? "flag" : "pencil";
}

/** Who wrote a version: the author's name, or "Outside the app" for an external one (D11). */
export function authorWords(version: ItemVersion): string {
  return version.author?.name ?? "Outside the app";
}

/** What the disk holds now when it could not be stored (S8, S10, A1), or null when it is. */
export function stateNotice(
  state: ItemVersionPage["state"],
): { title: string; detail: string; icon: IconName } | null {
  switch (state) {
    case "secret":
      return {
        title: "Not versioned: secret",
        detail:
          "The item on disk holds a secret match, so agent-hub does not store it. Earlier versions stay listed and comparable; Restore is off until the secret is removed.",
        icon: "shield-alert",
      };
    case "too_large":
      return {
        title: "Not versioned: too large",
        detail:
          "The item on disk is past the bounds (256 KiB a file, 200 files a skill), so agent-hub does not store it. Earlier versions stay listed and restorable.",
        icon: "triangle-alert",
      };
    case "unreadable":
      return {
        title: "Not versioned: cannot read it",
        detail:
          "The item on disk holds a link or a file that cannot be read, so it cannot be recorded first. Restore is off until it can be read.",
        icon: "circle-alert",
      };
    default:
      return null;
  }
}

/** Whether Restore may run: the disk's content must be recordable first (S10, A1). */
export function canRestore(state: ItemVersionPage["state"]): boolean {
  return state !== "secret" && state !== "unreadable";
}

export interface FileChange {
  path: string;
  status: "added" | "removed" | "changed";
  older: VersionFile | null;
  newer: VersionFile | null;
  /** The text (or the bytes, for a binary file) differs. */
  textChanged: boolean;
  /** The executable bit changed. */
  bitsChanged: boolean;
}

/** The files that differ between two versions, by path: added, removed, changed or bit changed. */
export function folderDiff(
  older: readonly VersionFile[],
  newer: readonly VersionFile[],
): FileChange[] {
  const before = new Map(older.map((file) => [file.path, file]));
  const after = new Map(newer.map((file) => [file.path, file]));
  const paths = [...new Set([...before.keys(), ...after.keys()])].sort();
  return paths.flatMap((path): FileChange[] => {
    const a = before.get(path) ?? null;
    const b = after.get(path) ?? null;
    if (a === null && b !== null)
      return [
        { path, status: "added", older: null, newer: b, textChanged: true, bitsChanged: false },
      ];
    if (b === null && a !== null)
      return [
        { path, status: "removed", older: a, newer: null, textChanged: true, bitsChanged: false },
      ];
    if (a === null || b === null) return [];
    // A binary file has no text: its size stands for its bytes, as far as the web can tell.
    const textChanged = a.text !== b.text || (a.text === null && a.size !== b.size);
    const bitsChanged = a.executable !== b.executable;
    return textChanged || bitsChanged
      ? [{ path, status: "changed", older: a, newer: b, textChanged, bitsChanged }]
      : [];
  });
}

/**
 * The most diff lines Compare renders for one pair of versions, headers included, across every
 * file of a folder: a 200-file folder of 256 KiB files must not render millions of lines.
 */
export const COMPARE_MAX_LINES = 2000;

export interface ShownChange extends FileChange {
  /** The unified diff to render, cut to the budget; null for a binary file or one not shown. */
  diff: string | null;
  /** Lines of this file's diff past the budget. */
  hiddenLines: number;
  /** The budget ran out before this file: its diff was not computed. */
  skipped: boolean;
}

const isBinary = (change: FileChange) =>
  (change.older !== null && change.older.text === null) ||
  (change.newer !== null && change.newer.text === null);

/**
 * Each changed file of two versions with its diff, within one budget of `maxLines` rendered
 * lines: the file that crosses it is cut and the files after it are not diffed at all.
 */
export function compareChanges(
  older: readonly VersionFile[],
  newer: readonly VersionFile[],
  maxLines: number = COMPARE_MAX_LINES,
): ShownChange[] {
  let left = maxLines;
  return folderDiff(older, newer).map((change): ShownChange => {
    if (!change.textChanged || isBinary(change))
      return { ...change, diff: null, hiddenLines: 0, skipped: false };
    if (left <= 0) return { ...change, diff: null, hiddenLines: 0, skipped: true };
    const lines = unifiedDiff(
      change.path,
      change.older?.text ?? "",
      change.newer?.text ?? "",
    ).split("\n");
    const shown = lines.slice(0, left);
    left -= shown.length;
    return {
      ...change,
      diff: shown.join("\n"),
      hiddenLines: lines.length - shown.length,
      skipped: false,
    };
  });
}

/** Binary files both versions hold with the same size and bit, so not listed as changed: their
 * bytes may still differ. */
export function unshownBinaries(older: readonly VersionFile[], newer: readonly VersionFile[]) {
  const after = new Map(newer.map((file) => [file.path, file]));
  return older
    .filter((a) => {
      const b = after.get(a.path);
      // A size or bit change already lists the file as changed.
      return (
        b !== undefined &&
        a.text === null &&
        b.text === null &&
        a.size === b.size &&
        a.executable === b.executable
      );
    })
    .map((file) => file.path);
}

/** Why a restore did not go through, in words (`code` and `reason` of the problem, API.md Errors). */
export function writeProblemWords(problem: ApiProblem): string {
  if (problem.status === 401)
    return "Restore is locked in this browser. Open the link hub web printed when it started (it ends with ?token=…) once in this browser.";
  switch (problem.code) {
    case "hub_read_only":
      return "The hub folder is read-only here (always in the container), so nothing was restored.";
    case "no_author":
      return `No author identity is set for this hub, so nothing was restored: ${problem.reason ?? "set git user.name and user.email"}.`;
    case "link_in_path":
      return "A folder or file on the item's path is a link, and agent-hub never writes through one. Nothing was restored.";
    case "unit_unreadable":
      return "The item on disk cannot be read whole, so it could not be recorded first. Nothing was restored.";
    case "secret_unversioned":
      return "The item on disk holds a secret match and has no version, so restoring would lose it. Nothing was restored.";
    case "managed_confirmation_required":
      return "hub.lock manages this file: confirm that the next hub sync rewrites it.";
    case "write_failed":
      return problem.detail ?? "The write failed; the item is as it was.";
    case "version_race":
      return "Another write took this item's next version first. Nothing was written; try again.";
    case "written_not_recorded":
      return "The version was written but not recorded; the next read records it as changed outside the app.";
    default:
      return problem.detail ?? problem.title;
  }
}
