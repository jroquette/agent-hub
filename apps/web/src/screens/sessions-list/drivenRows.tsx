/* Driven sessions as rows of the sections (AC-234.8): where such a row opens. */
import { agentSessionHref } from "./control";
import { isDriven, type SectionRow } from "./sections";

/** Where a row opens: a driven session or a twin opens its chat, others their detail. */
export function rowHref(row: SectionRow): string {
  if (isDriven(row)) return agentSessionHref(row.id);
  return row.agent_session_id
    ? agentSessionHref(row.agent_session_id)
    : `/sessions/${encodeURIComponent(row.id)}`;
}
