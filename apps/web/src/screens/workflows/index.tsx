import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { Link, Navigate, useLocation, useParams, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AppLink,
  DataTable,
  Icon,
  JsonViewer,
  ProblemError,
  SegmentedControl,
  Skeleton,
} from "../../components";
import { useMediaQuery } from "../../lib/useMediaQuery";
import { useRowKeys } from "../../lib/useRowKeys";
import { useScope } from "../../lib/scope";
import { RailFact } from "../skills/RailFact";
import "../skills/SkillDetail.css";
import "../skills/Skills.css";
import { skillsHome, SKILLS_PICKER } from "../skills/routes";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { DiscussButton, useDiscussTarget } from "../../shell/discuss";
import { HistoryPanel } from "../item-history";
import { kindLabelOf, NodePanel, useNodeParam, WorkflowGraph } from "./WorkflowGraph";
import {
  canvasModel,
  neighbours,
  visibleEdges,
  type CanvasModel,
  type CanvasStep,
  type Edge,
} from "./graphModel";
import { StartRun, startableFromWeb } from "../runs-list/StartRun";
import { RoundsRule, StepList, StepWhat } from "./StepList";
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

function Page({ children, view }: { children: ReactNode; view?: string }) {
  return (
    <div className="wf-detail ah-stack" data-view={view}>
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

type WorkflowView = "graph" | "steps" | "document";

const VIEWS: { id: WorkflowView; label: string }[] = [
  { id: "graph", label: "Graph" },
  { id: "steps", label: "Steps" },
  { id: "document", label: "Document" },
];

/** `?view=`: the graph by default, the steps on a phone. */
function useViewParam(): [WorkflowView, (view: WorkflowView) => void] {
  const [params, setParams] = useSearchParams();
  const phone = useMediaQuery("(max-width: 767px)");
  const raw = params.get("view");
  const view: WorkflowView =
    raw === "graph" || raw === "steps" || raw === "document" ? raw : phone ? "steps" : "graph";
  const set = (next: WorkflowView) => {
    setParams(
      (current) => {
        const p = new URLSearchParams(current);
        p.set("view", next);
        return p;
      },
      { replace: true },
    );
  };
  return [view, set];
}

/** The kinds a workflow uses, each with its tile and what it means. */
function StepKinds({ types }: { types: Record<string, number> }) {
  const kinds = kindCounts(types).map(([kind]) => kind);
  if (kinds.length === 0) return null;
  return (
    <ul className="wf-kinds">
      {kinds.map((kind) => (
        <li key={kind}>
          <span className="wf-kind-tile" data-kind={kind} aria-hidden="true">
            <Icon name={STEP_KINDS[kind].icon} size="sm" />
          </span>
          <span style={{ fontWeight: 500 }}>
            {kind === "repeat"
              ? "Rounds"
              : `${(STEP_KINDS[kind].one[0] ?? "").toUpperCase()}${STEP_KINDS[kind].one.slice(1)}`}
          </span>
          <span className="ah-small ah-muted">{STEP_KINDS[kind].hint}</span>
        </li>
      ))}
    </ul>
  );
}

/** About this workflow: what you give it, where it lives, its step kinds and how to move around. */
function About({
  workflow,
  view,
  inline = false,
}: {
  workflow: WorkflowDetail;
  view: WorkflowView;
  inline?: boolean;
}) {
  const needs = workflow.inputs;
  return (
    <aside
      className={inline ? "ah-card wf-about-inline" : "ah-skill-rail"}
      aria-label="About this workflow"
    >
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
        <div className="ah-stack" style={{ gap: 4, marginTop: 12 }}>
          <AppLink
            className="ah-small"
            href={`/runs?workflow=${encodeURIComponent(workflow.name)}`}
          >
            Runs of this workflow
          </AppLink>
          {workflow.source === "hub" && (
            <Link className="ah-small" to={{ search: "?view=document", hash: "history" }}>
              History of this file
            </Link>
          )}
        </div>
      </section>
      {workflow.step_types && Object.keys(workflow.step_types).length > 0 && (
        <section aria-label="Step kinds" className="ah-skill-rail-section">
          <h2 className="ah-caption" style={{ margin: "0 0 8px" }}>
            Step kinds
          </h2>
          <StepKinds types={workflow.step_types} />
        </section>
      )}
      {view === "graph" && (
        <section aria-label="How to move around" className="ah-skill-rail-section">
          <h2 className="ah-caption" style={{ margin: "0 0 6px" }}>
            How to move around
          </h2>
          <p className="ah-small ah-subtle" style={{ margin: 0 }}>
            Drag to move · ⌘ or Ctrl + scroll to zoom · arrow keys follow the arrows. Choose a step
            to see what it does and what leads to it.
          </p>
        </section>
      )}
    </aside>
  );
}

function StepChipList({
  ids,
  steps,
  onOpen,
  none,
}: {
  ids: string[];
  steps: CanvasModel["steps"];
  onOpen: (id: string) => void;
  none: string;
}) {
  if (ids.length === 0) return <span className="ah-muted">{none}</span>;
  return (
    <span className="wf-chips">
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          className="ah-fm-chip ah-mono wf-chip-btn"
          onClick={() => {
            onOpen(id);
          }}
        >
          {steps.get(id)?.bare ?? id}
        </button>
      ))}
    </span>
  );
}

