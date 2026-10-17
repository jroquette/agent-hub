/* A learning reviewed by Claude: a session in the hub folder checks the note against /learn's bar
 * and writes its verdict and, when it helps, a revised body into a draft folder. Nothing is
 * accepted or committed by the agent: the owner reads the verdict and decides. */
import { readStored, removeStored, writeStored } from "../../lib/storage";
import type { TranscriptState } from "../agent-session/model";
import { draftDir, draftWrites } from "../skills/draft";

export type ReviewVerdict = "ready" | "needs_changes" | "not_for_brain";
export type CheckResult = "pass" | "fail" | "unknown";

export interface ReviewCheck {
  name: string;
  result: CheckResult;
  note: string;
}

export interface LearningReview {
  verdict: ReviewVerdict;
  summary: string;
  checks: ReviewCheck[];
  /** Where Claude suggests the note goes, relative to `brain/`; null when it has no opinion. */
  target: string | null;
}

/** The review a session wrote: its verdict (once written) and its revised body, if any. */
export interface ReviewWrites {
  review: LearningReview | null;
  /** The verdict file exists but does not parse: the session did not follow the format. */
  malformed: boolean;
  revision: string | null;
}

/** Which session reviews a learning and the draft folder it writes in, kept per learning. */
export interface ReviewLink {
  sessionId: string;
  draftId: string;
  /** The learning's place in a triage batch (0 first); absent for a single review. */
  order?: number | undefined;
}

export const REVIEW_FILE = "review.json";
export const REVISION_FILE = "note.md";
const PREFIX = "ah.learning.review.";
const VERDICTS: readonly ReviewVerdict[] = ["ready", "needs_changes", "not_for_brain"];
const RESULTS: readonly CheckResult[] = ["pass", "fail", "unknown"];

export function newReviewDraftId(random: () => number = Math.random): string {
  const suffix = Math.floor(random() * 36 ** 6)
    .toString(36)
    .padStart(6, "0");
  return `learning-${suffix}`;
}

export function readReviewLink(learningId: string): ReviewLink | null {
  const raw = readStored(PREFIX + learningId);
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (
      typeof value === "object" &&
      value !== null &&
      "sessionId" in value &&
      "draftId" in value &&
      typeof value.sessionId === "string" &&
      typeof value.draftId === "string"
    ) {
      const order = "order" in value && typeof value.order === "number" ? value.order : undefined;
      return { sessionId: value.sessionId, draftId: value.draftId, order };
    }
  } catch {
    // A link that does not parse is dropped.
  }
  return null;
}

export function saveReviewLink(learningId: string, link: ReviewLink): void {
  writeStored(PREFIX + learningId, JSON.stringify(link));
}

