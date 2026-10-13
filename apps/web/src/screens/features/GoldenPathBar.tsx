import type { CSSProperties } from "react";

import type { components } from "../../api/schema";
import { GOLDEN_STEP_LABEL, Tooltip, goldenStepSummary, shownGoldenSteps } from "../../components";

type GoldenPath = components["schemas"]["GoldenPath"];
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
};

/**
 * The compact golden path of the Features list (AC-136.32): one segment per step drawn from the
 * server's states, the phase with its meta, and every step's state, meta and reason in the
 * tooltip and the accessible name.
 */
export function GoldenPathBar({ path }: { path: GoldenPath }) {
  const steps = shownGoldenSteps(path.steps);
  const label = GOLDEN_STEP_LABEL[path.phase];
  const meta = steps.find((s) => s.name === path.phase)?.meta ?? null;
  const summaries = steps.map(goldenStepSummary);
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
          style={{ display: "flex", gap: 2 }}
          role="img"
          aria-label={`Golden path: ${label}. ${summaries.join("; ")}`}
        >
          {steps.map((step) => (
            <span
              key={step.name}
              data-state={step.state}
              style={{
                width: 14,
                height: 8,
                borderRadius: 2,
                border: "1px solid transparent",
                ...SEGMENT[step.state],
              }}
            />
          ))}
        </span>
        <span className="ah-small">
          <b style={{ fontWeight: 500 }}>{label}</b>
          {meta && path.phase !== "shipped" && (
            <>
              {" · "}
              <span className="ah-muted">{meta}</span>
            </>
          )}
        </span>
      </span>
    </Tooltip>
  );
}
