/* Uses / Used by (D4, AC-164.20): the skills and agents an item names, and the items naming it. */
import "./SkillDetail.css";

import { AppLink, Icon } from "../../components";
import type { components } from "../../api/schema";
import { skillRoute } from "./queries";
import { KIND_ICON, KIND_NAME } from "./SkillCard";

type Relation = components["schemas"]["Relation"];

const MANAGED_SOURCE = "hub-workflow";

function RelationList({
  label,
  project,
  relations,
  empty,
}: {
  label: string;
  project: string;
  relations: readonly Relation[];
  empty: string;
}) {
  return (
    <div className="ah-skill-relations-col">
      <h3 className="ah-caption ah-muted" style={{ margin: "0 0 6px" }}>
        {label}
      </h3>
      {relations.length === 0 ? (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          {empty}
        </p>
      ) : (
        <ul className="ah-skill-relations" aria-label={label}>
          {relations.map((relation) => (
            <li key={relation.id}>
              <span className="ah-skill-kind">
                <Icon name={KIND_ICON[relation.kind]} size="sm" />
                {KIND_NAME[relation.kind]}
              </span>
              <AppLink className="ah-mono" href={skillRoute(project, relation)}>
                {relation.name}
              </AppLink>
              {relation.source !== MANAGED_SOURCE && (
                <span className="ah-small ah-muted">from {relation.source}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export interface RelationsProps {
  project: string;
  uses: readonly Relation[];
  usedBy: readonly Relation[];
}

/** The relations card; each entry is an in-app link to that item's detail. */
export function Relations({ project, uses, usedBy }: RelationsProps) {
  return (
    <section className="ah-card ah-skill-section" aria-labelledby="skill-relations">
      <div className="ah-card-head">
        <h2 id="skill-relations" className="ah-h3">
          Relations
        </h2>
      </div>
      <div className="ah-card-body ah-skill-relations-grid">
        <RelationList
          label="Uses"
          project={project}
          relations={uses}
          empty="Names no skill or agent of this hub."
        />
        <RelationList
          label="Used by"
          project={project}
          relations={usedBy}
          empty="No other item names it."
        />
      </div>
    </section>
  );
}
