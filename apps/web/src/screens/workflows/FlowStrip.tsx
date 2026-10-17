import { Icon } from "../../components";
import type { components } from "../../api/schema";
import { STEP_KINDS, stepKind } from "./steps";

/* A workflow's steps as one line read left to right: a chip per step, coloured by kind, and a
 * repeat's body boxed with its round cap. */

export type WorkflowStep = components["schemas"]["WorkflowStepView"];

function Arrow() {
  return (
    <span className="wf-arrow" aria-hidden>
      <Icon name="arrow-right" size="sm" />
    </span>
  );
}

function StepChip({ step }: { step: WorkflowStep }) {
  const kind = stepKind(step.type);
  const info = STEP_KINDS[kind];
  return (
    <span
      className={`wf-step wf-step-${kind}`}
      title={`${info.one}${step.description ? `: ${step.description}` : ""}`}
    >
      <Icon name={info.icon} size="sm" />
      {step.id}
    </span>
  );
}

function Steps({ steps }: { steps: readonly WorkflowStep[] }) {
  return (
    <>
      {steps.map((step, index) => (
        <span key={step.id} className="wf-link">
          {index > 0 && <Arrow />}
          {step.type === "loop_group" ? (
            <span
              className="wf-rounds"
              title={step.description ?? "Repeats these steps until they pass"}
            >
              <span className="wf-rounds-label">
                <Icon name="refresh-cw" size="sm" />
                {step.max_iterations ? `up to ${String(step.max_iterations)} rounds` : "rounds"}
              </span>
              <Steps steps={step.body} />
            </span>
          ) : (
            <StepChip step={step} />
          )}
        </span>
      ))}
    </>
  );
}

/** The steps in order; `label` names the strip for assistive tech. */
export function FlowStrip({ steps, label }: { steps: readonly WorkflowStep[]; label: string }) {
  return (
    <div className="wf-flow" role="img" aria-label={label}>
      <Steps steps={steps} />
    </div>
  );
}

/** "worktree, then 3 rounds of implement, check…, then pr": the strip in words. */
export function flowInWords(steps: readonly WorkflowStep[]): string {
  return steps
    .map((step) =>
      step.type === "loop_group"
        ? `up to ${String(step.max_iterations ?? "")} rounds of ${flowInWords(step.body)}`
        : step.id,
    )
    .join(", then ");
}
