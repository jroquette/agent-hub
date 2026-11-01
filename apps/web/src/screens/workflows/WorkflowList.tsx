/* A project's workflows as catalog cards: the Toolkit's Workflows tab shows them without loading
 * the Workflows screen, whose code loads on demand. */
import "../skills/Skills.css";

import type { components } from "../../api/schema";
import { AppLink, DataTable, Icon } from "../../components";
import { workflowHref } from "../skills/routes";
import type { WorkflowStep, WorkflowSummary } from "./queries";
import { stepKind } from "./steps";

/** "8 steps · Claude does 3 · repeats up to 3 times": the shape of a workflow in words. */
export function shapeInWords(steps: readonly WorkflowStep[]): string {
  let total = 0;
  let claude = 0;
  let asks = 0;
  let rounds = 0;
  const walk = (list: readonly WorkflowStep[]) => {
    for (const step of list) {
      if (step.type === "loop_group") {
        rounds = Math.max(rounds, step.max_iterations ?? 0);
        walk(step.body);
        continue;
      }
      total += 1;
      const kind = stepKind(step.type);
      if (kind === "agent") claude += 1;
      if (kind === "approval" || kind === "wait") asks += 1;
    }
  };
  walk(steps);
  const parts = [`${String(total)} ${total === 1 ? "step" : "steps"}`];
  if (claude > 0) parts.push(`Claude does ${String(claude)}`);
  if (rounds > 0) parts.push(`repeats in up to ${String(rounds)} rounds`);
  parts.push(asks > 0 ? "stops to ask you" : "runs without you");
  return parts.join(" · ");
}

/** A workflow as a catalog card, the shape of the Toolkit's other tabs: name, what it does, then
 * where it comes from, what you give it and its shape. Only the name takes a Tab stop. */
function WorkflowCard({ item, showProject }: { item: WorkflowSummary; showProject: boolean }) {
  const needs = item.inputs.filter((input) => input.required);
  const headingId = `workflow-card-${item.project}-${item.name}`;
  return (
    <li className="ah-skill-card-item">
      <article className="ah-skill-card" aria-labelledby={headingId}>
        <header className="ah-skill-card-head">
          <h3 id={headingId} className="ah-skill-name">
            <AppLink href={workflowHref(item)}>{item.name}</AppLink>
          </h3>
          <span className="ah-grow" />
          {showProject && <span className="ah-skill-meta">{item.project}</span>}
        </header>
        <p className="ah-skill-desc" title={item.description ?? undefined}>
          {item.description ?? "No description."}
        </p>
        <footer className="ah-skill-card-foot">
          <span className="ah-skill-card-line">
            <span className="ah-skill-meta">
              <Icon name={item.source === "hub" ? "warehouse" : "package"} size="sm" />
              {item.source === "hub" ? "Hub" : "Built-in"}
            </span>
            <span className="ah-skill-meta">
              <Icon name="braces" size="sm" />
              {needs.length > 0
                ? `You give it: ${needs.map((input) => input.name).join(", ")}`
                : "Takes no input"}
            </span>
          </span>
          <span className="ah-skill-meta">
            <Icon name="list-checks" size="sm" />
            {shapeInWords(item.steps)}
          </span>
        </footer>
      </article>
    </li>
  );
}

type WorkflowCatalog = components["schemas"]["WorkflowCatalogView"];

/** A project's workflows, the hub's own first, and the files that do not load. */
export function WorkflowList({
  catalog,
  query = "",
}: {
  catalog: Pick<WorkflowCatalog, "items" | "problems">;
  query?: string;
}) {
  const q = query.trim().toLowerCase();
  const items = catalog.items
    .filter((item) => !q || `${item.name}\n${item.description ?? ""}`.toLowerCase().includes(q))
    .sort((x, y) => Number(x.source === "builtin") - Number(y.source === "builtin"));
  const showProject = new Set(items.map((item) => item.project)).size > 1;
  const { problems } = catalog;
  return (
    <>
      {items.length > 0 && (
        <ul className="ah-skills-grid" aria-label="Workflows">
          {items.map((item) => (
            <WorkflowCard
              key={`${item.project}/${item.name}`}
              item={item}
              showProject={showProject}
            />
          ))}
        </ul>
      )}
      {problems.length > 0 && (
        <DataTable
          caption="Files that do not load"
          density="compact"
          rows={problems}
          rowKey={(p) => `${p.project}/${p.file}/${p.key}`}
          columns={[
            {
              id: "file",
              label: "File",
              render: (p) => (
                <span className="ah-mono" style={{ color: "var(--failed)" }}>
                  {p.file}
                  {p.line === null ? "" : `:${String(p.line)}`}
                </span>
              ),
            },
            { id: "key", label: "Key", render: (p) => <span className="ah-mono">{p.key}</span> },
            { id: "message", label: "Problem", render: (p) => p.message },
          ]}
        />
      )}
    </>
  );
}
