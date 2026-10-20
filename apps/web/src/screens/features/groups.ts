/* The Features list: what is moving (with a warning on the rows that need the owner), what was evaluated, what shipped. */
import type { components } from "../../api/schema";
import { GOLDEN_STEP_LABEL, ownerWaitStep, type IconName } from "../../components";
import { waitsOnOwner } from "./GoldenPathBar";
import { phaseIndex } from "./parts";

type Feature = components["schemas"]["FeatureView"];
type LiveTile = components["schemas"]["LiveTile"];

export type GroupId = "progress" | "evaluated" | "shipped";

export const GROUPS: readonly {
  id: GroupId;
  title: string;
  /** The words after the count in the page's summary line. */
  summary: string;
  hint: string;
  empty: string;
}[] = [
  {
    id: "progress",
    title: "In progress",
    summary: "in progress",
    hint: "What needs you first, then furthest along and most ACs passing",
    empty: "No feature in progress.",
  },
  {
    id: "evaluated",
    title: "Evaluated",
    summary: "evaluated",
    hint: "The evaluator said ship and every AC passes; shipped once the tickets are read as done",
    empty: "No feature waits on its tickets after a ship verdict.",
  },
  {
    id: "shipped",
    title: "Shipped",
    summary: "shipped",
    hint: "",
    empty: "No feature shipped yet.",
  },
];

/** A verdict in words, for a row's line: the codes stay in the eval. */
export const VERDICT_WORDS: Record<NonNullable<Feature["verdict"]>, string> = {
  SHIP: "evaluator says ship",
  "SHIP-WITH-OWNER-STEPS": "evaluator says ship after your steps",
  "NO-SHIP": "evaluator says no ship",
};

export type Tone = "blocked" | "failed" | "waiting" | "done";

/** Why a feature sits in its group: the lead icon, the one line under its name and the tab it opens. */
export interface Reason {
  group: GroupId;
  /**
   * Why the row needs the owner, shown as a warning on it: a session that waits on you (a permission
   * or your reply), a broken record, NO-SHIP, or owner steps.
   */
  needs: Needs | null;
  icon: IconName | null;
  tone: Tone | null;
  line: string;
  doc: string | null;
}

/** The kinds of warning, in the order they lead In progress. */
export const NEEDS_ORDER = ["session", "your-turn", "problem", "no-ship", "owner-steps"] as const;
export type Needs = (typeof NEEDS_ORDER)[number];

/** A live session working on a feature that waits on you: a permission prompt, or your reply. */
export interface SessionWait {
  tile: LiveTile;
  /** `waiting`: a permission or question is open; `idle`: the turn ended and it is yours. */
  group: "waiting" | "idle";
}

/**
 * The session that waits on you for this feature, if any: a live tile whose issue (from its branch,
 * worktree or first prompt) is one of the feature's, or whose title names the feature. A waiting
 * one wins over an idle one, then the most recent.
 */
export function sessionWaitOf(f: Feature, tiles: readonly LiveTile[]): SessionWait | null {
  const ids = new Set(f.issues.map((i) => issueId(i).toUpperCase()));
  const ofFeature = (t: LiveTile) => {
    const issue = (t.label?.issue ?? t.issue ?? "").toUpperCase();
    return (issue !== "" && ids.has(issue)) || (t.label?.title ?? "").includes(f.slug);
  };
  const waits = tiles
    .filter((t) => (t.group === "waiting" || t.group === "idle") && !t.is_subagent && ofFeature(t))
    .sort(
      (a, b) =>
        Number(b.group === "waiting") - Number(a.group === "waiting") ||
        b.last_activity_at.localeCompare(a.last_activity_at),
    );
  const tile = waits[0];
  return tile ? { tile, group: tile.group === "waiting" ? "waiting" : "idle" } : null;
}

function sessionReason(wait: SessionWait): Reason {
  const { tile } = wait;
  if (wait.group === "waiting") {
    const why = tile.waiting_reason ?? "a permission prompt";
    return {
      group: "progress",
      needs: "session",
      icon: "shield-alert",
      tone: "waiting",
      line: `A session waits on you · ${why}`,
      doc: null,
    };
  }
  const last = tile.last_action ? ` · ${tile.last_action}` : "";
  return {
    group: "progress",
    needs: "your-turn",
    icon: "message-square",
    tone: "waiting",
    line: `Your turn in a session${last}`,
    doc: null,
  };
}

