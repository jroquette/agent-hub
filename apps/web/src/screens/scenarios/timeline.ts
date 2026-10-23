import type { EventCategory, IconName } from "../../components";
import type { ScenarioRunDetail, ScenarioStep } from "./queries";

/* A scenario run's record as timeline rows and facts, in plain words (spec 23 screen 3). Pure:
 * the record view (`ScenarioRunDetail`) and the scenario's steps in, rows out. */

type Entry = ScenarioRunDetail["timeline"][number];

export interface Row {
  id: string;
  at: string | null;
  cat: EventCategory;
  icon: IconName;
  /** "Scenario run", "Agent", or who answered a gate (the record's approver). */
  actor: string;
  text: string;
  /** The values the step captured, shown after the text (a credential mark as a chip). */
  captures: { name: string; value: unknown }[];
  detail: string[];
}

/** "1 step" / "2 steps". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${String(n)} ${n === 1 ? one : many}`;
}

/** The words for a divergence (the open investigation's `failure_kind`). */
export function divergence(kind: string | null | undefined, type: string | undefined): string {
  if (kind === "timeout") {
    return type === "expect"
      ? "it did not reach its expected state before its timeout"
      : "it did not finish within its timeout";
  }
  if (kind === "output_contract") return "its output does not match the action's output format";
  if (kind === "exec_failed") return "its script exited with an error";
  return kind ? `it failed (${kind})` : "it failed";
}

/** The gates the run's own record names as investigation gates (E-10). */
export function investigationGates(run: ScenarioRunDetail): Set<string> {
  return new Set(run.investigations.map((item) => item.gate));
}

function decisionWords(choice: string | null, text: string | null): string {
  switch (choice) {
    case "approve":
      return "approved";
    case "reject":
      return "rejected";
    case "pick":
      return `picked option ${text ?? ""}`.trim();
    case "retry":
      return "retry";
    case "stop":
      return "stopped";
    default:
      return choice ?? "answered";
  }
}

function whereWords(where: string | null): string {
  if (where === "web") return " in hub web";
  if (where === "terminal") return " in a terminal";
  return where ? ` in ${where}` : "";
}

/** The polls of one expect step's attempt. */
export function pollsOf(run: ScenarioRunDetail, node: string, attempt: number | null) {
  return run.polls.filter((poll) => poll.node === node && poll.attempt === attempt);
}

