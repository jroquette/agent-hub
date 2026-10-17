import { useState, type ReactNode } from "react";
import { useParams } from "react-router";

import {
  AppLink,
  DataTable,
  EmptyState,
  Icon,
  JsonViewer,
  ProblemError,
  Skeleton,
} from "../../components";
import { useScope } from "../../lib/scope";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { DiscussButton, useDiscussTarget } from "../../shell/discuss";
import { NodePanel, useNodeParam, WorkflowGraph } from "./WorkflowGraph";
import { StartRun, startableFromWeb } from "../runs-list/StartRun";
import { StepList } from "./StepList";
import { useWorkflow, useWorkflows, type WorkflowDetail, type WorkflowSummary } from "./queries";
import { countLabel, kindCounts, STEP_KINDS, type StepKind } from "./steps";

/* Workflows (plan 6.3, AC-213.15): the catalog with the files that do not load, and one
 * workflow's layered graph and document, read-only. */

export function SourceBadge({ source }: { source: WorkflowSummary["source"] }) {
  return (
    <span className="ah-badge ah-badge-quiet">
      <Icon name={source === "hub" ? "warehouse" : "package"} />
      {source === "hub" ? "Hub" : "Built-in"}
    </span>
  );
}

function workflowHref(item: { project: string; name: string }): string {
  return `/workflows/${encodeURIComponent(item.project)}/${encodeURIComponent(item.name)}`;
}

function Page({ children }: { children: ReactNode }) {
  return (
    <div style={{ padding: "16px 32px 40px", minHeight: "100%" }} className="ah-stack">
      {children}
    </div>
  );
}

