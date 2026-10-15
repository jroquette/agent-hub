import type { ReactNode } from "react";
import { useNavigate, useParams } from "react-router";

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
import { NodePanel, useNodeParam, WorkflowGraph } from "./WorkflowGraph";
import { useWorkflow, useWorkflows, type WorkflowDetail, type WorkflowSummary } from "./queries";

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

/** The catalog: every workflow of the projects in scope, and the files that do not load. */
export function WorkflowsScreen() {
  const [scope] = useScope();
  const navigate = useNavigate();
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
  } else {
    const problems = catalog.data?.problems ?? [];
    content = (
      <>
        <DataTable
          caption="Workflows"
          density="compact"
          loading={catalog.isPending}
          rows={catalog.data?.items ?? []}
          rowKey={(item) => `${item.project}/${item.name}`}
          onRowClick={(item) => void navigate(workflowHref(item))}
          columns={[
            {
              id: "name",
              label: "Workflow",
              render: (item) => (
                <div className="ah-stack" style={{ gap: 0, padding: "5px 0" }}>
                  <span className="ah-mono" style={{ fontWeight: 500 }}>
                    {item.name}
                  </span>
                  {item.description && (
                    <span className="ah-small ah-subtle">{item.description}</span>
                  )}
                </div>
              ),
            },
            {
              id: "project",
              label: "Project",
              width: 160,
              render: (item) => <span className="ah-mono">{item.project}</span>,
            },
            {
              id: "source",
              label: "Source",
              width: 110,
              render: (item) => <SourceBadge source={item.source} />,
            },
            {
              id: "size",
              label: "Revision · size",
              width: 180,
              render: (item) => (
                <span className="ah-small">
                  <span className="ah-mono">r{item.revision}</span> · {item.node_count} nodes ·{" "}
                  {item.layer_count} layers
                </span>
              ),
            },
          ]}
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
      <h1 className="ah-h1">Workflows</h1>
      <p className="ah-muted" style={{ margin: 0 }}>
        The workflows each hub can run: its own files, then the built-ins it does not override.
      </p>
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
        <span className="ah-small ah-subtle">
          r{workflow.revision} · {workflow.node_count} nodes · {workflow.layer_count} layers
        </span>
      </div>
      {workflow.description && (
        <p className="ah-muted" style={{ margin: 0 }}>
          {workflow.description}
        </p>
      )}
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
        <h2 className="ah-h3" style={{ margin: 0 }}>
          Document
        </h2>
        <span className="ah-small ah-subtle">The parsed document (JSON), read-only.</span>
        <JsonViewer value={workflow.document} maxHeight={480} />
      </section>
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