/** The run's timeline as rows, in record order. */
export function timelineRows(
  run: ScenarioRunDetail,
  steps: readonly ScenarioStep[] | undefined,
): Row[] {
  const typeOf = new Map((steps ?? []).map((step) => [step.id, step]));
  const gates = new Set([
    ...run.timeline.filter((e) => e.event === "gate").map((e) => e.node ?? ""),
    ...investigationGates(run),
  ]);
  const investigations = investigationGates(run);
  const failures = new Map<string, (string | null)[]>();
  for (const item of run.investigations) {
    failures.set(item.step, [...(failures.get(item.step) ?? []), item.failure_kind]);
  }
  const failedSeen = new Map<string, number>();
  const ended = new Set(
    run.timeline
      .filter((e) => e.event === "step_end")
      .map((e) => `${e.node ?? ""}:${String(e.attempt)}`),
  );
  let proposals = 0;
  const lastProposalIndex = run.timeline.map((e) => e.event).lastIndexOf("proposal");
  const rows: Row[] = [];
  run.timeline.forEach((entry: Entry, index) => {
    const id = String(index + 1);
    const base = {
      id,
      at: entry.at,
      detail: [] as string[],
      captures: [] as { name: string; value: unknown }[],
    };
    const node = entry.node ?? "";
    switch (entry.event) {
      case "start":
        rows.push({
          ...base,
          cat: "lifecycle",
          icon: "play",
          actor: "Scenario run",
          text: `Started in ${run.environment ?? "—"} · ${run.mode ?? "—"}`,
        });
        return;
      case "resume":
        rows.push({
          ...base,
          cat: "lifecycle",
          icon: "rotate-ccw",
          actor: "Scenario run",
          text: "Resumed",
        });
        return;
      case "end":
        rows.push({
          ...base,
          cat: "lifecycle",
          icon: "circle-stop",
          actor: "Scenario run",
          text: `Ended ${entry.status ?? ""}`.trim(),
        });
        return;
      case "step_start":
        // A step shows once it ends; one still running shows as running.
        if (gates.has(node) || ended.has(`${node}:${String(entry.attempt)}`)) return;
        rows.push({
          ...base,
          cat: "tool",
          icon: typeOf.get(node)?.type === "expect" ? "timer" : "circle-play",
          actor: "Scenario run",
          text: `${node} · running`,
        });
        return;
      case "step_end": {
        if (gates.has(node)) return;
        const step = typeOf.get(node);
        const parts = [node];
        if ((entry.attempt ?? 1) > 1) parts.push(`attempt ${String(entry.attempt)}`);
        const polls = pollsOf(run, node, entry.attempt);
        if (step?.type === "expect" || polls.length > 0) {
          parts.push(plural(polls.length, "poll"));
          parts.push(polls.some((poll) => poll.held === true) ? "held" : "never held");
        } else if (step?.action) {
          parts.push(`action ${step.action}`);
        }
        if (entry.status === "failed") {
          const seen = failedSeen.get(node) ?? 0;
          failedSeen.set(node, seen + 1);
          const kind = failures.get(node)?.[seen] ?? null;
          parts.push(kind ? `failed: ${kind}` : "failed");
        } else if (step?.type !== "expect" && polls.length === 0) {
          parts.push(entry.status ?? "ended");
        }
        const captured = run.captures
          .filter((capture) => capture.node === node && capture.attempt === entry.attempt)
          .map((capture) => ({ name: capture.name, value: capture.value as unknown }));
        rows.push({
          ...base,
          captures: captured,
          cat: entry.status === "failed" ? "error" : "tool",
          icon: step?.type === "expect" || polls.length > 0 ? "timer" : "circle-play",
          actor: "Scenario run",
          text: parts.join(" · "),
          detail: polls
            .slice(-20)
            .map(
              (poll) =>
                `poll ${String(poll.poll ?? "?")} · ${poll.held === true ? "held" : "not held"}`,
            ),
        });
        return;
      }
      case "gate":
        if (investigations.has(node)) return;
        rows.push({
          ...base,
          cat: "gate",
          icon: "check-check",
          actor: "Scenario run",
          text: `${node} waits for approval`,
        });
        return;
      case "decision": {
        const decision = run.decisions.find((d) => d.node === node && d.attempt === entry.attempt);
        if (decision === undefined) return;
        rows.push({
          ...base,
          cat: "decision",
          icon: "split",
          actor: decision.approver ?? "You",
          text: `${node} · ${decisionWords(decision.choice, decision.text)}${decision.approver ? ` by ${decision.approver}` : ""}${whereWords(decision.where)}`,
        });
        return;
      }
      case "investigation":
        rows.push({
          ...base,
          cat: "gate",
          icon: "scan-eye",
          actor: "Scenario run",
          text: `Investigation ${String(entry.attempt ?? "")} opened at ${node}`,
        });
        return;
      case "agent_action":
        rows.push({
          ...base,
          cat: "tool",
          icon: "scan-eye",
          actor: "Agent",
          text: `Investigation read${entry.action ? `: ${entry.action}` : ""}${entry.effect ? ` (${entry.effect})` : ""}${entry.status ? ` · ${entry.status}` : ""}`,
        });
        return;
      case "proposal": {
        proposals += 1;
        const latest = index === lastProposalIndex && run.proposal !== null;
        const findings = run.findings.length;
        const options = run.proposal?.options.length ?? 0;
        rows.push({
          ...base,
          cat: "message",
          icon: "message-square",
          actor: "Agent",
          text: latest
            ? `Proposal ${String(run.proposal?.proposal ?? proposals)}: ${plural(findings, "finding")}, ${plural(options, "option")}`
            : `Proposal ${String(proposals)}`,
        });
        return;
      }
      case "workaround_start":
      case "workaround_end": {
        const workaround = run.workarounds.find((w) => w.number === entry.attempt);
        const number = String(entry.attempt ?? "");
        let text: string;
        if (entry.event === "workaround_start") {
          text = workaround
            ? `Workaround ${number} started: option ${workaround.option}, ${plural(workaround.steps, "step")}${workaround.approver ? `, picked by ${workaround.approver}` : ""}`
            : `Workaround ${number} started`;
        } else {
          text =
            entry.status === "interrupted"
              ? `Workaround ${number} ended interrupted; it is never run again`
              : `Workaround ${number} ended ${entry.status ?? ""}`.trim();
        }
        rows.push({
          ...base,
          cat: "decision",
          icon: "corner-down-right",
          actor: "Scenario run",
          text,
        });
        return;
      }
      default:
        return;
    }
  });
  return rows;
}

/** The steps that ended ok, once each. */
export function stepsDone(run: ScenarioRunDetail): number {
  const gates = new Set([
    ...run.timeline.filter((e) => e.event === "gate").map((e) => e.node ?? ""),
    ...investigationGates(run),
  ]);
  return new Set(
    run.timeline
      .filter((e) => e.event === "step_end" && e.status === "ok" && !gates.has(e.node ?? ""))
      .map((e) => e.node),
  ).size;
}

/** The paused step's failing attempt: its polls and how long it ran, for the pause banner. */
export function pausedFacts(
  run: ScenarioRunDetail,
  step: string,
): { polls: number; seconds: number | null } {
  const ends = run.timeline.filter((e) => e.event === "step_end" && e.node === step);
  const last = ends[ends.length - 1];
  const attempt = last?.attempt ?? null;
  const begun = run.timeline.find(
    (e) => e.event === "step_start" && e.node === step && e.attempt === attempt,
  );
  const seconds =
    begun?.at && last?.at ? (Date.parse(last.at) - Date.parse(begun.at)) / 1000 : null;
  return { polls: pollsOf(run, step, attempt).length, seconds };
}

/** "10 min" or "40 s". */
export function roughDuration(seconds: number): string {
  if (seconds < 60) return `${String(Math.round(seconds))} s`;
  return `${String(Math.round(seconds / 60))} min`;
}
