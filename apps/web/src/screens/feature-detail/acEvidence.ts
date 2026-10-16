/**
 * What an acceptance criterion's evidence says, read from the free text the evaluator writes in
 * `features.json` (e.g. "Demo_API@780917525 (= merged b811fca72, PR #2374), 2026-10-16,
 * whole-feature eval: … exit 0, 10 passed, 42 deselected; red on merge base 38290da11 (ImportError …).
 * evals/feature.md"). The text has no fixed shape, so every fact is optional and the original text
 * is always kept: the facts are derived, the text is the record.
 */

export interface EvidenceCommit {
  repo: string | null;
  sha: string;
}

export interface EvidencePr {
  repo: string | null;
  number: string;
}

export interface EvidenceResult {
  /** The first exit code named, as written ("0", "2"). */
  exit: string | null;
  passed: number | null;
  failed: number | null;
  deselected: number | null;
}

export interface EvidenceFacts {
  /** "superseded", "dropped" or "partial" when the text opens with it. */
  standing: "superseded" | "dropped" | "partial" | null;
  commits: EvidenceCommit[];
  prs: EvidencePr[];
  /** The first ISO date in the text (YYYY-MM-DD). */
  date: string | null;
  result: EvidenceResult | null;
  /** The clause that says the check failed before the change ("red on merge base 38290da11 (…)"). */
  redOnBase: string | null;
  /** `DataMode=` values, the environment the check ran in. */
  environments: string[];
  /** Eval files the text points to, brain-relative to the feature folder ("evals/feature.md"). */
  evalFiles: string[];
  /** Eval deliveries named as "eval demo-1562" / "DEMO-1538 eval". */
  evalDeliveries: string[];
  /** Tracker ids named in the text (DEMO-1552), AC ids excluded. */
  issues: string[];
  /** True when the text says a manual check is still an owner step. */
  ownerCheckOpen: boolean;
}

const unique = <T>(items: T[]): T[] => [...new Set(items)];

const COMMIT = /(?:\b([A-Za-z][\w.-]*)@|@\s?)([0-9a-f]{7,40})\b/g;
const PR_HASH = /\bPR\s*#(\d+)/g;
const REPO_PR = /\b([A-Za-z][\w.-]*)#(\d+)\b/g;
const DATE = /\b(\d{4}-\d{2}-\d{2})\b/;
const EXIT = /\bexit\s+(\d+)/;
const COUNT = (word: string) => new RegExp(`\\b(\\d+)\\s+${word}\\b`);
const RED =
  /\b(?:(?:all \d+|new files|\d+ new tests) )?red (?:on|at) (?:merge )?base\b.*?(?=;|\.\s|\.$|$)|\bred at [0-9a-f]{7,40}\b.*?(?=;|\.\s|\.$|$)/i;
const DATAMODE = /\bDataMode=(\w+)/g;
const EVAL_FILE = /\bevals\/[\w.-]+\.md\b/g;
const EVAL_NAMED = /\beval\s+(tip-\d+)\b|\b(TIP-\d+)\s+eval\b/gi;
const ISSUE = /\b(?!AC-)([A-Z][A-Z0-9]{1,9}-\d{2,})\b/g;
const OWNER_OPEN = /still an owner step|owner step still|owner-reported, not observed/i;

function standingOf(text: string): EvidenceFacts["standing"] {
  const head = text.trimStart().slice(0, 16).toLowerCase();
  if (head.startsWith("superseded")) return "superseded";
  if (head.startsWith("dropped")) return "dropped";
  if (head.startsWith("partial")) return "partial";
  return null;
}

function resultOf(text: string): EvidenceResult | null {
  const exit = EXIT.exec(text)?.[1] ?? null;
  const num = (word: string) => {
    const m = COUNT(word).exec(text);
    return m?.[1] ? Number(m[1]) : null;
  };
  const result = {
    exit,
    passed: num("passed"),
    failed: num("failed"),
    deselected: num("deselected"),
  };
  return result.exit === null && result.passed === null && result.failed === null ? null : result;
}

/** The facts the evidence text states; empty facts (and `null`s) for what it does not. */
export function parseEvidence(text: string): EvidenceFacts {
  const commits = [...text.matchAll(COMMIT)].map((m) => ({ repo: m[1] ?? null, sha: m[2] ?? "" }));
  const prs = [
    ...[...text.matchAll(PR_HASH)].map((m) => ({ repo: null, number: m[1] ?? "" })),
    ...[...text.matchAll(REPO_PR)].map((m) => ({ repo: m[1] ?? null, number: m[2] ?? "" })),
  ];
  const deliveries = [...text.matchAll(EVAL_NAMED)].map((m) => (m[1] ?? m[2] ?? "").toLowerCase());
  return {
    standing: standingOf(text),
    commits: commits.filter(
      (c, i) => commits.findIndex((o) => o.sha === c.sha && o.repo === c.repo) === i,
    ),
    prs: prs.filter((p, i) => prs.findIndex((o) => o.number === p.number) === i),
    date: DATE.exec(text)?.[1] ?? null,
    result: resultOf(text),
    redOnBase: RED.exec(text)?.[0].trim().replace(/[.,]$/, "") ?? null,
    environments: unique([...text.matchAll(DATAMODE)].map((m) => m[1] ?? "")),
    evalFiles: unique([...text.matchAll(EVAL_FILE)].map((m) => m[0])),
    evalDeliveries: unique(deliveries),
    issues: unique([...text.matchAll(ISSUE)].map((m) => m[1] ?? "")),
    ownerCheckOpen: OWNER_OPEN.test(text),
  };
}

/** "exit 0 · 10 passed · 42 deselected", or null when no result is stated. */
export function resultLine(result: EvidenceResult | null): string | null {
  if (!result) return null;
  return [
    result.exit !== null ? `exit ${result.exit}` : null,
    result.passed !== null ? `${String(result.passed)} passed` : null,
    result.failed !== null ? `${String(result.failed)} failed` : null,
    result.deselected !== null ? `${String(result.deselected)} deselected` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Whether the stated result is green: exit 0 and nothing failed. */
export function resultPassed(result: EvidenceResult | null): boolean | null {
  if (!result) return null;
  if (result.exit !== null) return result.exit === "0" && !result.failed;
  return result.failed === null || result.failed === 0;
}

/** A short commit for display: 7 hex characters. */
export const shortSha = (sha: string) => sha.slice(0, 7);
