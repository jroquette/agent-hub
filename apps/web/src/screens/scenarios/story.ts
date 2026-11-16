import type { IconName } from "../../components";
import type { ScenarioAction, ScenarioMode, ScenarioPlanRow, ScenarioStep } from "./queries";

/* The words of a scenario's steps: their pace, how often a wait checks, and every place a step
 * can stop. Pure: built from the scenario file and its actions as the detail returns them, and
 * from a plan row once there is one. Never a guess: what it cannot put in words it shows as
 * written. */

const UNIT: Readonly<Record<string, string>> = { s: "s", m: "min", h: "h", ms: "ms" };
const SECONDS: Readonly<Record<string, number>> = { ms: 0.001, s: 1, m: 60, h: 3600 };
const MAX_POLLS = 1000;

/** "10s" → "10 s", "5m" → "5 min" (Content › Formatting); anything else as written. */
export function pace(value: string): string {
  const match = /^(\d+)(ms|s|m|h)$/.exec(value.trim());
  return match ? `${match[1] ?? ""} ${UNIT[match[2] ?? ""] ?? ""}` : value;
}

function seconds(value: string): number | null {
  const match = /^(\d+)(ms|s|m|h)$/.exec(value.trim());
  if (!match) return null;
  return Number(match[1]) * (SECONDS[match[2] ?? ""] ?? 0);
}

/** How many checks an expect makes at most: timeout ÷ every, at most the contract's 1000. */
export function maxChecks(every: string, timeout: string): number | null {
  const step = seconds(every);
  const total = seconds(timeout);
  if (step === null || total === null || step <= 0) return null;
  return Math.min(MAX_POLLS, Math.max(1, Math.floor(total / step)));
}

const OPERATOR: Readonly<Record<string, string>> = {
  "==": "is",
  "!=": "is not",
  ">=": "is at least",
  "<=": "is at most",
  ">": "is above",
  "<": "is below",
};

function term(text: string): string | null {
  const match = /^\$self\.output\.([A-Za-z0-9_.]+)\s*(==|!=|>=|<=|>|<)\s*(.+)$/.exec(text.trim());
  if (!match) return null;
  const literal = (match[3] ?? "").trim();
  if (!/^(-?\d+(\.\d+)?|'[^']*'|"[^"]*"|true|false|null)$/.test(literal)) return null;
  return `${match[1] ?? ""} ${OPERATOR[match[2] ?? ""] ?? ""} ${literal}`;
}

/** `$self.output.status == 200` → "status is 200"; `and` / `or` of such terms are joined in
 * words. Anything else is null: the caller shows the expression as written. */
function conditionInWords(expression: string): string | null {
  for (const joiner of [" and ", " or "]) {
    if (expression.includes(joiner)) {
      const parts = expression.split(joiner).map(term);
      if (parts.some((part) => part === null)) return null;
      return parts.join(joiner);
    }
  }
  return term(expression);
}

/** The condition of an expect, in words when it can be, else as written (`mono`). */
function conditionOf(step: ScenarioStep): { text: string; mono: boolean } {
  const raw = step.until_when ?? "";
  const words = conditionInWords(raw);
  return words === null ? { text: raw, mono: true } : { text: words, mono: false };
}

export interface StopLine {
  key: string;
  icon: IconName;
  text: string;
  /** How the line reads: a decision that stops (`ask`), refuses (`deny`), or plain. */
  tone: "ok" | "ask" | "deny" | "info";
  title?: string;
}

const POLICY_BEFORE: Readonly<Record<string, string>> = {
  read: "It only reads: it runs without asking in every declared environment.",
  write:
    "It changes data: it asks you first where agents ask before changing data, runs without asking where they may change data, and is denied where they only read and in production.",
  destroy:
    "It deletes or replaces data: it asks you first wherever it may run, and is denied where agents only read and in production.",
};

const MODE_TITLE = "After 10 investigations in one scenario run, it fails instead.";

/** Every place a step can stop, before a plan (the policy as rules) or after one (the plan's
 * decision in that environment), and for the mode chosen. */
export function stopLines(
  step: ScenarioStep,
  action: ScenarioAction | null,
  mode: ScenarioMode,
  planned: { row: ScenarioPlanRow | null; environment: string } | null,
): StopLine[] {
  const lines: StopLine[] = [];
  if (step.type === "approval") {
    return [
      { key: "approval", icon: "stamp", tone: "ask", text: "Always stops here for your approval." },
    ];
  }
  if (step.type === "wait") {
    return [
      {
        key: "wait",
        icon: "hourglass",
        tone: "info",
        text: `Pauses here${step.description ? `: ${step.description}` : ""}.`,
      },
    ];
  }
  if (step.type !== "action" && step.type !== "expect") return lines;

  if (action?.problem) {
    lines.push({
      key: "problem",
      icon: "circle-x",
      tone: "deny",
      text: `Its action does not load, so it cannot run: ${action.problem}.`,
    });
  }
  const row = planned?.row ?? null;
  if (row !== null && planned !== null) {
    const env = planned.environment;
    if (row.decision === "allow") {
      lines.push({
        key: "policy",
        icon: "circle-check",
        tone: "ok",
        text:
          row.effect === "read"
            ? `Runs without asking in ${env}: it only reads.`
            : `Runs without asking in ${env}: agents may change data there.`,
      });
    } else if (row.decision === "ask") {
      lines.push({
        key: "policy",
        icon: "hand",
        tone: "ask",
        text: `Asks you in ${env}: the scenario run pauses before this step until you approve it. Reject cancels the scenario run.`,
      });
    } else {
      lines.push({
        key: "policy",
        icon: "octagon-x",
        tone: "deny",
        text: `Denied in ${env}${row.reason ? `: ${row.reason}` : ""}. The scenario run cannot start.`,
      });
    }
  } else if (action?.draft) {
    lines.push({
      key: "policy",
      icon: "circle-x",
      tone: "deny",
      text: "Draft: it cannot run until its action's files are committed.",
    });
  } else if (action?.effect) {
    lines.push({
      key: "policy",
      icon: "info",
      tone: "info",
      text: POLICY_BEFORE[action.effect] ?? `Its effect is ${action.effect}.`,
    });
  }

  const retry =
    step.retry && step.retry.max_attempts > 0
      ? `After ${String(step.retry.max_attempts)} more ${step.retry.max_attempts === 1 ? "try" : "tries"}, `
      : "";
  const then =
    mode === "interactive"
      ? "the scenario run pauses and a read-only agent investigates with you (Interactive)."
      : "the scenario run fails here (Regression).";
  const failure =
    step.type === "expect" && step.timeout
      ? (() => {
          const condition = conditionOf(step);
          const what = condition.mono ? "" : ` (${condition.text})`;
          return `If its condition${what} still does not hold after ${pace(step.timeout)}, `;
        })()
      : `If the script fails, runs past ${pace(step.timeout ?? action?.timeout ?? "5m")} or prints the wrong output, `;
  const text = retry
    ? `${retry}${failure.charAt(0).toLowerCase()}${failure.slice(1)}${then}`
    : `${failure}${then}`;
  lines.push({
    key: "failure",
    icon: mode === "interactive" ? "search" : "circle-x",
    tone: "info",
    text: text.charAt(0).toUpperCase() + text.slice(1),
    ...(mode === "interactive" ? { title: MODE_TITLE } : {}),
  });
  return lines;
}
