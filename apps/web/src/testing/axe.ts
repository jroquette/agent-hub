import axe from "axe-core";

/** A violation as tests report it: the rule id, its impact and how many nodes break it. */
export interface Violation {
  id: string;
  impact: string | null;
  nodes: number;
}

const BLOCKING = new Set(["serious", "critical"]);

/** The serious and critical axe violations inside `container` (the a11y gate, AC-200.57). */
export async function seriousViolations(container: Element): Promise<Violation[]> {
  const results = await axe.run(container, { resultTypes: ["violations"] });
  return results.violations
    .filter((violation) => BLOCKING.has(violation.impact ?? ""))
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact ?? null,
      nodes: violation.nodes.length,
    }));
}
