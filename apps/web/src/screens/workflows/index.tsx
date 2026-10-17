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
import { FlowStrip, flowInWords } from "./FlowStrip";
import { StepList } from "./StepList";
import "./workflows.css";
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

const LEGEND: readonly { kind: StepKind; label: string; color: string }[] = [
  { kind: "agent", label: "AI agent (Claude)", color: "var(--accent)" },
  { kind: "command", label: "Command or script", color: "var(--border-strong)" },
  { kind: "approval", label: "Waits for you", color: "var(--waiting)" },
];

/** One line under the title: the colour of each kind of step, and the longer story on demand. */
function Legend() {
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <div className="wf-legend ah-small ah-muted">
        {LEGEND.map((item) => (
          <span key={item.kind} className="ah-row" style={{ gap: 6 }}>
            <span className="wf-dot" style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
        <span className="ah-row" style={{ gap: 6 }}>
          <Icon name="refresh-cw" size="sm" />
          Steps in a dashed box repeat in rounds
        </span>
      </div>
      <details className="ah-small">
        <summary style={{ cursor: "pointer", color: "var(--accent)", width: "fit-content" }}>
          What is a workflow?
        </summary>
        <p className="ah-muted" style={{ margin: "8px 0 0", maxWidth: 760 }}>
          A workflow is a recipe the hub follows on its own, from start to finish, with no one at
          the keyboard. You give it a few inputs (an issue, a repo), and it runs its steps in order:
          AI agents write or review code, commands run the tests or git, and some steps stop to ask
          you. An agent decides <i>how</i> to do its step; the workflow decides <i>which</i> steps
          happen, in what order, and when to stop. Each start becomes a{" "}
          <AppLink href="/runs">workflow run</AppLink> you can follow live.
        </p>
      </details>
    </div>
  );
}

function WorkflowRow({ item, showProject }: { item: WorkflowSummary; showProject: boolean }) {
  const href = workflowHref(item);
  const needs = item.inputs.filter((input) => input.required);
  return (
    <li className="wf-row">
      <div className="wf-about ah-stack" style={{ gap: 4, minWidth: 0 }}>
        <span className="ah-row ah-wrap" style={{ gap: 8 }}>
          <AppLink href={href} className="wf-name">
            {item.name}
          </AppLink>
          {showProject && <span className="ah-small ah-subtle ah-mono">{item.project}</span>}
        </span>
        <span className="ah-muted">{item.description ?? "No description."}</span>
        <span className="ah-small ah-subtle">
          {needs.length > 0 ? (
            <>
              Starts with{" "}
              {needs.map((input, index) => (
                <span key={input.name}>
                  {index > 0 && ", "}
                  <span className="ah-mono" title={input.description ?? undefined}>
                    {input.name}
                  </span>
                </span>
              ))}
            </>
          ) : (
            "Takes no input"
          )}
        </span>
      </div>
      <FlowStrip steps={item.steps} label={`Steps: ${flowInWords(item.steps)}`} />
      <div className="wf-actions">
        {startableFromWeb(item.name) ? (
          <StartRun
            project={item.project}
            workflow={{ project: item.project, name: item.name }}
            label="Run"
            size="sm"
            variant="default"
          />
        ) : (
          <span
            className="ah-small ah-subtle"
            title="It writes to the tracker: start it with hub run"
          >
            via <code className="ah-mono">hub run</code>
          </span>
        )}
        <AppLink className="ah-btn ah-btn-sm" href={href} aria-label={`Details of ${item.name}`}>
          Details
          <Icon name="arrow-right" size="sm" />
        </AppLink>
      </div>
    </li>
  );
}

function Group({
  title,
  hint,
  items,
  showProject,
  empty,
}: {
  title: string;
  hint: string;
  items: WorkflowSummary[];
  showProject: boolean;
  empty?: ReactNode;
}) {
  return (
    <section aria-label={title} className="ah-stack" style={{ gap: 8, marginTop: 12 }}>
      <div className="ah-row ah-wrap" style={{ gap: 8, alignItems: "baseline" }}>
        <h2 className="ah-h3" style={{ margin: 0 }}>
          {title}
        </h2>
        <span className="ah-small ah-subtle">{hint}</span>
      </div>
      {items.length === 0 ? (
        empty
      ) : (
        <ul className="wf-list" aria-label={title}>
          {items.map((item) => (
            <WorkflowRow
              key={`${item.project}/${item.name}`}
              item={item}
              showProject={showProject}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/** The catalog: the hub's own workflows, then the built-ins, and the files that do not load. */
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
  } else if (catalog.isPending) {
    content = <Skeleton width="100%" height={160} />;
  } else if (catalog.data.items.length + catalog.data.problems.length === 0) {
    content = (
      <div className="ah-card">
        <EmptyState icon="workflow" title="No workflows defined">
          Workflows are YAML files in the hub. ./hub sync installs the default issue-to-pr workflow.
        </EmptyState>
      </div>
    );
  } else {
    const { items, problems } = catalog.data;
    const showProject = new Set(items.map((item) => item.project)).size > 1;
    content = (
      <>
        <Group
          title="Your workflows"
          hint="Files in the hub's workflows/ folder."
          items={items.filter((item) => item.source === "hub")}
          showProject={showProject}
          empty={
            <div className="ah-card ah-card-body ah-row ah-wrap" style={{ gap: 12 }}>
              <span className="ah-small ah-muted ah-grow">
                None yet. Describe one and Claude writes it, or copy a built-in to change it.
              </span>
              <AppLink className="ah-btn ah-btn-sm" href="/workflows/new">
                <Icon name="plus" size="sm" />
                New workflow
              </AppLink>
            </div>
          }
        />
        <Group
          title="Built into agent-hub"
          hint="Ready to use; a hub file with the same name replaces one."
          items={items.filter((item) => item.source === "builtin")}
          showProject={showProject}
        />
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
      <div className="ah-row ah-wrap" style={{ gap: 12, alignItems: "flex-start" }}>
        <div className="ah-stack ah-grow" style={{ gap: 4 }}>
          <h1 className="ah-h1">Workflows</h1>
          <p className="ah-muted" style={{ margin: 0 }}>
            Automations the hub runs on its own, step by step: you give the inputs, it does the
            rest.
          </p>
        </div>
        <AppLink className="ah-btn" href="/workflows/new">
          <Icon name="plus" />
          New workflow
        </AppLink>
        <StartRun project={scope} />
      </div>
      <Legend />
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
