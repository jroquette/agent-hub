/* What a skill's text says it does (S6, AC-164.19): its steps, each with who acts in it, a title
 * and a one-line summary, derived from the body and labelled so. */
import "./SkillDetail.css";

import { DerivedLabel, Icon } from "../../components";
import type { IconName } from "../../components";
import type { components } from "../../api/schema";
import { stepAnchor } from "../../lib/brainLinks";
import { AnchorLink } from "./BodyView";

type Schemas = components["schemas"];
type SkillStructure = Schemas["SkillStructure"];
type Step = Schemas["Step"];
type StepTag = Step["tags"][number];
type StepType = Schemas["StepType"];

/** A declared step type, in the words and icons the Workflows graph uses for the same steps. */
const TYPE: Record<StepType, { icon: IconName; label: string }> = {
  agent: { icon: "message-square", label: "Agent works" },
  script: { icon: "file-text", label: "Runs commands" },
  gate: { icon: "stamp", label: "You approve" },
  human: { icon: "hand", label: "You act" },
};
/** A tag guessed from the step's words, shown only when the step declares no type. */
const TAG: Record<StepTag, { icon: IconName; label: string }> = {
  gate: { icon: "stamp", label: "Gate" },
  agent: { icon: "network", label: "Agent" },
  command: { icon: "terminal", label: "Command" },
  script: { icon: "scroll-text", label: "Script" },
  human: { icon: "hand", label: "Needs you" },
};
const HOW =
  "Read from the body's top-level numbered list. A step's type is the one its text declares (agent, script, gate, human), else guessed from its words: check it against the text.";

/** "step 3", "steps 3 and 5", "steps 2, 4 and 6". */
function stepList(indexes: readonly number[]): string {
  const names = indexes.map(String);
  if (names.length === 1) return `step ${names[0] ?? ""}`;
  return `steps ${names.slice(0, -1).join(", ")} and ${names.at(-1) ?? ""}`;
}

/** "6 steps · you approve step 3 · you act in step 5". */
export function stepsHeadline(steps: readonly Step[]): string {
  const of = (type: StepType) =>
    steps.filter((step) => step.declared_type === type).map((step) => step.index);
  const parts = [`${String(steps.length)} ${steps.length === 1 ? "step" : "steps"}`];
  const gates = of("gate");
  if (gates.length > 0) parts.push(`you approve ${stepList(gates)}`);
  const acts = of("human");
  if (acts.length > 0) parts.push(`you act in ${stepList(acts)}`);
  return parts.join(" · ");
}

function StepKind({ step }: { step: Step }) {
  if (step.declared_type) {
    const look = TYPE[step.declared_type];
    return (
      <span className="ah-skill-step-type" data-type={step.declared_type}>
        <Icon name={look.icon} size="sm" />
        {look.label}
      </span>
    );
  }
  return (
    <>
      {step.tags.map((tag) => (
        <span key={tag} className="ah-skill-tag">
          <Icon name={TAG[tag].icon} size="sm" />
          {TAG[tag].label}
        </span>
      ))}
    </>
  );
}

export interface StructurePanelProps {
  structure: SkillStructure | null;
  /** Called with `step-<n>` when a step is chosen; by default the page scrolls to it. */
  onStep?: ((anchor: string) => void) | undefined;
}

/** The Steps panel, headed "Derived from the text"; nothing when the body has no numbered steps. */
export function StructurePanel({ structure, onStep }: StructurePanelProps) {
  if (structure === null || structure.steps.length === 0) return null;
  const dynamic = structure.dynamic_context;
  return (
    <section className="ah-card ah-skill-section" aria-labelledby="skill-structure">
      <div className="ah-card-head">
        <h2 id="skill-structure" className="ah-h3">
          Steps
        </h2>
        <span className="ah-small ah-muted">{stepsHeadline(structure.steps)}</span>
        <span className="ah-grow" />
        <DerivedLabel how={HOW}>Derived from the text</DerivedLabel>
      </div>
      <div className="ah-card-body ah-stack" style={{ gap: 12 }}>
        <ol className="ah-skill-steps" aria-label="Steps">
          {structure.steps.map((step) => {
            const names = [
              ...step.agents,
              ...step.skills.map((name) => `/${name}`),
              ...step.commands,
              ...step.scripts,
            ];
            return (
              <li key={step.index} data-type={step.declared_type ?? undefined}>
                <span className="ah-skill-step-num" aria-hidden="true">
                  {step.index}
                </span>
                <div className="ah-skill-step-main">
                  <div className="ah-skill-step-head">
                    <AnchorLink
                      anchor={stepAnchor(step.index)}
                      onGo={onStep}
                      className="ah-skill-step-title"
                      label={`${String(step.index)}. ${step.title}`}
                    >
                      {step.title}
                    </AnchorLink>
                    <StepKind step={step} />
                  </div>
                  {step.summary && (
                    <p className="ah-skill-step-summary" title={step.summary}>
                      {step.summary}
                    </p>
                  )}
                  {names.length > 0 && (
                    <div className="ah-skill-step-meta">
                      {names.map((name) => (
                        <code key={name}>{name}</code>
                      ))}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        {structure.truncated && (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            Only the first 200 steps are listed.
          </p>
        )}
        {dynamic > 0 && (
          <p className="ah-small" style={{ margin: 0 }}>
            <Icon name="square-terminal" size="sm" /> {dynamic} dynamic context{" "}
            {dynamic === 1 ? "block" : "blocks"}: runs at invocation, shown here as text and never
            run.
          </p>
        )}
      </div>
    </section>
  );
}
