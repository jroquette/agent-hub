import { useParams } from "react-router";

import { PhaseTag } from "../../components";
import { NotFoundBody } from "../not-found";

const TITLES: Readonly<Record<string, string>> = {
  brain: "Brain",
  decisions: "Decisions",
  context: "Context",
};

/** The Knowledge items that arrive in Phase 3: the title, "Arrives in Phase 3." and nothing else (D20). */
export function KnowledgePhase3Screen() {
  const { section = "" } = useParams();
  const title = TITLES[section];
  if (title === undefined) return <NotFoundBody />;
  return (
    <div className="ah-page">
      <div className="ah-row" style={{ gap: 12 }}>
        <h1 className="ah-h1">{title}</h1>
        <PhaseTag phase="P3" />
      </div>
      <p className="ah-muted" style={{ margin: 0 }}>
        Arrives in Phase 3.
      </p>
    </div>
  );
}
