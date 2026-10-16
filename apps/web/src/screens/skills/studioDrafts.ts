/* The Studio's drafts in this browser: which session writes each draft, and the list the catalog
 * offers to continue. Only ids and labels are kept; the files live in the hub folder. */
import type { ItemKind } from "./filters";
import type { SkillRef } from "./queries";

export interface StoredDraft {
  draftId: string;
  project: string;
  kind: ItemKind;
  sessionId: string | null;
  /** The name read from the draft, once it has one. */
  name: string | null;
  updatedAt: string;
  published: boolean;
  /** The existing item the draft changes; absent for a new item. */
  target?: SkillRef | null;
}

const KEY = "ah.studio.drafts";
/** Older drafts drop off the list; their folders stay in the hub until discarded there. */
const MAX_DRAFTS = 20;

function readAll(): StoredDraft[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? (parsed as StoredDraft[]) : [];
  } catch {
    return [];
  }
}

function writeAll(drafts: readonly StoredDraft[]) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(drafts.slice(0, MAX_DRAFTS)));
  } catch {
    // Without storage a draft is only forgotten on reload.
  }
}

/** The drafts of `project` not yet published, most recent first. */
export function openDrafts(project: string): StoredDraft[] {
  return readAll().filter((d) => d.project === project && !d.published);
}

/** The open edit draft of `target` in `project`, so a second Edit reopens it. */
export function openEditDraft(project: string, target: SkillRef): StoredDraft | null {
  return (
    openDrafts(project).find(
      (d) =>
        d.target?.kind === target.kind &&
        d.target.source === target.source &&
        d.target.name === target.name,
    ) ?? null
  );
}

export function storedDraft(draftId: string): StoredDraft | null {
  return readAll().find((d) => d.draftId === draftId) ?? null;
}

/** Saves `patch` on the draft (created when new) and moves it to the top of the list. */
export function saveDraft(
  draftId: string,
  base: Pick<StoredDraft, "project" | "kind">,
  patch: Partial<Omit<StoredDraft, "draftId">>,
  now: Date = new Date(),
): StoredDraft {
  const all = readAll();
  const known = all.find((d) => d.draftId === draftId);
  const next: StoredDraft = {
    draftId,
    sessionId: null,
    name: null,
    published: false,
    ...base,
    ...known,
    ...patch,
    updatedAt: now.toISOString(),
  };
  writeAll([next, ...all.filter((d) => d.draftId !== draftId)]);
  return next;
}

export function forgetDraft(draftId: string) {
  writeAll(readAll().filter((d) => d.draftId !== draftId));
}