export function forgetReviewLink(learningId: string): void {
  removeStored(PREFIX + learningId);
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** The verdict file's JSON as a review, or null when it is not one. */
export function parseReview(text: string): LearningReview | null {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const verdict = VERDICTS.find((v) => v === record.verdict);
  if (verdict === undefined) return null;
  const checks = (Array.isArray(record.checks) ? record.checks : []).flatMap(
    (item: unknown): ReviewCheck[] => {
      if (typeof item !== "object" || item === null) return [];
      const check = item as Record<string, unknown>;
      const name = str(check.name);
      const result = RESULTS.find((r) => r === check.result) ?? "unknown";
      return name === null ? [] : [{ name, result, note: str(check.note) ?? "" }];
    },
  );
  const target = str(record.target)?.trim() ?? "";
  return {
    verdict,
    summary: str(record.summary) ?? "",
    checks,
    target: target === "" ? null : target.replace(/^brain\//, ""),
  };
}

/** What the session wrote in its draft folder so far. */
export function reviewWrites(state: TranscriptState, draftId: string): ReviewWrites {
  const files = draftWrites(state, draftId).files;
  const done = (name: string) => files.find((f) => f.path === name && !f.pending && !f.partial);
  const verdict = done(REVIEW_FILE);
  const review = verdict ? parseReview(verdict.content) : null;
  return {
    review,
    malformed: verdict !== undefined && review === null,
    revision: done(REVISION_FILE)?.content ?? null,
  };
}

export interface ReviewPromptInput {
  project: string;
  /** The inbox note, relative to the hub (`brain/_inbox/x.md`). */
  notePath: string;
  draftId: string;
  targetChoices: string[];
  suggestedTarget: string | null;
}

/** The bar every review holds a learning to: the /learn skill's criteria. */
const REVIEW_BAR = [
  "Hold it to the bar of the /learn skill (plugin/hub-workflow/skills/learn/SKILL.md when the hub has it):",
  "1. Non-obvious: a capable engineer new to this hub would not already know it.",
  "2. Verified: every claim checks out now. Open each cited path and line, run read-only commands where a claim depends on output, and say what you found.",
  "3. Not a duplicate: search brain/ (not brain/_inbox/) and the repos' AGENTS.md for the same knowledge.",
  "4. Well-placed and well-written: one learning, a clear title, the why, and where it applies.",
];

const reviewFileSpec = (dir: string) =>
  `\`${dir}/${REVIEW_FILE}\`: {"verdict": "ready" | "needs_changes" | "not_for_brain", "summary": "<two sentences>", "checks": [{"name": "Non-obvious" | "Verified" | "Not a duplicate" | "Well-written", "result": "pass" | "fail" | "unknown", "note": "<what you found, with paths>"}], "target": "<folder or .md path relative to brain/>"}`;
const revisionFileSpec = (dir: string) =>
  `\`${dir}/${REVISION_FILE}\`, only when the note should change before it is accepted: the full revised body, without the frontmatter. Fix what the checks found; keep the author's meaning.`;

/** The first message of a review session. */
export function reviewPrompt(input: ReviewPromptInput): string {
  const dir = draftDir(input.draftId);
  const choices = input.targetChoices.length > 0 ? input.targetChoices.join(", ") : "learnings/";
  return [
    `Review the proposed learning \`${input.notePath}\` of project ${input.project} before I decide whether it goes into the brain.`,
    "",
    ...REVIEW_BAR,
    "",
    `Pick where it belongs in brain/: one of ${choices}, or a better .md path${input.suggestedTarget ? ` (the note suggests ${input.suggestedTarget})` : ""}.`,
    "",
    `Write only inside \`${dir}/\`:`,
    `- ${reviewFileSpec(dir)}`,
    `- ${revisionFileSpec(dir)}`,
    "",
    "Do not edit the note itself or anything else, do not accept, reject, commit or push: I make the decision in agent-hub. When both files are written, reply with REVIEWED and the verdict in one line.",
  ].join("\n");
}

/** The most learnings one triage session reviews; the rest wait for the next run. */
export const MAX_TRIAGE_BATCH = 15;

export interface TriageItem {
  learningId: string;
  /** The inbox note, relative to the hub (`brain/_inbox/x.md`). */
  notePath: string;
}

export function newTriageBatchId(random: () => number = Math.random): string {
  const suffix = Math.floor(random() * 36 ** 6)
    .toString(36)
    .padStart(6, "0");
  return `triage-${suffix}`;
}

/** The draft folder of one learning in a triage batch: its review reads like a single review's. */
export const triageDraftId = (batchId: string, learningId: string) => `${batchId}/${learningId}`;

/** The first message of a triage session: one review per learning, each in its own folder. */
export function triagePrompt(input: {
  project: string;
  batchId: string;
  items: readonly TriageItem[];
}): string {
  const lines = input.items.map((item) => {
    const dir = draftDir(triageDraftId(input.batchId, item.learningId));
    return `- \`${item.notePath}\` → write in \`${dir}/\``;
  });
  const example = draftDir(triageDraftId(input.batchId, "<id>"));
  return [
    `Triage the ${String(input.items.length)} proposed learnings of project ${input.project} below before I decide which go into the brain. Review each one on its own, one after the other:`,
    "",
    ...lines,
    "",
    ...REVIEW_BAR,
    "",
    "Pick where each belongs in brain/ (a folder such as learnings/ or learnings/gotchas/, or a better .md path; the note's `target` frontmatter is a suggestion). Two notes that say the same thing: the weaker one is not_for_brain, and its summary names the other.",
    "",
    `For each learning, write only inside its own folder (\`${example}/\`):`,
    `- ${reviewFileSpec(example)}`,
    `- ${revisionFileSpec(example)}`,
    "",
    "Write each review.json as soon as that learning is reviewed, before moving to the next. Do not edit the notes or anything else, do not accept, reject, commit or push: I decide in agent-hub. At the end, reply with TRIAGED and one line per learning: its verdict and title.",
  ].join("\n");
}
