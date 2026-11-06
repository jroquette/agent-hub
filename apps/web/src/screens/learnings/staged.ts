/* Triage marks: the accepts and rejects the owner picked on the Learnings screen and has not sent
 * yet. They live in this browser until "Open pull request" sends them all as one hub PR per
 * project, so marking many learnings costs one PR, not one each. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

import type { components } from "../../api/schema";
import { apiKey, apiPost, type ApiProblem } from "../../lib/api";
import { readStored, removeStored, writeStored } from "../../lib/storage";
import { readNoteDraft } from "./noteDraft";

export type LearningBatchResult = components["schemas"]["LearningBatchResult"];

/** One learning marked for the triage pull request. */
export interface StagedDecision {
  action: "accept" | "reject";
  /** The learning's project: one pull request per project's hub. */
  project: string;
  /** The learning's title, to list it without refetching. */
  title: string;
  /** An accept's destination under `brain/`. */
  target?: string;
  /** A reject's reason. */
  reason?: string;
}

/** The most decisions one pull request carries (the API's limit). */
export const MAX_BATCH = 50;

const KEY = "ah.learning.staged";
const DRAFT_PREFIX = "ah.learning.draft.";
type Staged = Readonly<Record<string, StagedDecision>>;

function parse(raw: string | null): Staged {
  if (raw === null) return {};
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
    const kept: Record<string, StagedDecision> = {};
    for (const [id, item] of Object.entries(value as Record<string, unknown>)) {
      if (typeof item !== "object" || item === null) continue;
      const d = item as Partial<StagedDecision>;
      if (
        (d.action === "accept" || d.action === "reject") &&
        typeof d.project === "string" &&
        typeof d.title === "string"
      ) {
        kept[id] = {
          action: d.action,
          project: d.project,
          title: d.title,
          ...(typeof d.target === "string" ? { target: d.target } : {}),
          ...(typeof d.reason === "string" ? { reason: d.reason } : {}),
        };
      }
    }
    return kept;
  } catch {
    return {};
  }
}

const listeners = new Set<() => void>();
// The marks as last parsed, kept while the stored text is the same (a stable snapshot).
let cache: { raw: string | null; staged: Staged } = { raw: null, staged: {} };

function current(): Staged {
  const raw = readStored(KEY);
  if (raw !== cache.raw) cache = { raw, staged: parse(raw) };
  return cache.staged;
}

function publish(next: Staged): void {
  if (Object.keys(next).length === 0) removeStored(KEY);
  else writeStored(KEY, JSON.stringify(next));
  listeners.forEach((listener) => {
    listener();
  });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // Another tab marking learnings shows here too.
  const onStorage = (event: StorageEvent) => {
    if (event.key === KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function stageDecision(id: string, decision: StagedDecision): void {
  publish({ ...current(), [id]: decision });
}

export function unstageDecisions(ids: readonly string[]): void {
  const dropped = new Set(ids);
  publish(Object.fromEntries(Object.entries(current()).filter(([id]) => !dropped.has(id))));
}

/** Every marked learning, by id; re-renders when a mark changes, here or in another tab. */
export function useStagedDecisions(): Staged {
  return useSyncExternalStore(subscribe, current);
}

/** The edited body an accept sends: the note's draft when it differs from where it started. */
function editedBody(id: string): string | undefined {
  const draft = readNoteDraft(id);
  return draft !== null && draft.body !== draft.base ? draft.body : undefined;
}

/** Sends one project's marks as one hub pull request; on success they are unmarked and their
 * note drafts dropped. */
export function useSendStaged() {
  const client = useQueryClient();
  return useMutation<LearningBatchResult, ApiProblem, readonly string[]>({
    mutationFn: (ids) =>
      apiPost("/api/v1/learnings/decisions", {
        decisions: ids.map((id) => {
          const d = current()[id];
          if (d === undefined) throw new Error(`Learning ${id} is not marked`);
          const body = d.action === "accept" ? editedBody(id) : undefined;
          return {
            learning_id: id,
            action: d.action,
            target: d.action === "accept" ? (d.target ?? "") : "",
            reason: d.action === "reject" ? (d.reason ?? "") : "",
            ...(body === undefined ? {} : { note_body: body }),
          };
        }),
      }),
    onSuccess: (_answer, ids) => {
      ids.forEach((id) => {
        removeStored(DRAFT_PREFIX + id);
      });
      unstageDecisions(ids);
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/learnings") });
      // Every learning's detail: the sent ones now say "PR open".
      void client.invalidateQueries({ queryKey: ["api", "/api/v1/learnings/{learning_id}"] });
    },
  });
}

/** The mark of learning `id`, or null when it is not marked. */
export function stagedOrNone(
  staged: Readonly<Record<string, StagedDecision>>,
  id: string,
): StagedDecision | null {
  return staged[id] ?? null;
}
