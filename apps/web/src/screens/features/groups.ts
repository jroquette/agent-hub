/* The Features list: what is moving (with a warning on the rows that need the owner) and what shipped. */
import type { components } from "../../api/schema";
import { ownerWaitStep, type IconName } from "../../components";
import { phaseIndex } from "./parts";

type Feature = components["schemas"]["FeatureView"];
type LiveTile = components["schemas"]["LiveTile"];

export type GroupId = "needs" | "active" | "ready" | "quiet" | "paused" | "done";

/** A feature with no activity for this many days, and no session on it, is Quiet. */
export const QUIET_DAYS = 14;

export const GROUPS: readonly {
  id: GroupId;
  title: string;
  /** The words after the count in the page's summary line. */
  summary: string;
  hint: string;
  empty: string;
  /** Folded until the owner opens it. */
  folded: boolean;
}[] = [
  {
    id: "needs",
    title: "Needs you",
    summary: "need you",
    hint: "Work that stops until you act: a session waiting, a plan change, a no-ship verdict, a broken record",
    empty: "Nothing needs you.",
    folded: false,
  },
  {
    id: "active",
    title: "Active",
    summary: "active",
    hint: `Worked on in the last ${String(QUIET_DAYS)} days, the ones a session works on now first`,
    empty: "No feature is moving.",
    folded: false,
  },
  {
    id: "ready",
    title: "Ready to close",
    summary: "ready to close",
    hint: "The evaluator says ship. Sign off your checks, or mark them shipped or closed in bulk",
    empty: "Nothing waits to be closed.",
    folded: false,
  },
  {
    id: "quiet",
    title: "Quiet",
    summary: "quiet",
    hint: `No activity for ${String(QUIET_DAYS)} days or more. Close or pause what will not move`,
    empty: "No quiet feature.",
    folded: true,
  },
  {
    id: "paused",
    title: "Paused",
    summary: "paused",
    hint: "You set these aside. Reopen one from its page",
    empty: "No paused feature.",
    folded: true,
  },
  {
    id: "done",
    title: "Shipped and closed",
    summary: "shipped or closed",
    hint: "",
    empty: "No feature shipped or closed yet.",
    folded: true,
  },
];

/** Days since a `YYYY-MM-DD` or ISO date, at `now`; null without one. */
export function daysAgo(date: string | null | undefined, now: number): number | null {
  if (!date) return null;
  const at = Date.parse(date.length === 10 ? `${date}T00:00:00Z` : date);
  return Number.isNaN(at) ? null : Math.max(0, Math.floor((now - at) / 86_400_000));
}

/** The newest of the records' date and the live sessions' last activity on the feature. */
export function lastActivityOf(f: Feature, tiles: readonly LiveTile[] = []): string | null {
  const dates = [f.last_activity_on, ...tilesOf(f, tiles).map((t) => t.last_activity_at)].filter(
    (d): d is string => Boolean(d),
  );
  return dates.reduce<string | null>(
    (best, d) => (best === null || Date.parse(d) > Date.parse(best) ? d : best),
    null,
  );
}

/** "today", "yesterday", "5 days ago". */
export function agoWords(days: number | null): string {
  if (days === null) return "no date";
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  return `${String(days)} days ago`;
}

/** A verdict in words, for a row's line: the codes stay in the eval. */
export const VERDICT_WORDS: Record<NonNullable<Feature["verdict"]>, string> = {
  SHIP: "Ready to ship",
  "SHIP-WITH-OWNER-STEPS": "Ready to ship after your manual checks",
  "NO-SHIP": "Not ready to ship",
};

/** What happens next at each step, in plain words, for a row whose step has nothing else to say. */
const NEXT_AT: Record<Feature["phase"], string> = {
  spec: "Next: write the spec",
  ux_design: "Next: design the screens",
  research: "Next: research the code",
  plan: "Next: write the plan",
  tickets: "Next: create the tickets",
  build: "Building",
  acceptance: "Next: evaluate the whole feature",
  shipped: "Shipped",
};