/** The chosen step: what it waits for and leads to, its condition, what it does, as written. */
function StepInspector({
  step,
  model,
  edges,
  focusOnOpen,
  onOpen,
  onClose,
}: {
  step: CanvasStep;
  model: CanvasModel;
  edges: Edge[];
  focusOnOpen: boolean;
  onOpen: (id: string) => void;
  onClose: () => void;
}) {
  const kind = stepKind(step.type);
  const titled = step.description !== null && step.description.trim() !== "";
  const { next, previous } = neighbours(edges, step.id);
  const doc: DocNode = step.doc ?? { id: step.bare, type: step.type };
  const condition = typeof doc.when === "string" && doc.when.trim() ? doc.when : null;
  const body = model.groups.get(step.id);
  return (
    <NodePanel
      id={step.id}
      focusOnOpen={focusOnOpen}
      onClose={onClose}
      heading={
        <>
          <span className={titled ? undefined : "ah-mono"}>
            {titled ? step.description : step.bare}
          </span>
          <span className="wf-inspector-kind">
            <span className="wf-kind-tile" data-kind={kind} aria-hidden="true">
              <Icon name={STEP_KINDS[kind].icon} size="sm" />
            </span>
            {titled && (
              <>
                <span className="ah-mono">{step.bare}</span>
                <span aria-hidden="true">·</span>
              </>
            )}
            {kindLabelOf(step.type)}
          </span>
        </>
      }
    >
      <dl className="wf-facts">
        <div>
          <dt className="ah-caption">Waits for</dt>
          <dd>
            <StepChipList
              ids={previous}
              steps={model.steps}
              onOpen={onOpen}
              none={step.group ? "Starts the round" : "Starts first"}
            />
          </dd>
        </div>
        <div>
          <dt className="ah-caption">Leads to</dt>
          <dd>
            <StepChipList
              ids={next}
              steps={model.steps}
              onOpen={onOpen}
              none={step.group ? "Ends the round" : "Ends the run"}
            />
          </dd>
        </div>
        {condition && (
          <div>
            <dt className="ah-caption">Only when</dt>
            <dd>
              <span className="wf-step-cond">
                <code>{condition}</code>
              </span>
            </dd>
          </div>
        )}
        {kind !== "wait" && kind !== "stop" && (
          <div>
            <dt className="ah-caption">What it does</dt>
            <dd>
              {body ? (
                <>
                  <RoundsRule group={doc} />
                  <span className="ah-caption" style={{ marginTop: 6 }}>
                    Steps inside
                  </span>
                  <StepChipList
                    ids={body.flat().map((s) => s.id)}
                    steps={model.steps}
                    onOpen={onOpen}
                    none="None"
                  />
                </>
              ) : (
                (StepWhat({ node: doc, id: step.bare }) ?? (
                  <span className="ah-muted">{STEP_KINDS[kind].hint}</span>
                ))
              )}
            </dd>
          </div>
        )}
      </dl>
      {step.doc && (
        <details className="wf-prompt">
          <summary>
            <Icon name="chevron-right" />
            As written in the file
          </summary>
          <div className="wf-prompt-body" style={{ alignItems: "stretch" }}>
            <JsonViewer value={step.doc} maxHeight={320} />
          </div>
        </details>
      )}
    </NodePanel>
  );
}

type DocNode = Record<string, unknown>;

