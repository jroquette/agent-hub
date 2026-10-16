/* What an item costs in context (D5, P8, AC-164.24): approximate tokens, always and on invoke. */
import "./SkillDetail.css";

import { DerivedLabel } from "../../components";
import type { components } from "../../api/schema";
import type { ItemKind } from "./filters";

type Cost = components["schemas"]["ContextCost"];

const tokens = (n: number) => `≈ ${n.toLocaleString("en-US")} tokens`;
const HOW = "Characters divided by 4: a rough estimate, not the model's tokenizer.";

function Stat({ label, value, source }: { label: string; value: number; source: string }) {
  return (
    <div className="ah-skill-cost">
      <dt>{label}</dt>
      <dd>
        <span className="ah-skill-cost-value">{tokens(value)}</span>
        <span className="ah-small ah-muted ah-skill-cost-source">{source}</span>
      </dd>
    </div>
  );
}

/** The two context figures `/plugin` shows, as a section of the About rail; nothing for a hook. */
export function ContextCost({ cost, kind }: { cost: Cost | null; kind: ItemKind }) {
  if (cost === null) return null;
  const always =
    cost.always_loaded_tokens === 0
      ? "from the description; none while only you can invoke it"
      : "from the description, in every session";
  return (
    <section className="ah-skill-rail-section" aria-labelledby="skill-cost">
      <div className="ah-skill-rail-head">
        <h3 id="skill-cost" className="ah-caption">
          Context cost
        </h3>
        <DerivedLabel how={HOW}>Approximate</DerivedLabel>
      </div>
      <dl className="ah-skill-costs">
        <Stat label="Always loaded" value={cost.always_loaded_tokens} source={always} />
        <Stat
          label="On invoke"
          value={cost.on_invoke_tokens}
          source={kind === "agent" ? "from the system prompt" : "from the body"}
        />
      </dl>
    </section>
  );
}
