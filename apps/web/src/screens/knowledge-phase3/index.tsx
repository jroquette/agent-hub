import { useParams } from "react-router";

import { ScreenPlaceholder } from "../../shell/ScreenPlaceholder";

const TITLES: Record<string, string> = {
  brain: "Brain",
  decisions: "Decisions",
  context: "Context",
};

/** Placeholder: the Knowledge sub-items that arrive in Phase 3 (D20); E4 ports the state. */
export function KnowledgePhase3Screen() {
  const { section = "" } = useParams();
  return <ScreenPlaceholder title={TITLES[section] ?? "Knowledge"} />;
}
