/* One labelled fact of an item's About rail: a term over its value. */
import "./SkillDetail.css";

import type { ReactNode } from "react";

export function RailFact({
  term,
  children,
  mono,
}: {
  term: string;
  children: ReactNode;
  mono?: boolean | undefined;
}) {
  return (
    <div className="ah-skill-fact">
      <dt>{term}</dt>
      <dd className={mono ? "ah-mono" : undefined}>{children}</dd>
    </div>
  );
}
