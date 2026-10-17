/* The Features list as an inbox: what needs the owner, what is moving, what shipped. */
import type { components } from "../../api/schema";
import { GOLDEN_STEP_LABEL, type IconName } from "../../components";
import { waitsOnOwner } from "./GoldenPathBar";
import { phaseIndex } from "./parts";

type Feature = components["schemas"]["FeatureView"];

export type GroupId = "needs" | "progress" | "shipped";

export const GROUPS: readonly { id: GroupId; title: string; hint: string; empty: string }[] = [
  {
    id: "needs",
    title: "Needs you",
    hint: "Owner steps to do, a NO-SHIP verdict or a record that cannot be read",
    empty:
      "Nothing needs you. Features show here when they wait on your owner steps, get a NO-SHIP verdict or have a record that cannot be read.",
  },
  {
    id: "progress",
    title: "In progress",
    hint: "Furthest along first",
    empty: "No feature in progress.",
  },
  { id: "shipped", title: "Shipped", hint: "", empty: "No feature shipped yet." },
];

export type Tone = "blocked" | "failed" | "waiting" | "done";

/** Why a feature sits in its group: the lead icon, the one line under its name and the tab it opens. */
export interface Reason {
  group: GroupId;
  /** Orders the Needs you group: a broken record first, then NO-SHIP, then owner steps. */
  rank: number;
  icon: IconName | null;
  tone: Tone | null;
  line: string;
  doc: string | null;
}

/** The eval's verdict line without its markdown. */
export const plainVerdictLine = (line: string) => line.replace(/\*\*|`/g, "").trim();

const plural = (n: number, word: string) => `${String(n)} ${word}${n === 1 ? "" : "s"}`;

/** The current step's meta without its "N/M ACs" part, which the ACs column already shows. */
function stepMeta(meta: string | null): string | null {
  const parts = (meta ?? "").split(" · ").filter((p) => p && !/^\d+\/\d+ ACs$/.test(p));
  return parts.length ? parts.join(" · ") : null;
}

export function reasonOf(f: Feature): Reason {
  if (f.problem) {
    return {
      group: "needs",
      rank: 0,
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
      rank: 1,
      icon: "circle-x",
      tone: "failed",
      line: why ? `Evaluator says NO-SHIP: ${why}` : "Evaluator says NO-SHIP",
      doc: "eval",
    };
  }
  if (f.phase !== "shipped" && waitsOnOwner(f.golden_path)) {
    const n = f.acs?.owner_steps ?? 0;
    return {
      group: "needs",
      rank: 2,
      icon: "hand",
      tone: "waiting",
      line: n ? `${plural(n, "owner step")} to do` : "Owner steps to do",
      doc: "acs",
    };
  }
  if (f.phase === "shipped") {
    return {
      group: "shipped",
      rank: 0,
      icon: "circle-check",
      tone: "done",
      line: "Shipped",
      doc: null,
    };
  }
  const steps = f.golden_path.steps;
  const at = steps.findIndex((s) => s.name === f.phase);
  const step = steps[at];
  const parts = [
    `${GOLDEN_STEP_LABEL[f.phase]} · step ${String(at + 1)} of ${String(steps.length)}`,
  ];
  const meta = stepMeta(step?.meta ?? null);
  if (meta) parts.push(meta);
  if (step?.state === "unknown" && step.reason) parts.push(step.reason);
  return { group: "progress", rank: 0, icon: null, tone: null, line: parts.join(" · "), doc: null };
}

function stepRatio(f: Feature): number {
  const p = f.golden_path.steps.find((s) => s.name === f.phase)?.progress;
  return p && p.total > 0 ? p.done / p.total : 0;
}

function acRatio(f: Feature): number {
  const a = f.acs;
  return a && a.total > 0 ? (a.passing + a.owner_steps) / a.total : 0;
}

/** Orders rows inside one group: by reason, furthest along, most done, then by name. */
export function byGroupOrder(a: Feature, b: Feature): number {
  const ra = reasonOf(a);
  const rb = reasonOf(b);
  return (
    ra.rank - rb.rank ||
    phaseIndex(b.phase) - phaseIndex(a.phase) ||
    stepRatio(b) - stepRatio(a) ||
    acRatio(b) - acRatio(a) ||
    a.slug.localeCompare(b.slug)
  );
}

/** The issue id at the head of an entry ("AGH-200 (provisional …)" → "AGH-200"). */
const ISSUE_ID = /^[A-Z][A-Z0-9]*-\d+/;
export const issueId = (raw: string): string => ISSUE_ID.exec(raw.trim())?.[0] ?? raw.trim();

/** Case-insensitive match on the name, project, repos and issue ids; every word must match. */
export function matchesQuery(f: Feature, q: string): boolean {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = [f.slug, f.project, ...f.repos, ...f.issues.map(issueId)].join(" ").toLowerCase();
  return words.every((w) => hay.includes(w));
}
