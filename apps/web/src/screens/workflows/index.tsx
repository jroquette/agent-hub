import { useRef, useState, type ReactNode } from "react";
import { Navigate, useParams } from "react-router";

import type { components } from "../../api/schema";
import { AppLink, DataTable, Icon, JsonViewer, ProblemError, Skeleton } from "../../components";
import { useRowKeys } from "../../lib/useRowKeys";
import { useScope } from "../../lib/scope";
import { RailFact } from "../skills/RailFact";
import "../skills/SkillDetail.css";
import { skillsHome, SKILLS_PICKER } from "../skills/routes";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { DiscussButton, useDiscussTarget } from "../../shell/discuss";
import { HistoryPanel } from "../item-history";
import { NodePanel, useNodeParam, WorkflowGraph } from "./WorkflowGraph";
import { StartRun, startableFromWeb } from "../runs-list/StartRun";
import { StepList } from "./StepList";
import "./workflows.css";
import {
  useWorkflow,
  type WorkflowDetail,
  type WorkflowStep,
  type WorkflowSummary,
} from "./queries";
import { countLabel, kindCounts, STEP_KINDS, stepKind } from "./steps";

/* Workflows (plan 6.3, AC-213.15): the list a project's Toolkit shows in its Workflows tab, and one
 * workflow's layered graph and document, read-only. */

export function SourceBadge({ source }: { source: WorkflowSummary["source"] }) {
  return (
    <span className="ah-badge ah-badge-quiet">
      <Icon name={source === "hub" ? "warehouse" : "package"} />
      {source === "hub" ? "Hub" : "Built-in"}
    </span>
  );
}

/** A workflow's page, inside its project's Toolkit. */
export function workflowHref(item: { project: string; name: string }): string {
  return `${skillsHome(item.project)}/workflows/${encodeURIComponent(item.name)}`;
}

/** The Toolkit's Workflows tab of a project. */
export function workflowsTab(project: string): string {
  return `${skillsHome(project)}?view=workflows`;
}

function Page({ children }: { children: ReactNode }) {
  return <div className="wf-detail ah-stack">{children}</div>;
}

/** The step kinds of a workflow as quiet chips: "3 AI agents", "5 commands". */
export function StepChips({ types }: { types: Record<string, number> }) {
  const counts = kindCounts(types);
  if (counts.length === 0) return null;
  return (
    <span className="ah-row ah-wrap" style={{ gap: 6 }}>
      {counts.map(([kind, n]) => (
        <span key={kind} className="ah-badge ah-badge-quiet" title={STEP_KINDS[kind].hint}>
          <Icon name={STEP_KINDS[kind].icon} />
          {countLabel(kind, n)}
        </span>
      ))}
    </span>
  );
}

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