/** "3 of 10 tickets merged": the step's count in words, where it has one worth saying. */
function progressWords(phase: Feature["phase"], done: number, total: number): string | null {
  const n = `${String(done)} of ${String(total)}`;
  if (phase === "build") return `${n} tickets merged`;
  if (phase === "tickets") return `${n} tickets created`;
  if (phase === "ux_design") return `${n} designs approved`;
  return null;
}

export type Tone = "blocked" | "failed" | "waiting" | "done";

/** Why a feature sits in its group: the lead icon, the one line under its name and the tab it opens. */
export interface Reason {
  group: GroupId;
  /**
   * Why the row needs the owner, shown as a warning on it: a session that waits on you (a permission
   * or your reply), a broken record, NO-SHIP, a plan change request, owner steps to sign off, or a
   * sign-off to write by hand.
   */
  needs: Needs | null;
  icon: IconName | null;
  tone: Tone | null;
  line: string;
  /** The row's link query after `doc=` (a tab, or the ticket panel at a change request). */
  doc: string | null;
  /** How many sessions work on the feature right now (live, not subagents): the row's live dot. */
  working: number;
  /** The row's line as it would read with no session working, for its tooltip and screen-reader name. */
  plainLine: string;
}

/** The kinds of warning, in the order they lead In progress. */
export const NEEDS_ORDER = [
  "session",
  "your-turn",
  "problem",
  "no-ship",
  "change-request",
  "owner-steps",
  "owner-manual",
] as const;
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
  const waits = tilesOf(f, tiles)
    .filter((t) => t.group === "waiting" || t.group === "idle")
    .sort(
      (a, b) =>
        Number(b.group === "waiting") - Number(a.group === "waiting") ||
        b.last_activity_at.localeCompare(a.last_activity_at),
    );
  const tile = waits[0];
  return tile ? { tile, group: tile.group === "waiting" ? "waiting" : "idle" } : null;
}

/** The main-session tiles (not subagents) whose issue is one of the feature's, or whose title names it. */
function tilesOf(f: Feature, tiles: readonly LiveTile[]): LiveTile[] {
  const ids = new Set(f.issues.map((i) => issueId(i).toUpperCase()));
  return tiles.filter((t) => {
    if (t.is_subagent) return false;
    const issue = (t.label?.issue ?? t.issue ?? "").toUpperCase();
    return (issue !== "" && ids.has(issue)) || (t.label?.title ?? "").includes(f.slug);
  });
}

/** The sessions working on the feature right now (`live`), the most recent first. */
export function sessionsWorkingOn(f: Feature, tiles: readonly LiveTile[]): LiveTile[] {
  return tilesOf(f, tiles)
    .filter((t) => t.group === "live")
    .sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at));
}

/** "A session is working · Edited groups.ts", "2 sessions are working · …". */
export function workingLine(working: readonly LiveTile[]): string {
  const [latest] = working;
  const head =
    working.length === 1
      ? "A session is working"
      : `${String(working.length)} sessions are working`;
  return latest?.last_action ? `${head} · ${latest.last_action}` : head;
}

