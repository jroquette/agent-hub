import type { IconName } from "../../components";
import type {
  ScenarioAction,
  ScenarioDetail,
  ScenarioMode,
  ScenarioPlanRow,
  ScenarioStep,
} from "./queries";

/* The words of a scenario's storyline (the scenario detail's step cards): what each step does,
 * the values it passes, what it keeps and every place it can stop. Pure: built from the scenario
 * file and its actions as the detail returns them, and from a plan row once there is one. Never a
 * guess: what it cannot put in words it shows as written. */

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
export function conditionInWords(expression: string): string | null {
  for (const joiner of [" and ", " or "]) {
    if (expression.includes(joiner)) {
      const parts = expression.split(joiner).map(term);
      if (parts.some((part) => part === null)) return null;
      return parts.join(joiner);
    }
  }
  return term(expression);
}

/** The step kind as the cards name it. */
export const KIND_LOOK: Readonly<Record<string, { label: string; icon: IconName }>> = {
  expect: { label: "Expect", icon: "timer" },
  action: { label: "Action", icon: "circle-play" },
  approval: { label: "Approval by you", icon: "stamp" },
  wait: { label: "Wait", icon: "hourglass" },
  loop_group: { label: "Repeats", icon: "refresh-cw" },
  include: { label: "Includes", icon: "layers" },
};

export function kindLook(type: string): { label: string; icon: IconName } {
  return KIND_LOOK[type] ?? { label: type, icon: "circle-dashed" };
}

/** The action a step calls, among the detail's actions (by the ref the step writes). */
export function actionOf(
  step: ScenarioStep,
  actions: readonly ScenarioAction[],
): ScenarioAction | null {
  if (step.action === null) return null;
  return actions.find((action) => action.ref === step.action) ?? null;
}

/** The condition of an expect, in words when it can be, else as written (`mono`). */
export function conditionOf(step: ScenarioStep): { text: string; mono: boolean } {
  const raw = step.until_when ?? "";
  const words = conditionInWords(raw);
  return words === null ? { text: raw, mono: true } : { text: words, mono: false };
}

/** What a step does, in one sentence. */
export function whatItDoes(step: ScenarioStep, action: ScenarioAction | null): string {
  if (step.type === "expect" && step.every && step.timeout) {
    const checks = maxChecks(step.every, step.timeout);
    const condition = conditionOf(step);
    const until = condition.mono ? "its condition holds" : condition.text;
    return `Waits until ${until}: checks every ${pace(step.every)}, for up to ${pace(step.timeout)}${
      checks === null ? "" : ` (at most ${String(checks)} checks)`
    }.`;
  }
  if (step.type === "expect") {
    return `Runs ${step.action ?? "its action"} again and again until its condition holds.`;
  }
  if (step.type === "action") {
    const what = action?.description ?? `Runs ${step.action ?? "its action"}`;
    return `${what.replace(/\.$/, "")}, once.`;
  }
  if (step.type === "approval") {
    return "Stops here until you approve it. Reject cancels the scenario run.";
  }
  if (step.type === "wait") return step.description ?? "Waits.";
  return step.description ?? kindLook(step.type).label;
}

export interface ValueLine {
  name: string;
  /** What the step passes, in words: "input service", "kept by fetch as order_id", a literal. */
  value: string;
  /** The value is a literal (shown in mono). */
  literal: boolean;
  /** A tooltip: where a run-time value comes from. */
  title?: string;
  /** "action's default" when the step passes nothing and the action has a default. */
  note: string | null;
  required: boolean;
}

function words(value: unknown): { value: string; literal: boolean; title?: string } {
  if (typeof value === "string") {
    const runtime = /^<\$CTX\.([a-z0-9_]+) from ([^>]+)>$/i.exec(value);
    if (runtime) {
      return {
        value,
        literal: true,
        title: `Known at run time: captured by step ${runtime[2] ?? ""}`,
      };
    }
    const input = /^\$INPUTS\.([A-Za-z0-9_]+)$/.exec(value);
    if (input) return { value: `input ${input[1] ?? ""}`, literal: false };
    const kept = /^\$CTX\.([A-Za-z0-9_]+)$/.exec(value);
    if (kept) return { value: `kept earlier as ${kept[1] ?? ""}`, literal: false };
    return { value, literal: true };
  }
  return { value: JSON.stringify(value), literal: true };
}