function DetailBody({ workflow }: { workflow: WorkflowDetail }) {
  const node = useNodeParam();
  const [view, setView] = useViewParam();
  const laptop = useMediaQuery("(min-width: 1280px)", true);
  const model = useMemo(() => canvasModel(workflow.layers, workflow.document), [workflow]);
  const allGroups = useMemo(() => new Set(model.groups.keys()), [model]);
  const edges = useMemo(
    () => visibleEdges(workflow.layers, model, allGroups),
    [workflow.layers, model, allGroups],
  );
  const selected = (node.nodeId ? model.steps.get(node.nodeId) : undefined) ?? null;
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
  const stepsRef = useRef<HTMLElement>(null);
  useRowKeys(view === "steps" ? stepsRef : NO_ROWS);
  // The document view scrolls to History when the link asks for it.
  const { hash } = useLocation();
  useEffect(() => {
    if (view === "document" && hash === "#history") {
      document.getElementById("history")?.scrollIntoView({ block: "start" });
    }
  }, [view, hash]);
  const inspector = selected ? (
    <StepInspector
      step={selected}
      model={model}
      edges={edges}
      focusOnOpen={node.openedByUser}
      onOpen={node.open}
      onClose={node.close}
    />
  ) : null;
  return (
    <Page view={view}>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: workflow.project, href: `/projects/${encodeURIComponent(workflow.project)}` },
          { label: "Toolkit", href: skillsHome(workflow.project) },
          { label: "Workflows", href: workflowsTab(workflow.project) },
          { label: workflow.name, mono: true },
        ]}
      />
      <header className="wf-head">
        <div className="ah-row ah-wrap" style={{ gap: 12 }}>
          <h1 className="ah-h1 ah-mono" style={{ margin: 0 }}>
            {workflow.name}
          </h1>
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
        {workflow.description && (
          <p className="ah-skill-lede" style={{ margin: 0 }}>
            {workflow.description}
          </p>
        )}
        <div className="wf-head-meta">
          <p className="wf-shape">{shapeInWords(workflow.steps)}</p>
          <StepChips types={workflow.step_types ?? {}} />
        </div>
      </header>
      <div className="wf-viewbar">
        <SegmentedControl
          label="View"
          value={view}
          onChange={(id) => {
            setView(id === "steps" || id === "document" ? id : "graph");
          }}
          options={VIEWS}
        />
      </div>
      {view === "graph" && (
        <>
          {!laptop && <About workflow={workflow} view={view} inline />}
          <WorkflowGraph
            textAlternative="none"
            layers={workflow.layers}
            document={workflow.document}
            selected={selected?.id ?? null}
            onSelect={node.open}
            onClose={node.close}
            wheel={laptop ? "pan" : "page"}
            panel={inspector ?? (laptop ? <About workflow={workflow} view={view} /> : null)}
          />
        </>
      )}
      {view === "steps" && (
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
          <About workflow={workflow} view={view} />
        </div>
      )}
      {view === "document" && (
        <>
          <section aria-label="Document" className="ah-stack" style={{ gap: 8 }}>
            <h2 className="ah-h3" style={{ margin: 0 }}>
              Document
            </h2>
            <span className="ah-small ah-subtle">The parsed document (JSON), read-only.</span>
            <JsonViewer value={workflow.document} maxHeight={640} />
          </section>
          {workflow.source === "hub" && (
            <div id="history">
              <HistoryPanel
                target={{ kind: "workflow", project: workflow.project, name: workflow.name }}
              />
            </div>
          )}
        </>
      )}
    </Page>
  );
}

const NO_ROWS = { current: null };

/** One workflow: its layered graph, a node's panel and its document. */
export function WorkflowDetailScreen() {
  const { project = "", name = "" } = useParams();
  const workflow = useWorkflow(project, name);
  if (workflow.isPending) {
    return (
      <Page view="graph">
        <div aria-busy="true" aria-label={`Loading ${name}`} role="status" className="wf-loading">
          <Skeleton width={320} height={28} />
          <Skeleton lines={1} />
          <Skeleton width={220} height={32} />
          <div className="wf-canvas" data-panel="">
            <div className="wf-canvas-viewport wf-loading-canvas">
              {[1, 2, 1].map((n, i) => (
                <div key={i} className="wf-col">
                  {Array.from({ length: n }, (_, j) => (
                    <Skeleton key={j} width={216} height={60} />
                  ))}
                </div>
              ))}
            </div>
            <div className="wf-panel" style={{ padding: 16 }}>
              <Skeleton lines={8} />
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
