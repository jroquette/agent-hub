import type { CSSProperties } from "react";

import type { components } from "../api/schema";
import { Tooltip } from "./core";

type StepState = components["schemas"]["StepState"];

const DASHED = "1px dashed var(--border-control)";

const SEGMENT: Record<StepState, CSSProperties> = {
  done: { background: "var(--done)" },
  partial: {
    background: "linear-gradient(90deg, var(--done) 50%, var(--surface-sunken) 50%)",
    border: "1px solid var(--done)",
  },
  current: { background: "var(--live)" },
  pending: { background: "var(--surface-sunken)" },
  blocked: {
    background: "var(--blocked-soft)",
    border: "1px solid var(--blocked)",
  },
  skipped: { background: "transparent", border: DASHED },
  unknown: { background: "transparent", border: DASHED },
  unrecorded: { background: "transparent", border: DASHED },
};

/**
 * A list of steps as one bar: a segment per step in its state, the current step's label with its
 * position ("Build · 6/8"; the last step reads alone), and every step's summary in the tooltip and
 * the accessible name. Not a tab stop: the row that holds it names it.
 */
export function StepBar({
  name,
  label,
  current,
  steps,
}: {
  /** What the steps are ("Golden path"), at the head of the accessible name. */
  name: string;
  label: string;
  /** The index of the current step in `steps`. */
  current: number;
  steps: readonly { state: StepState; summary: string }[];
}) {
  const summaries = steps.map((step) => step.summary);
  return (
    <Tooltip
      label={
        <span className="ah-stack" style={{ gap: 2 }}>
          {summaries.map((line) => (
            <span key={line}>{line}</span>
          ))}
        </span>
      }
    >
      <span className="ah-stack" style={{ gap: 3 }}>
        <span
          style={{ display: "flex", gap: 2, width: "fit-content" }}
          role="img"
          aria-label={`${name}: ${label}. ${summaries.join("; ")}`}
        >
          {steps.map((step) => (
            <span
              key={step.summary}
              data-state={step.state}
              style={{
                width: 12,
                height: 8,
                borderRadius: 2,
                border: "1px solid transparent",
                ...SEGMENT[step.state],
              }}
            />
          ))}
        </span>
        <span className="ah-step-label" aria-hidden="true">
          {label}
          {current < steps.length - 1 && (
            <span className="ah-subtle">
              {" "}
              · {current + 1}/{steps.length}
            </span>
          )}
        </span>
      </span>
    </Tooltip>
  );
}
