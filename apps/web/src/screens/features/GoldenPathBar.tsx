import type { CSSProperties } from "react";

import type { components } from "../../api/schema";
import {
  GOLDEN_STEP_LABEL,
  StatusBadge,
  Tooltip,
  goldenStepSummary,
  ownerWaitStep,
  shownGoldenSteps,
} from "../../components";

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
  unrecorded: { background: "transparent", border: DASHED },
};

/** The step order, as the column hint gives it, so the segments can be read left to right. */
export const GOLDEN_PATH_ORDER = Object.values(GOLDEN_STEP_LABEL).join(" → ");

/** Whether the feature is held at Acceptance by owner steps only: the owner is the one to act. */
export function waitsOnOwner(path: GoldenPath): boolean {
  return ownerWaitStep(path.steps) !== null;
}

/**
 * The compact golden path of the Features list (AC-136.32): one segment per step drawn from the
 * server's states, the phase with its meta, and every step's state, meta and reason in the
 * tooltip and the accessible name.
 */
export function GoldenPathBar({ path, compact = false }: { path: GoldenPath; compact?: boolean }) {
  const steps = shownGoldenSteps(path.steps);
  const label = GOLDEN_STEP_LABEL[path.phase];
  const waiting = waitsOnOwner(path);
  const meta = waiting ? null : (steps.find((s) => s.name === path.phase)?.meta ?? null);
  const position = steps.findIndex((s) => s.name === path.phase) + 1;
  const summaries = steps.map(goldenStepSummary);
  const segments = steps.map((step) => (
    <span
      key={step.name}
      data-state={step.state}
      style={{
        width: compact ? 12 : 14,
        height: 8,
        borderRadius: 2,
        border: "1px solid transparent",
        ...SEGMENT[step.state],
      }}
    />
  ));
  if (compact) {
    // The row's line names the step and its own description reads every step: no tab stop here.
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
            aria-label={`Golden path: ${label}. ${summaries.join("; ")}`}
          >
            {segments}
          </span>
          <span className="ft-gp-label" aria-hidden="true">
            {label}
            {path.phase !== "shipped" && position > 0 && (
              <span className="ah-subtle">
                {" "}
                · {position}/{steps.length}
              </span>
            )}
          </span>
        </span>
      </Tooltip>
    );
  }
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
        {/* Focusable so keyboard users open the same step-by-step tooltip as the mouse. */}
        <span
          style={{ display: "flex", gap: 2, width: "fit-content", borderRadius: 2 }}
          role="img"
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
          aria-label={`Golden path: ${label}. ${summaries.join("; ")}`}
        >
          {segments}
        </span>
        <span className="ah-small ah-row" style={{ gap: 6 }}>
          <span>
            <b style={{ fontWeight: 500 }}>{label}</b>
            {path.phase !== "shipped" && position > 0 && (
              <span className="ah-subtle">
                {" "}
                · step {position} of {steps.length}
              </span>
            )}
            {meta && path.phase !== "shipped" && (
              <>
                {" · "}
                <span className="ah-muted">{meta}</span>
              </>
            )}
          </span>
          {waiting && <StatusBadge status="waiting" quiet />}
        </span>
      </span>
    </Tooltip>
  );
}
