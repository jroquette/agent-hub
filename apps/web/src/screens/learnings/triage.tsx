/* Triage with Claude: one session in the project's hub reviews a batch of proposed learnings, each
 * into its own draft folder, so every learning's review reads exactly like a single review's. */
import { useEffect, useState } from "react";

import type { components } from "../../api/schema";
import { readStored, writeStored } from "../../lib/storage";
import type { TranscriptState } from "../agent-session/model";
import { useAgentTranscript } from "../agent-session/queries";
import { sessionControlUnavailable } from "../sessions-list/control";
import { useAgentCapabilities, useCreateAgentSession, useWorkdirs } from "../sessions-list/queries";
import { blockedReason, type ClaudeVerdict } from "./filters";
import {
  MAX_TRIAGE_BATCH,
  newTriageBatchId,
  readReviewLink,
  reviewWrites,
  type ReviewVerdict,
  saveReviewLink,
  triageDraftId,
  triagePrompt,
  type ReviewLink,
} from "./review";

type Learning = components["schemas"]["Learning"];

const hubNotePath = (path: string) => (path.startsWith("brain/") ? path : `brain/${path}`);

/** The proposals a triage run would review: decidable, with a note, and with no review yet or
 * one that ended without a verdict. */
export function triageCandidates(
  rows: readonly Learning[],
  verdictOf: (l: Learning) => ClaudeVerdict,
): Learning[] {
  return rows.filter(
    (l) =>
      l.status === "proposed" &&
      blockedReason(l) === null &&
      l.note_path &&
      (verdictOf(l) === "unreviewed" || verdictOf(l) === "no_verdict"),
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
    batch.forEach((l, order) => {
      saveReviewLink(l.id, {
        sessionId: session.id,
        draftId: triageDraftId(batchId, l.id),
        order,
      });
    });
    return batch.length;
  };

  return { start, reason, pending: create.isPending, error: create.error };
}

/** Where Claude stands on one learning, as the queue and the detail show it. */
export interface ClaudeReview {
  verdict: ClaudeVerdict;
  /** The review session, when one was asked for. */
  sessionId: string | null;
  /** The verdict's two-sentence summary, once written. */
  summary: string | null;
  /** For a queued learning, how many Claude reviews before it (1 = right after the current). */
  position: number | null;
}

/** One review session over one or more learnings: how far it got. */
export interface TriageRun {
  sessionId: string;
  /** `waiting`: Claude stopped until you answer (a permission, a question) with reviews left. */
  status: "running" | "waiting" | "ended";
  total: number;
  reviewed: number;
  /** The learning Claude is on (the first in order without a verdict), while it runs. */
  currentId: string | null;
  verdicts: Record<ReviewVerdict, number>;
  /** Learnings the session ended without reviewing. */
  missing: number;
}

const NOT_REVIEWED: ClaudeReview = {
  verdict: "unreviewed",
  sessionId: null,
  summary: null,
  position: null,
};

/** Reads one session's transcript and works out each linked learning's place and verdict. */
export function runOf(
  sessionId: string,
  links: readonly [string, ReviewLink][],
  state: TranscriptState,
  failed: boolean,
): { run: TriageRun; reviews: Record<string, ClaudeReview> } {
  const ordered = [...links].sort(
    ([a, x], [b, y]) => (x.order ?? Infinity) - (y.order ?? Infinity) || a.localeCompare(b),
  );
  const written = new Map(ordered.map(([id, link]) => [id, reviewWrites(state, link.draftId)]));
  const left = ordered.filter(([id]) => !written.get(id)?.review);
  const ended =
    failed ||
    state.status === "ended" ||
    state.status === "failed" ||
    // An idle session with nothing left finished its turn: the triage is done.
    (state.status === "idle" && left.length === 0);
  const waiting = !ended && (state.status === "waiting_permission" || state.status === "idle");
  const verdicts: Record<ReviewVerdict, number> = { ready: 0, needs_changes: 0, not_for_brain: 0 };
  const reviews: Record<string, ClaudeReview> = {};
  for (const [id] of ordered) {
    const review = written.get(id)?.review ?? null;
    if (review) {
      verdicts[review.verdict] += 1;
      reviews[id] = { verdict: review.verdict, sessionId, summary: review.summary, position: null };
      continue;
    }
    const place = left.findIndex(([leftId]) => leftId === id);
    reviews[id] = {
      verdict: ended ? "no_verdict" : place > 0 ? "queued" : waiting ? "waiting" : "reviewing",
      sessionId,
      summary: null,
      position: !ended && place > 0 ? place : null,
    };
  }
  return {
    run: {
      sessionId,
      status: ended ? "ended" : waiting ? "waiting" : "running",
      total: ordered.length,
      reviewed: ordered.length - left.length,
      currentId: ended ? null : (left[0]?.[0] ?? null),
      verdicts,
      missing: ended ? left.length : 0,
    },
    reviews,
  };
}