/** The eval's verdict line without its markdown. */
export const plainVerdictLine = (line: string) => line.replace(/\*\*|`/g, "").trim();

const plural = (n: number, word: string) => `${String(n)} ${word}${n === 1 ? "" : "s"}`;

/** How many ACs wait on the owner: the AC counts, else the Acceptance step's reason ("3 ACs wait on owner steps …"). */
export function ownerStepCount(f: Feature): number {
  if (f.acs?.owner_steps) return f.acs.owner_steps;
  const reason = ownerWaitStep(f.golden_path.steps)?.reason ?? "";
  return Number(/^(\d+) ACs?\b/.exec(reason)?.[1] ?? 0);
}

/**
 * What the eval says beyond its verdict, so rows that share a verdict still differ:
 * "**Verdict: SHIP-WITH-OWNER-STEPS.** The code is ready…" → "The code is ready…".
 */
export function verdictDetail(line: string | null): string | null {
  if (!line) return null;
  const text = plainVerdictLine(line)
    .replace(/^#+\s*/, "")
    .replace(/^(final\s+)?verdict\s*:?\s*[A-Z][A-Z-]*\b[\s.,:;)-]*/i, "")
    .trim();
  return text.length > 2 ? text : null;
}

function ownerLine(f: Feature): string {
  const n = ownerStepCount(f);
  const head = n ? `${plural(n, "step")} left for you` : "Your steps are left";
  const detail = verdictDetail(f.verdict_line);
  return detail ? `${head} · ${detail}` : `${head} · open the ACs to see them`;
}

/** A step reason that only says Linear was not read: the page says it once, not every row. */
export const isLinearGap = (reason: string | null) =>
  reason !== null && /Linear not (loaded|read|connected)|from Linear not loaded/i.test(reason);

/** Whether any feature's golden path is missing ticket status from Linear. */
export const missesLinear = (features: readonly Feature[]) =>
  features.some((f) => f.golden_path.steps.some((s) => isLinearGap(s.reason)));

/** Every AC passes (owner steps counted as done). */
const allAcsPass = (f: Feature) =>
  f.acs !== null && f.acs.total > 0 && f.acs.passing + f.acs.owner_steps >= f.acs.total;

/** A step's reason for the row's line, short; the Linear one is said once above the list. */
function shortReason(reason: string): string | null {
  return isLinearGap(reason) ? null : reason.replace(/[.;]\s*open the \w+ tab\.?$/i, "");
}

export function reasonOf(f: Feature, wait: SessionWait | null = null): Reason {
  if (wait && f.phase !== "shipped") return sessionReason(wait);
  if (f.problem) {
    return {
      group: "progress",
      needs: "problem",
      icon: "octagon-x",
      tone: "blocked",
      line: `${f.problem}. Fix it in a hub PR.`,
      doc: null,
    };
  }
  if (f.phase !== "shipped" && f.verdict === "NO-SHIP") {
    const why = f.verdict_line ? plainVerdictLine(f.verdict_line) : "";
    return {
      group: "progress",
      needs: "no-ship",
      icon: "circle-x",
      tone: "failed",
      line: why ? `Evaluator says no ship: ${verdictDetail(why) ?? why}` : "Evaluator says no ship",
      doc: "eval",
    };
  }
  if (f.phase !== "shipped" && waitsOnOwner(f.golden_path)) {
    return {
      group: "progress",
      needs: "owner-steps",
      icon: "hand",
      tone: "waiting",
      line: ownerLine(f),
      doc: "acs",
    };
  }
  if (f.phase === "shipped") {
    return {
      group: "shipped",
      needs: null,
      icon: "circle-check",
      tone: "done",
      line: "Shipped",
      doc: null,
    };
  }
  if (f.verdict === "SHIP" && allAcsPass(f)) {
    const detail = verdictDetail(f.verdict_line);
    return {
      group: "evaluated",
      needs: null,
      icon: "circle-check",
      tone: null,
      line: detail
        ? `Evaluator says ship · ${detail}`
        : "Evaluator says ship · tickets not read as done",
      doc: "eval",
    };
  }
  const steps = f.golden_path.steps;
  const at = steps.findIndex((s) => s.name === f.phase);
  const step = steps[at];
  // The Golden path column shows where the step sits; the line says what happens in it.
  const parts = [GOLDEN_STEP_LABEL[f.phase]];
  // Build's meta says when Linear was not read: the page says it once, not every row.
  const meta = step?.meta && !isLinearGap(step.meta) ? step.meta : null;
  if (meta) parts.push(meta);
  const why = step?.reason && step.state !== "done" ? shortReason(step.reason) : null;
  if (why) parts.push(why);
  if (f.verdict) parts.push(VERDICT_WORDS[f.verdict]);
  if (parts.length === 1) parts.push(`step ${String(at + 1)} of ${String(steps.length)}`);
  return {
    group: "progress",
    needs: null,
    icon: null,
    tone: null,
    line: parts.join(" · "),
    doc: null,
  };
}

function stepRatio(f: Feature): number {
  const p = f.golden_path.steps.find((s) => s.name === f.phase)?.progress;
  return p && p.total > 0 ? p.done / p.total : 0;
}

function acRatio(f: Feature): number {
  const a = f.acs;
  return a && a.total > 0 ? (a.passing + a.owner_steps) / a.total : 0;
}

const needsRank = (r: Reason) => (r.needs ? NEEDS_ORDER.indexOf(r.needs) : NEEDS_ORDER.length);

/** Orders rows inside one group: the ones that need you first, then furthest along, most done, then by name. */
export function byGroupOrder(
  a: Feature,
  b: Feature,
  reason: (f: Feature) => Reason = reasonOf,
): number {
  return (
    needsRank(reason(a)) - needsRank(reason(b)) ||
    phaseIndex(b.phase) - phaseIndex(a.phase) ||
    stepRatio(b) - stepRatio(a) ||
    acRatio(b) - acRatio(a) ||
    a.slug.localeCompare(b.slug)
  );
}

/** The issue id at the head of an entry ("AGH-200 (provisional …)" → "AGH-200"). */
const ISSUE_ID = /^[A-Z][A-Z0-9]*-\d+/;
export const issueId = (raw: string): string => ISSUE_ID.exec(raw.trim())?.[0] ?? raw.trim();

/** Case-insensitive match on the nickname, slug, project, repos and issue ids; every word must match. */
export function matchesQuery(f: Feature, q: string, name: string | null = null): boolean {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = [name ?? "", f.slug, f.project, ...f.repos, ...f.issues.map(issueId)]
    .join(" ")
    .toLowerCase();
  return words.every((w) => hay.includes(w));
}