function sessionReason(wait: SessionWait): BaseReason {
  const { tile } = wait;
  if (wait.group === "waiting") {
    const why = tile.waiting_reason ?? "a permission prompt";
    return {
      group: "needs",
      needs: "session",
      icon: "shield-alert",
      tone: "waiting",
      line: `A session waits on you · ${why}`,
      doc: null,
    };
  }
  const last = tile.last_action ? ` · ${tile.last_action}` : "";
  return {
    group: "needs",
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

/** How many ACs wait on the owner: the AC counts, else the waiting Acceptance step's reason ("3 ACs wait on owner steps …"). */
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

/** A step reason that only says Linear was not read: the page says it once, not every row. */
export const isLinearGap = (reason: string | null) =>
  reason !== null && /Linear not (loaded|read|connected)|from Linear not loaded/i.test(reason);

/** Whether any feature's golden path is missing ticket status from Linear. */
export const missesLinear = (features: readonly Feature[]) =>
  features.some((f) => f.golden_path.steps.some((s) => isLinearGap(s.reason)));

/** A step's reason for the row's line, short; the Linear one is said once above the list. */
function shortReason(reason: string): string | null {
  return isLinearGap(reason) ? null : reason.replace(/[.;]\s*open the \w+ tab\.?$/i, "");
}

type BaseReason = Omit<Reason, "working" | "plainLine">;

/**
 * Why the row sits where it does. The owner's own decision wins (shipped, closed, paused); then what
 * stops work until the owner acts (Needs you); then finished code that waits to be closed (Ready to
 * close); then the rest, Active or Quiet by its last activity. A session working on the feature puts
 * the live dot on the row and keeps it Active. The shell's badge counts the Needs you rows on the
 * server, with the same rule in `agent_hub/core/features/owner_needs.py` (ADR 0056): a change to
 * one changes the other.
 */
export function reasonOf(
  f: Feature,
  wait: SessionWait | null = null,
  working: readonly LiveTile[] = [],
  lastActivity: string | null = f.last_activity_on ?? null,
  now: number = Date.now(),
): Reason {
  const base = baseReasonOf(f, wait);
  const plain = { ...base, working: working.length, plainLine: base.line };
  if (base.group === "active") {
    const days = daysAgo(lastActivity, now);
    if (!working.length && days !== null && days >= QUIET_DAYS) {
      const line = `No activity for ${String(days)} days · ${base.line}`;
      return { ...plain, group: "quiet", line, plainLine: line };
    }
  }
  if (!working.length || base.needs !== null || base.group !== "active") return plain;
  return { ...plain, line: workingLine(working) };
}

function decidedReason(f: Feature): BaseReason | null {
  const decided = f.owner_status;
  if (!decided) return null;
  const on = decided.decided_at ? ` on ${decided.decided_at.slice(0, 10)}` : "";
  const note = decided.note ? ` · ${decided.note}` : "";
  if (decided.status === "paused") {
    return {
      group: "paused",
      needs: null,
      icon: "circle-pause",
      tone: null,
      line: `Paused by you${on}${note}`,
      doc: null,
    };
  }
  return {
    group: "done",
    needs: null,
    icon: decided.status === "shipped" ? "circle-check" : "circle-stop",
    tone: decided.status === "shipped" ? "done" : null,
    line: `${decided.status === "shipped" ? "Shipped" : "Closed without shipping"} by you${on}${note}`,
    doc: null,
  };
}

/** Whether the evaluator's whole-feature verdict says ship and every criterion is met or the owner's. */
function evaluatedToShip(f: Feature): boolean {
  if (f.verdict !== "SHIP" && f.verdict !== "SHIP-WITH-OWNER-STEPS") return false;
  const a = f.acs;
  return !a || a.total === 0 || a.passing + a.owner_steps >= a.total;
}

function baseReasonOf(f: Feature, wait: SessionWait | null): BaseReason {
  const decided = decidedReason(f);
  if (decided) return decided;
  if (wait && f.phase !== "shipped") return sessionReason(wait);
  if (f.problem) {
    return {
      group: "needs",
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
      group: "needs",
      needs: "no-ship",
      icon: "circle-x",
      tone: "failed",
      line: why ? `Evaluator says no ship: ${verdictDetail(why) ?? why}` : "Evaluator says no ship",
      doc: "eval",
    };
  }
  const kind = f.phase !== "shipped" ? f.waiting_on_owner?.kind : undefined;
  if (kind === "change_request") {
    const tickets = f.waiting_on_owner?.tickets ?? [];
    const [first = ""] = tickets;
    return {
      group: "needs",
      needs: "change-request",
      icon: "hand",
      tone: "waiting",
      line:
        tickets.length > 1
          ? `${String(tickets.length)} plan changes wait for you · from ${tickets.join(", ")}`
          : `Plan change waits for you · from ${first}`,
      doc: `tickets&ticket=${encodeURIComponent(first)}&step=preflight`,
    };
  }
  if (f.phase === "shipped") {
    return {
      group: "done",
      needs: null,
      icon: "circle-check",
      tone: "done",
      line: "Shipped",
      doc: null,
    };
  }
  if (kind === "owner_signoff") {
    const n = ownerStepCount(f);
    return {
      group: "ready",
      needs: null,
      icon: "hand",
      tone: null,
      line: n
        ? `Sign off ${plural(n, "check")} of yours, or close it`
        : "Sign off your checks, or close it",
      doc: "acs",
    };
  }
  if (kind === "owner_signoff_manual") {
    return {
      group: "ready",
      needs: null,
      icon: "hand",
      tone: null,
      line: "Evaluator says ship after your checks · no ACs listed, mark it shipped or close it",
      doc: "eval",
    };
  }
  if (evaluatedToShip(f)) {
    const step = f.golden_path.steps.find((st) => st.name === f.phase);
    const left =
      step?.progress && step.progress.total > 0 && step.state !== "unknown"
        ? ` · ${progressWords(f.phase, step.progress.done, step.progress.total) ?? ""}`
        : "";
    return {
      group: "ready",
      needs: null,
      icon: "circle-check",
      tone: null,
      line: `Evaluator says ship · records still show ${GOLDEN_WORDS[f.phase]}${left}`.replace(
        / · $/,
        "",
      ),
      doc: null,
    };
  }
  const step = f.golden_path.steps.find((s) => s.name === f.phase);
  // The Stage column names the step; the line says what comes next there, in plain words.
  const parts: string[] = [];
  if (step?.state === "blocked" && step.reason && !isLinearGap(step.reason)) {
    parts.push(`Blocked: ${shortReason(step.reason) ?? step.reason}`);
  } else if (step?.state === "stale") {
    parts.push("Needs a new evaluation");
  } else {
    parts.push(NEXT_AT[f.phase]);
    const p = step?.progress;
    // An unknown step's count was not read: the notice above the list says so once.
    const known = p && p.total > 0 && step.state !== "unknown";
    const count = known ? progressWords(f.phase, p.done, p.total) : null;
    if (count) parts.push(count);
  }
  return {
    group: "active",
    needs: null,
    icon: null,
    tone: null,
    line: parts.join(" · "),
    doc: null,
  };
}

/** The step's name in a sentence ("records still show Build"). */
const GOLDEN_WORDS: Record<Feature["phase"], string> = {
  spec: "Spec",
  ux_design: "UX design",
  research: "Research",
  plan: "Plan",
  tickets: "Tickets",
  build: "Build",
  acceptance: "Acceptance",
  shipped: "Shipped",
};

function stepRatio(f: Feature): number {
  const p = f.golden_path.steps.find((s) => s.name === f.phase)?.progress;
  return p && p.total > 0 ? p.done / p.total : 0;
}

function acRatio(f: Feature): number {
  const a = f.acs;
  return a && a.total > 0 ? (a.passing + a.owner_steps) / a.total : 0;
}

/** The sort's ranks: the warnings in their order, with a session working right after the session warnings. */
const RANK_ORDER = ["session", "your-turn", "working", ...NEEDS_ORDER.slice(2)] as const;
function needsRank(r: Reason): number {
  const key = r.needs ?? (r.working > 0 ? "working" : null);
  return key ? RANK_ORDER.indexOf(key) : RANK_ORDER.length;
}

/**
 * Orders rows inside one group: the ones that need you first (by kind), then the ones a session works
 * on, then the newest activity, then furthest along, then by name.
 */
export function byGroupOrder(
  a: Feature,
  b: Feature,
  reason: (f: Feature) => Reason = reasonOf,
  activity: (f: Feature) => string | null = (f) => f.last_activity_on ?? null,
): number {
  const at = (f: Feature) => {
    const d = activity(f);
    return d ? Date.parse(d.length === 10 ? `${d}T00:00:00Z` : d) || 0 : 0;
  };
  return (
    needsRank(reason(a)) - needsRank(reason(b)) ||
    at(b) - at(a) ||
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