function SessionVerdicts({
  sessionId,
  links,
  onRun,
}: {
  sessionId: string;
  links: readonly [string, ReviewLink][];
  onRun: (run: TriageRun, reviews: Record<string, ClaudeReview>) => void;
}) {
  const { state, error } = useAgentTranscript(sessionId);
  const key = JSON.stringify(runOf(sessionId, links, state, error !== null));
  useEffect(() => {
    const { run, reviews } = JSON.parse(key) as ReturnType<typeof runOf>;
    onRun(run, reviews);
  }, [key, onRun]);
  return null;
}

const DISMISSED_KEY = "ah.learning.triage.dismissed";
const MAX_DISMISSED = 50;

function readDismissed(): string[] {
  try {
    const value: unknown = JSON.parse(readStored(DISMISSED_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

/** Claude's reviews of `rows`, read live from the sessions linked to them. Mount `sources` once
 * (they render nothing); `reviewOf` gives a learning's state, `runs` each session's progress. */
export function useClaudeVerdicts(rows: readonly Learning[]) {
  const [reviews, setReviews] = useState<Record<string, ClaudeReview>>({});
  const [runs, setRuns] = useState<Record<string, TriageRun>>({});
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const [, setGeneration] = useState(0);
  const bySession = new Map<string, [string, ReviewLink][]>();
  for (const l of rows) {
    const link = readReviewLink(l.id);
    if (!link) continue;
    bySession.set(link.sessionId, [...(bySession.get(link.sessionId) ?? []), [l.id, link]]);
  }
  const [onRun] = useState(() => (run: TriageRun, next: Record<string, ClaudeReview>) => {
    setRuns((current) => ({ ...current, [run.sessionId]: run }));
    setReviews((current) => ({ ...current, ...next }));
  });
  const sources = [...bySession.entries()].map(([sessionId, links]) => (
    <SessionVerdicts key={sessionId} sessionId={sessionId} links={links} onRun={onRun} />
  ));
  const reviewOf = (l: Pick<Learning, "id">): ClaudeReview => {
    const link = readReviewLink(l.id);
    if (link === null) return NOT_REVIEWED;
    const known = reviews[l.id];
    // A fresh link whose session is not read yet: Claude is starting on it.
    return known?.sessionId === link.sessionId
      ? known
      : { verdict: "queued", sessionId: link.sessionId, summary: null, position: null };
  };
  return {
    sources,
    reviewOf,
    verdictOf: (l: Pick<Learning, "id">): ClaudeVerdict => reviewOf(l).verdict,
    /** The sessions over these learnings, newest knowledge first; dismissed finished ones left out. */
    runs: [...bySession.keys()]
      .map((sessionId) => runs[sessionId])
      .filter((run): run is TriageRun => run !== undefined)
      .filter((run) => run.status !== "ended" || !dismissed.includes(run.sessionId)),
    dismiss: (sessionId: string) => {
      const next = [...dismissed.filter((id) => id !== sessionId), sessionId].slice(-MAX_DISMISSED);
      writeStored(DISMISSED_KEY, JSON.stringify(next));
      setDismissed(next);
    },
    refresh: () => {
      setGeneration((g) => g + 1);
    },
  };
}