/** The catalog's opening: what a workflow is, in a few lines, and the step kinds. */
function WhatIsAWorkflow() {
  const kinds: [StepKind, string][] = [
    ["agent", "AI agent"],
    ["command", "Command"],
    ["approval", "Your approval"],
    ["repeat", "Rounds"],
  ];
  return (
    <section
      aria-label="What is a workflow"
      className="ah-card ah-card-body ah-stack"
      style={{ gap: 12 }}
    >
      <p style={{ margin: 0, maxWidth: 820 }}>
        A workflow is a <b>recipe the hub follows on its own</b> to get a job done, such as taking
        an issue to a pull request. It is a list of steps in a fixed order. An agent decides{" "}
        <i>how</i> to do its step; the workflow decides <i>which</i> steps happen, in what order,
        and when to stop. Each start shows up in <AppLink href="/runs">Workflow runs</AppLink>.
      </p>
      <ul
        aria-label="Kinds of step"
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 12,
        }}
      >
        {kinds.map(([kind, title]) => (
          <li key={kind} className="ah-row" style={{ gap: 8, alignItems: "flex-start" }}>
            <Icon name={STEP_KINDS[kind].icon} style={{ marginTop: 2, color: "var(--accent)" }} />
            <span className="ah-small">
              <b style={{ fontWeight: 600 }}>{title}</b>
              <br />
              <span className="ah-subtle">{STEP_KINDS[kind].hint}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
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

function WorkflowCard({ item, showProject }: { item: WorkflowSummary; showProject: boolean }) {
  const needs = item.inputs.filter((input) => input.required);
  return (
    <li>
      <AppLink
        href={workflowHref(item)}
        className="ah-pcard"
        style={{ height: "100%", color: "inherit", textDecoration: "none" }}
      >
        <span className="ah-row" style={{ gap: 8 }}>
          <Icon name="workflow" style={{ color: "var(--accent)" }} />
          <span className="ah-mono" style={{ fontWeight: 600, fontSize: 15 }}>
            {item.name}
          </span>
          <span className="ah-grow" />
          <SourceBadge source={item.source} />
        </span>
        <span className="ah-muted" style={{ minHeight: 40 }}>
          {item.description ?? "No description."}
        </span>
        <StepChips types={item.step_types ?? {}} />
        <span className="ah-row ah-wrap ah-small ah-subtle" style={{ gap: 6 }}>
          {needs.length > 0 ? (
            <>
              <span>You give it:</span>
              {needs.map((input) => (
                <span key={input.name} className="ah-mono" title={input.description ?? undefined}>
                  {input.name}
                </span>
              ))}
            </>
          ) : (
            <span>Takes no input.</span>
          )}
          <span className="ah-grow" />
          {showProject && <span className="ah-mono">{item.project}</span>}
          <span className="ah-row" style={{ gap: 2, color: "var(--accent)" }}>
            See the steps <Icon name="arrow-right" size="sm" />
          </span>
        </span>
      </AppLink>
    </li>
  );
}

/** The catalog: every workflow of the projects in scope, and the files that do not load. */
export function WorkflowsScreen() {
  const [scope] = useScope();
  const catalog = useWorkflows(scope);

  let content: ReactNode;
  if (catalog.isError) {
    content = (
      <ProblemError
        title="Could not load workflows"
        detail={catalog.error.detail}
        status={catalog.error.status}
        onRetry={() => void catalog.refetch()}
      />
    );
  } else if (catalog.isSuccess && catalog.data.items.length + catalog.data.problems.length === 0) {
    content = (
      <div className="ah-card">
        <EmptyState icon="workflow" title="No workflows defined">
          Workflows are YAML files in the hub. ./hub sync installs the default issue-to-pr workflow.
        </EmptyState>
      </div>
    );
  } else if (catalog.isPending) {
    content = <Skeleton width="100%" height={160} />;
  } else {
    const items = catalog.data.items;
    const problems = catalog.data.problems;
    const projects = new Set(items.map((item) => item.project));
    content = (
      <>
        <ul
          aria-label="Workflows"
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
            gap: 16,
          }}
        >
          {items.map((item) => (
            <WorkflowCard
              key={`${item.project}/${item.name}`}
              item={item}
              showProject={projects.size > 1}
            />
          ))}
        </ul>
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
              {
                id: "project",
                label: "Project",
                width: 160,
                render: (p) => <span className="ah-mono">{p.project}</span>,
              },
            ]}
          />
        )}
      </>
    );
  }

  return (
    <Page>
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h1 className="ah-h1">Workflows</h1>
        <span className="ah-grow" />
        <AppLink className="ah-btn" href="/workflows/new">
          <Icon name="plus" />
          New workflow
        </AppLink>
        <StartRun project={scope} />
      </div>
      <WhatIsAWorkflow />
      {content}
    </Page>
  );
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
  return (
    <Page>
      <Breadcrumbs
        items={[
          { label: "Workflows", href: "/workflows" },
          { label: workflow.project },
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
      {workflow.description && <p style={{ margin: 0, fontSize: 16 }}>{workflow.description}</p>}
      <StepChips types={workflow.step_types ?? {}} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 320px",
          gap: 24,
          alignItems: "start",
        }}
      >
        <section
          aria-label="Step by step"
          className="ah-card ah-card-body ah-stack"
          style={{ gap: 16 }}
        >
          <h2 className="ah-h3" style={{ margin: 0 }}>
            Step by step
          </h2>
          <StepList layers={workflow.layers} document={workflow.document} />
        </section>
        <aside className="ah-stack" style={{ gap: 16 }}>
          <section
            aria-label="What you give it"
            className="ah-card ah-card-body ah-stack"
            style={{ gap: 10 }}
          >
            <h2 className="ah-h3" style={{ margin: 0 }}>
              What you give it
            </h2>
            {needs.length === 0 ? (
              <span className="ah-small ah-subtle">Nothing: it runs as is.</span>
            ) : (
              <dl className="ah-small" style={{ margin: 0, display: "grid", gap: 8 }}>
                {needs.map((input) => (
                  <div key={input.name}>
                    <dt className="ah-mono" style={{ fontWeight: 600 }}>
                      {input.name}
                      {!input.required && <span className="ah-subtle"> (optional)</span>}
                    </dt>
                    <dd style={{ margin: 0 }} className="ah-subtle">
                      {input.description ?? input.type}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
          <section
            aria-label="Where it lives"
            className="ah-card ah-card-body ah-stack"
            style={{ gap: 6 }}
          >
            <h2 className="ah-h3" style={{ margin: 0 }}>
              Where it lives
            </h2>
            <span className="ah-small ah-subtle">
              {workflow.source === "hub"
                ? "A YAML file in this hub's workflows/ folder. Edit the file (or ask Claude with Discuss) and this page updates."
                : "Built into agent-hub. To change it, copy it into the hub's workflows/ folder with the same name: the hub's copy wins."}
            </span>
            <span className="ah-small ah-subtle">
              Revision {workflow.revision} · started from{" "}
              <AppLink href={`/runs?workflow=${encodeURIComponent(workflow.name)}`}>
                Workflow runs
              </AppLink>
            </span>
          </section>
        </aside>
      </div>
      <details
        className="ah-card ah-card-body"
        open={advanced}
        onToggle={(event) => {
          setAdvanced(event.currentTarget.open);
        }}
      >
        <summary className="ah-h3" style={{ cursor: "pointer" }}>
          Advanced: graph and document
        </summary>
        <div className="ah-stack" style={{ gap: 16, marginTop: 12 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: selected ? "minmax(0, 1fr) 320px" : "minmax(0, 1fr)",
              gap: 16,
              alignItems: "start",
            }}
          >
            <WorkflowGraph
              layers={workflow.layers}
              selected={selected?.id ?? null}
              onSelect={node.open}
            />
            {selected && (
              <NodePanel id={selected.id} focusOnOpen={node.openedByUser} onClose={node.close}>
                <dl className="ah-small" style={{ margin: 0, display: "grid", gap: 6 }}>
                  <dt className="ah-subtle">Type</dt>
                  <dd style={{ margin: 0 }}>{selected.type}</dd>
                  <dt className="ah-subtle">Waits for</dt>
                  <dd style={{ margin: 0 }} className="ah-mono">
                    {selected.depends_on.join(", ") || "—"}
                  </dd>
                  {selected.description && (
                    <>
                      <dt className="ah-subtle">Description</dt>
                      <dd style={{ margin: 0 }}>{selected.description}</dd>
                    </>
                  )}
                </dl>
                {written && (
                  <div style={{ marginTop: 8 }}>
                    <JsonViewer value={written} maxHeight={240} />
                  </div>
                )}
              </NodePanel>
            )}
          </div>
          <section aria-label="Document" className="ah-stack" style={{ gap: 8 }}>
            <h3 className="ah-h3" style={{ margin: 0 }}>
              Document
            </h3>
            <span className="ah-small ah-subtle">The parsed document (JSON), read-only.</span>
            <JsonViewer value={workflow.document} maxHeight={480} />
          </section>
        </div>
      </details>
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
        <Skeleton width={320} height={28} />
        <Skeleton width={560} height={160} />
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
          <AppLink className="ah-btn" href="/workflows">
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