/** One line per action input, in the action's order, then any value the action does not
 * declare; an input the step leaves out shows the action's default. */
export function valueLines(
  step: ScenarioStep,
  action: ScenarioAction | null,
  args?: Readonly<Record<string, string>> | null,
): ValueLine[] {
  // A plan's args are the step's values resolved in it (inputs filled, run-time ones marked).
  const given: Readonly<Record<string, unknown>> = args ?? step.with ?? {};
  const lines: ValueLine[] = [];
  const declared = new Set<string>();
  for (const input of action?.inputs ?? []) {
    declared.add(input.name);
    if (input.name in given) {
      lines.push({
        name: input.name,
        ...words(given[input.name]),
        note: null,
        required: input.required,
      });
    } else if (input.default !== null && input.default !== undefined) {
      lines.push({
        name: input.name,
        ...words(input.default),
        literal: true,
        note: "action's default",
        required: false,
      });
    }
  }
  for (const [name, value] of Object.entries(given)) {
    if (!declared.has(name)) lines.push({ name, ...words(value), note: null, required: false });
  }
  return lines;
}

/** "status (integer), body (string)": the top level of the action's output format. */
export function givesLine(action: ScenarioAction | null): string | null {
  const properties: unknown = action?.output_format?.properties;
  if (typeof properties !== "object" || properties === null) return null;
  const parts = Object.entries(properties as Record<string, unknown>).map(([name, schema]) => {
    const type =
      typeof schema === "object" && schema !== null
        ? (schema as { type?: unknown }).type
        : undefined;
    return typeof type === "string" ? `${name} (${type})` : name;
  });
  return parts.length === 0 ? null : parts.join(", ");
}

/** Each `capture` and the later steps that read it. */
export function keptLines(
  step: ScenarioStep,
  steps: readonly ScenarioStep[],
): { name: string; from: string; usedBy: string[] }[] {
  return Object.entries(step.capture ?? {}).map(([name, ref]) => ({
    name,
    from: ref.replace(/^\$self\./, ""),
    usedBy: steps
      .filter((other) =>
        Object.values(other.with ?? {}).some(
          (value) => typeof value === "string" && value.includes(`$CTX.${name}`),
        ),
      )
      .map((other) => other.id),
  }));
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

/** "2 steps · reads only · 1 input". */
export function shapeLine(scenario: ScenarioDetail): string {
  const steps = scenario.steps.length;
  const parts = [`${String(steps)} ${steps === 1 ? "step" : "steps"}`];
  const effectOf = (step: ScenarioStep) => actionOf(step, scenario.actions)?.effect ?? null;
  const writes = scenario.steps.filter((step) => effectOf(step) === "write").length;
  const destroys = scenario.steps.filter((step) => effectOf(step) === "destroy").length;
  if (writes === 0 && destroys === 0 && scenario.steps.some((step) => effectOf(step) === "read")) {
    parts.push("reads only");
  }
  if (writes > 0) parts.push(`writes in ${String(writes)} ${writes === 1 ? "step" : "steps"}`);
  if (destroys > 0) {
    parts.push(`destroys in ${String(destroys)} ${destroys === 1 ? "step" : "steps"}`);
  }
  const approvals = scenario.steps.filter((step) => step.type === "approval").length;
  if (approvals > 0)
    parts.push(`${String(approvals)} ${approvals === 1 ? "approval" : "approvals"}`);
  const inputs = scenario.inputs.length;
  if (inputs > 0) parts.push(`${String(inputs)} ${inputs === 1 ? "input" : "inputs"}`);
  return parts.join(" · ");
}
