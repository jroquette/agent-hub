import { Fragment } from "react";

import type { components } from "../../api/schema";
import { RedactionChip, StatusBadge, type Status } from "../../components";
import { renderParts, rowActorOf } from "./timeline";

export type SessionProblems = components["schemas"]["SessionProblems"];
export type Problem = components["schemas"]["Problem"];
type ProblemKind = components["schemas"]["ProblemKind"];

/** What went wrong, in the owner's words (S4, E4). */
export const KIND_LABEL: Readonly<Record<ProblemKind, string>> = {
  tool_failed: "Tool failed",
  command_exit: "Command failed",
  guard_denied: "Guard blocked",
  guard_ask_open: "Guard ask unanswered",
  guard_ask_declined: "Guard ask declined",
  interrupted: "Interrupted",
  gate_failed: "Gate failed",
  hook_failed: "Hook failed",
};

/** Text with each `[redacted: kind]` marker as a chip (TraceRow's Redacted, without the cycle). */
function Redacted({ text }: { text: string }) {
  return (
    <>
      {renderParts(text).map((part, i) =>
        "redacted" in part ? (
          <RedactionChip key={i} kind={part.redacted} />
        ) : (
          <Fragment key={i}>{part.text}</Fragment>
        ),
      )}
    </>
  );
}

interface Look {
  status: Status;
  label: string;
  title: string;
}

/** Whether the owner must act, as a badge: icon and label, never colour alone (E5). */
export function problemLook(problem: Pick<Problem, "kind" | "resolution">): Look {
  switch (problem.resolution) {
    case "needs_you":
      return { status: "failed", label: "Needs you", title: "Nothing fixed it: you need to act" };
    case "open":
      return {
        status: "running",
        label: "Agent is on it",
        title: "The agent is still working right after this problem",
      };
    case "recovered":
      return {
        status: "passed",
        label: "Handled by the agent",
        title: "The agent ran it again and it worked",
      };
    case "agent_continued":
      return {
        status: "passed",
        label: "Handled by the agent",
        title: "The agent carried on with other work",
      };
    case "by_you":
      if (problem.kind === "interrupted") {
        return { status: "stopped", label: "You interrupted", title: "You stopped the agent" };
      }
      if (problem.kind === "guard_ask_declined") {
        return { status: "stopped", label: "You declined", title: "You declined the guard's ask" };
      }
      return { status: "stopped", label: "Handled by you", title: "You answered it" };
  }
}

export function ProblemBadge({ problem }: { problem: Pick<Problem, "kind" | "resolution"> }) {
  const look = problemLook(problem);
  return <StatusBadge status={look.status} label={look.label} title={look.title} />;
}

/** "1 needs you · 2 handled by the agent". */
export function problemCounts(items: readonly Pick<Problem, "resolution">[]): string {
  const count = (resolutions: string[]) =>
    items.filter((item) => resolutions.includes(item.resolution)).length;
  return [
    [count(["needs_you"]), "needs you"],
    [count(["open"]), "agent is on it"],
    [count(["recovered", "agent_continued"]), "handled by the agent"],
    [count(["by_you"]), "by you"],
  ]
    .filter(([n]) => Number(n) > 0)
    .map(([n, text]) => `${String(n)} ${String(text)}`)
    .join(" · ");
}

export interface ProblemsPanelProps {
  problems: SessionProblems;
  /** The clock time of an ISO timestamp, in the reader's time zone. */
  timeOf: (at: string) => string;
  /** Opens the timeline at the event. */
  onOpen: (eventId: string) => void;
}

function MomentLink({
  eventId,
  label,
  onOpen,
}: {
  eventId: string;
  label?: string | undefined;
  onOpen: (eventId: string) => void;
}) {
  return (
    <a
      href={`?event=${encodeURIComponent(eventId)}`}
      className="ah-small"
      aria-label={label}
      onClick={(event) => {
        event.preventDefault();
        onOpen(eventId);
      }}
    >
      Open moment
    </a>
  );
}

/** "What went wrong": the summary lines, then each problem with who must act (AC-201.15). */
export function ProblemsPanel({ problems, timeOf, onOpen }: ProblemsPanelProps) {
  if (problems.items.length === 0) return null;
  return (
    <section className="sd-problems" aria-labelledby="sd-problems-title">
      <div className="ah-row ah-wrap" style={{ gap: 10, marginBottom: 6 }}>
        <h2 id="sd-problems-title" className="sd-problems-title">
          What went wrong
        </h2>
        <span className="ah-small ah-muted">{problemCounts(problems.items)}</span>
      </div>
      {problems.summary.length > 0 && (
        <ol className="sd-problems-summary" aria-label="Summary">
          {problems.summary.map((line) => (
            <li key={`${line.event_id}-${line.text}`} className="ah-small">
              <Redacted text={line.text} /> <MomentLink eventId={line.event_id} onOpen={onOpen} />
            </li>
          ))}
        </ol>
      )}
      <ul className="sd-problems-list" aria-label="Problems">
        {problems.items.map((problem) => {
          const kind = KIND_LABEL[problem.kind];
          const time = timeOf(problem.at);
          return (
            <li key={problem.event_id} className="sd-problem">
              <div className="ah-row ah-wrap" style={{ gap: 8 }}>
                <ProblemBadge problem={problem} />
                <b className="ah-small">{kind}</b>
                {problem.tool && <span className="ah-tool">{problem.tool}</span>}
                {problem.where && (
                  <code className="ah-mono ah-small sd-problem-where">
                    <Redacted text={problem.where} />
                  </code>
                )}
                <span className="ah-grow" />
                <span className="ah-small ah-muted">{rowActorOf(problem.actor).label}</span>
                <time className="ah-mono ah-small ah-subtle" dateTime={problem.at}>
                  {time}
                </time>
                <MomentLink
                  eventId={problem.event_id}
                  label={`Open moment: ${kind} at ${time}`}
                  onOpen={onOpen}
                />
              </div>
              {problem.message && (
                <div className="ah-small sd-problem-message">
                  <Redacted text={problem.message} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
