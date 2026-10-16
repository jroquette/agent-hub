/* Triage with Claude: one session in the project's hub reviews a batch of proposed learnings, each
 * into its own draft folder, so every learning's review reads exactly like a single review's. */
import { useEffect, useState } from "react";

import type { components } from "../../api/schema";
import { useAgentTranscript } from "../agent-session/queries";
import { sessionControlUnavailable } from "../sessions-list/control";
import { useAgentCapabilities, useCreateAgentSession, useWorkdirs } from "../sessions-list/queries";
import { blockedReason, type ClaudeVerdict } from "./filters";
import {
  MAX_TRIAGE_BATCH,
  newTriageBatchId,
  readReviewLink,
  reviewWrites,
  saveReviewLink,
  triageDraftId,
  triagePrompt,
  type ReviewLink,
} from "./review";

type Learning = components["schemas"]["Learning"];

const hubNotePath = (path: string) => (path.startsWith("brain/") ? path : `brain/${path}`);

/** The proposals a triage run would review: decidable, with a note, and not reviewed yet. */
export function triageCandidates(rows: readonly Learning[]): Learning[] {
  return rows.filter(
    (l) =>
      l.status === "proposed" &&
      blockedReason(l) === null &&
      l.note_path &&
      readReviewLink(l.id) === null,
  );
}

/** Starts a triage session for `project` over `candidates` (the first MAX_TRIAGE_BATCH). */
export function useTriage(project: string | null, candidates: readonly Learning[]) {
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const canDrive = capabilities.data !== undefined && unavailable === null;
  const workdirs = useWorkdirs(project ?? "", canDrive && project !== null);
  const hub = workdirs.data?.items.find((w) => w.kind === "hub") ?? null;
  const create = useCreateAgentSession();
  const reason =
    project === null
      ? "Pick one project to triage its learnings."
      : unavailable
        ? `${unavailable.title}.`
        : !canDrive
          ? "Checking whether this machine can drive Claude…"
          : workdirs.isPending
            ? "Looking for the hub folder…"
            : hub === null
              ? `Project ${project} has no hub folder to work in.`
              : candidates.length === 0
                ? "Every learning here already has a review."
                : null;

  const start = async (): Promise<number> => {
    if (!hub || project === null) return 0;
    const batch = candidates.slice(0, MAX_TRIAGE_BATCH);
    const batchId = newTriageBatchId();
    const items = batch.map((l) => ({
      learningId: l.id,
      notePath: hubNotePath(l.note_path ?? ""),
    }));
    const session = await create.mutateAsync({
      project,
      workdir_id: hub.workdir_id,
      mode: "acceptEdits",
      fork: false,
      prompt: triagePrompt({ project, batchId, items }),
    });
    for (const l of batch) {
      saveReviewLink(l.id, { sessionId: session.id, draftId: triageDraftId(batchId, l.id) });
    }
    return batch.length;
  };

  return { start, reason, pending: create.isPending, error: create.error };
}

function SessionVerdicts({
  sessionId,
  links,
  onVerdicts,
}: {
  sessionId: string;
  links: readonly [string, ReviewLink][];
  onVerdicts: (verdicts: Record<string, ClaudeVerdict>) => void;
}) {
  const { state, error } = useAgentTranscript(sessionId);
  const ended = error !== null || state.status === "ended" || state.status === "failed";
  const verdicts: Record<string, ClaudeVerdict> = {};
  for (const [learningId, link] of links) {
    const review = reviewWrites(state, link.draftId).review;
    verdicts[learningId] = review ? review.verdict : ended ? "unreviewed" : "reviewing";
  }
  const key = JSON.stringify(verdicts);
  useEffect(() => {
    onVerdicts(JSON.parse(key) as Record<string, ClaudeVerdict>);
  }, [key, onVerdicts]);
  return null;
}

/** Claude's verdict per learning, read from the review sessions linked to `rows`. Renders nothing
 * itself: mount `sources` once, read `verdictOf`. `refresh` re-reads the links after a new run. */
export function useClaudeVerdicts(rows: readonly Learning[]) {
  const [verdicts, setVerdicts] = useState<Record<string, ClaudeVerdict>>({});
  const [, setGeneration] = useState(0);
  const bySession = new Map<string, [string, ReviewLink][]>();
  for (const l of rows) {
    const link = readReviewLink(l.id);
    if (!link) continue;
    bySession.set(link.sessionId, [...(bySession.get(link.sessionId) ?? []), [l.id, link]]);
  }
  const [onVerdicts] = useState(() => (next: Record<string, ClaudeVerdict>) => {
    setVerdicts((current) => ({ ...current, ...next }));
  });
  const sources = [...bySession.entries()].map(([sessionId, links]) => (
    <SessionVerdicts key={sessionId} sessionId={sessionId} links={links} onVerdicts={onVerdicts} />
  ));
  const verdictOf = (l: Pick<Learning, "id">): ClaudeVerdict =>
    readReviewLink(l.id) === null ? "unreviewed" : (verdicts[l.id] ?? "reviewing");
  return {
    sources,
    verdictOf,
    refresh: () => {
      setGeneration((g) => g + 1);
    },
  };
}