function WorkflowRow({ item, showProject }: { item: WorkflowSummary; showProject: boolean }) {
  const needs = item.inputs.filter((input) => input.required);
  return (
    <li>
      <AppLink href={workflowHref(item)} className="wf-row">
        <span className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
          <span className="ah-row" style={{ gap: 8 }}>
            <span className="wf-name">{item.name}</span>
            {item.source === "builtin" && <span className="ah-small ah-subtle">built-in</span>}
            {showProject && <span className="ah-small ah-subtle">· {item.project}</span>}
          </span>
          <span className="ah-muted">{item.description ?? "No description."}</span>
          <span className="ah-small ah-subtle">
            {needs.length > 0
              ? `You give it: ${needs.map((input) => input.name).join(", ")}`
              : "Takes no input"}
            {" · "}
            {shapeInWords(item.steps)}
          </span>
        </span>
        <Icon name="chevron-right" className="wf-chevron" />
      </AppLink>
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
        <ul className="wf-list" aria-label="Workflows">
          {items.map((item) => (
            <WorkflowRow
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

/** `/workflows`, an older link: the Toolkit's Workflows tab of the project in scope, else the picker. */
export function WorkflowsScreen() {
  const [scope] = useScope();
  return <Navigate to={scope === null ? SKILLS_PICKER : workflowsTab(scope)} replace />;
}

/** `/workflows/:project/:name`, an older link: the workflow's page in its project's Toolkit. */
export function LegacyWorkflowRedirect() {
  const { project = "", name = "" } = useParams();
  return <Navigate to={workflowHref({ project, name })} replace />;
}

type DocNode = Record<string, unknown>;

/** The node as written in the document, when it sits at the top level of `nodes`. */
function documentNode(workflow: WorkflowDetail, id: string): DocNode | undefined {
  const nodes: unknown = (workflow.document as Record<string, unknown>).nodes;
  if (!Array.isArray(nodes)) return undefined;
  return (nodes as unknown[]).find(
    (node): node is DocNode =>
      typeof node === "object" && node !== null && (node as DocNode).id === id,
  );
}

function DetailBody({ workflow }: { workflow: WorkflowDetail }) {
  const node = useNodeParam();
  const nodes = workflow.layers.flat();
  const selected = nodes.find((n) => n.id === node.nodeId) ?? null;
  const written = selected ? documentNode(workflow, selected.id) : undefined;
  useDiscussTarget({
    key: `workflow:${workflow.project}:${workflow.name}`,
    project: workflow.project,
    kind: "Workflow",
    title: workflow.name,
    brief:
      workflow.source === "hub"
        ? `It is defined in a pack under the hub's \`workflows/\` folder; find the file that declares it.${selected ? ` I am looking at its node \`${selected.id}\`.` : ""}`
        : "It is a built-in workflow shipped with agent-hub, not a file of this hub: to change it, propose a copy in the hub's `workflows/` folder.",
  });
  const needs = workflow.inputs;
  const [advanced, setAdvanced] = useState(selected !== null);
  const stepsRef = useRef<HTMLElement>(null);
  useRowKeys(stepsRef);
  return (
    <Page>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: workflow.project, href: `/projects/${encodeURIComponent(workflow.project)}` },
          { label: "Toolkit", href: skillsHome(workflow.project) },
          { label: "Workflows", href: workflowsTab(workflow.project) },
          { label: workflow.name, mono: true },
        ]}
      />
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h1 className="ah-h1 ah-mono">{workflow.name}</h1>
        <SourceBadge source={workflow.source} />
        <span className="ah-grow" />
        <DiscussButton />
        {startableFromWeb(workflow.name) ? (
          <StartRun
            project={workflow.project}
            workflow={{ project: workflow.project, name: workflow.name }}
            label="Run this workflow"
          />
        ) : (
          <span className="ah-small ah-subtle">
            Starts from <code className="ah-mono">hub run</code>
          </span>
        )}
      </div>
      {workflow.description && <p className="ah-skill-lede">{workflow.description}</p>}
      <p className="wf-shape">{shapeInWords(workflow.steps)}</p>
      <div className="ah-skill-layout">
        <div className="ah-skill-main">
          <section aria-label="Step by step" className="ah-card ah-card-body" ref={stepsRef}>
            <div className="wf-steps-head">
              <h2 className="ah-h3" style={{ margin: 0 }}>
                Step by step
              </h2>
              <StepChips types={workflow.step_types ?? {}} />
            </div>
            <StepList layers={workflow.layers} document={workflow.document} />
          </section>
        </div>
        <aside className="ah-skill-rail" aria-label="About this workflow">
          <section aria-label="What you give it" className="ah-skill-rail-section">
            <h2 className="ah-caption" style={{ margin: "0 0 6px" }}>
              What you give it
            </h2>
            {needs.length === 0 ? (
              <span className="ah-small ah-subtle">Nothing: it runs as is.</span>
            ) : (
              <dl className="ah-skill-rail-facts" style={{ margin: 0 }}>
                {needs.map((input) => (
                  <div key={input.name} className="ah-skill-fact">
                    <dt className="ah-mono" style={{ color: "var(--text)", fontWeight: 600 }}>
                      {input.name}
                      {!input.required && <span className="ah-subtle"> (optional)</span>}
                    </dt>
                    <dd className="ah-muted">{input.description ?? input.type}</dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
          <section aria-label="Where it lives" className="ah-skill-rail-section">
            <h2 className="ah-caption" style={{ margin: "0 0 6px" }}>
              Where it lives
            </h2>
            <p className="ah-small ah-muted" style={{ margin: "0 0 12px" }}>
              {workflow.source === "hub"
                ? "A YAML file in this hub's workflows/ folder. Edit the file (or ask Claude with Discuss) and this page updates."
                : "Built into agent-hub. To change it, copy it into the hub's workflows/ folder with the same name: the hub's copy wins."}
            </p>
            <dl className="ah-skill-rail-facts" style={{ margin: 0 }}>
              <RailFact term="Revision" mono>
                r{workflow.revision}
              </RailFact>
            </dl>
            <AppLink
              className="ah-small"
              href={`/runs?workflow=${encodeURIComponent(workflow.name)}`}
              style={{ display: "inline-block", marginTop: 12 }}
            >
              Runs of this workflow
            </AppLink>
          </section>
        </aside>
      </div>
      <details
        className="ah-card ah-skill-fold wf-advanced"
        open={advanced}
        onToggle={(event) => {
          setAdvanced(event.currentTarget.open);
        }}
      >
        <summary className="ah-card-head">
          <Icon name="chevron-right" size="sm" />
          <span className="ah-h3">Advanced: graph and document</span>
        </summary>
        <div className="ah-card-body wf-advanced-body">
          <WorkflowGraph
            layers={workflow.layers}
            selected={selected?.id ?? null}
            onSelect={node.open}
          />
          {selected && (
            <NodePanel id={selected.id} focusOnOpen={node.openedByUser} onClose={node.close}>
              <div className="wf-node-detail">
                <dl className="wf-node-facts">
                  <div className="ah-skill-fact">
                    <dt>Type</dt>
                    <dd className="ah-mono">{selected.type}</dd>
                  </div>
                  <div className="ah-skill-fact">
                    <dt>Waits for</dt>
                    <dd className="ah-mono">{selected.depends_on.join(", ") || "—"}</dd>
                  </div>
                  {selected.description && (
                    <div className="ah-skill-fact">
                      <dt>Description</dt>
                      <dd>{selected.description}</dd>
                    </div>
                  )}
                </dl>
                {written && <JsonViewer value={written} maxHeight={360} />}
              </div>
            </NodePanel>
          )}
          <section aria-label="Document" className="ah-stack" style={{ gap: 8 }}>
            <h3 className="ah-h3" style={{ margin: 0 }}>
              Document
            </h3>
            <span className="ah-small ah-subtle">The parsed document (JSON), read-only.</span>
            <JsonViewer value={workflow.document} maxHeight={480} />
          </section>
        </div>
      </details>
      {workflow.source === "hub" && (
        <HistoryPanel
          target={{ kind: "workflow", project: workflow.project, name: workflow.name }}
        />
      )}
    </Page>
  );
}

/** One workflow: its layered graph, a node's panel and its document. */
export function WorkflowDetailScreen() {
  const { project = "", name = "" } = useParams();
  const workflow = useWorkflow(project, name);
  if (workflow.isPending) {
    return (
      <Page>
        <div aria-busy="true" aria-label={`Loading ${name}`} role="status" className="ah-stack">
          <Skeleton width={320} height={28} />
          <Skeleton lines={1} />
          <div className="ah-skill-layout">
            <div className="ah-card ah-card-body">
              <Skeleton lines={10} />
            </div>
            <div className="ah-skill-rail ah-card-body">
              <Skeleton lines={6} />
            </div>
          </div>
        </div>
      </Page>
    );
  }
  if (workflow.isError) {
    if (workflow.error.status === 404) {
      return (
        <Page>
          <h1 className="ah-h2">Workflow {name} not found</h1>
          <p className="ah-muted" style={{ margin: 0 }}>
            Project {project} has no workflow {name} that loads. It may have been renamed, or its
            file may not load.
          </p>
          <AppLink className="ah-btn" href={workflowsTab(project)}>
            Go to Workflows
          </AppLink>
        </Page>
      );
    }
    return (
      <Page>
        <ProblemError
          title="Could not load workflow"
          detail={workflow.error.detail}
          status={workflow.error.status}
          onRetry={() => void workflow.refetch()}
        />
      </Page>
    );
  }
  return <DetailBody workflow={workflow.data} />;
}
