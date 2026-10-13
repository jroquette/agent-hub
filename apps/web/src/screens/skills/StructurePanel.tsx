/* What a skill's text says it does (S6, AC-164.19): steps, agents, skills, commands and gates,
 * derived heuristically from the body and labelled so. */
import "./SkillDetail.css";

import { DerivedLabel, Icon } from "../../components";
import type { IconName } from "../../components";
import type { components } from "../../api/schema";
import { stepAnchor } from "../../lib/brainLinks";
import { AnchorLink } from "./BodyView";

type Schemas = components["schemas"];
type SkillStructure = Schemas["SkillStructure"];
type StepTag = Schemas["Step"]["tags"][number];

const TAG: Record<StepTag, { icon: IconName; label: string }> = {
  gate: { icon: "octagon-alert", label: "Gate" },
  agent: { icon: "network", label: "Agent" },
  command: { icon: "terminal", label: "Command" },
  script: { icon: "scroll-text", label: "Script" },
  human: { icon: "hand", label: "Needs you" },
};
const HOW =
  "Read heuristically from the body's top-level numbered list and backticked names: check it against the rendered or raw text.";

function Names({
  label,
  names,
  prefix = "",
}: {
  label: string;
  names: readonly string[];
  prefix?: string;
}) {
  if (names.length === 0) return null;
  return (
    <div className="ah-skill-fact">
      <dt>{label}</dt>
      <dd>
        {names.map((name, i) => (
          <span key={name}>
            {i > 0 && ", "}
            <code>
              {prefix}
              {name}
            </code>
          </span>
        ))}
      </dd>
    </div>
  );
}

export interface StructurePanelProps {
  structure: SkillStructure | null;
  /** Called with `step-<n>` when a step is chosen; by default the page scrolls to it. */
  onStep?: ((anchor: string) => void) | undefined;
}

/** The Structure panel, headed "Derived from the text"; nothing for a hook. */
export function StructurePanel({ structure, onStep }: StructurePanelProps) {
  if (structure === null) return null;
  const dynamic = structure.dynamic_context;
  return (
    <section className="ah-card ah-skill-section" aria-labelledby="skill-structure">
      <div className="ah-card-head">
        <h2 id="skill-structure" className="ah-h3">
          Structure
        </h2>
        <DerivedLabel how={HOW}>Derived from the text</DerivedLabel>
      </div>
      <div className="ah-card-body ah-stack" style={{ gap: 12 }}>
        {structure.steps.length === 0 ? (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            No numbered steps found
          </p>
        ) : (
          <ol className="ah-skill-steps" aria-label="Steps">
            {structure.steps.map((step) => (
              <li key={step.index}>
                <AnchorLink
                  anchor={stepAnchor(step.index)}
                  onGo={onStep}
                  className="ah-skill-step-title"
                >
                  {step.index}. {step.title}
                </AnchorLink>
                {(step.tags.length > 0 ||
                  step.agents.length > 0 ||
                  step.skills.length > 0 ||
                  step.commands.length > 0 ||
                  step.scripts.length > 0) && (
                  <div className="ah-skill-step-meta">
                    {step.tags.map((tag) => (
                      <span key={tag} className="ah-skill-tag">
                        <Icon name={TAG[tag].icon} size="sm" />
                        {TAG[tag].label}
                      </span>
                    ))}
                    {[
                      ...step.agents,
                      ...step.skills.map((name) => `/${name}`),
                      ...step.commands,
                      ...step.scripts,
                    ].map((name) => (
                      <code key={name}>{name}</code>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
        {structure.truncated && (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            Only the first 200 steps are listed.
          </p>
        )}
        <dl className="ah-skill-facts">
          <Names label="Agents named" names={structure.agents} />
          <Names label="Skills referenced" names={structure.skills} prefix="/" />
          <Names label="Commands" names={structure.commands} />
          <Names label="Gates" names={structure.gates} />
        </dl>
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
