import { useSearchParams } from "react-router";

import { AppLink, Banner, Skeleton, StatusBadge, Time } from "../../components";
import { fmtDuration } from "../../lib/format";
import {
  durationSeconds,
  FAILURE_KIND_LABEL,
  SKIP_CAUSE_LABEL,
  shortRunId,
} from "../runs-list/model";
import type { WorkflowRun } from "../runs-list/queries";
import { NodePanel, WorkflowGraph } from "../workflows/WorkflowGraph";
import { useWorkflow } from "../workflows/queries";
import { nodeState, nodeSummary, runLayers, STATE_LOOK, type RunNode } from "./graph";

function NodeFacts({ node, now }: { node: RunNode; now: number }) {
  const step = node.step;
  const look = STATE_LOOK[nodeState(node)];
  return (
    <dl className="ah-small" style={{ margin: 0, display: "grid", gap: 6 }}>
      <dt className="ah-subtle">State</dt>
      <dd style={{ margin: 0 }}>
        <StatusBadge status={look.status} label={look.label} />
        {step && ` · attempt ${String(step.attempt)} of ${String(step.max_attempts)}`}
      </dd>
      <dt className="ah-subtle">Type</dt>
      <dd style={{ margin: 0 }}>{node.type}</dd>
      {step && (
        <>
          <dt className="ah-subtle">Started</dt>
          <dd style={{ margin: 0 }}>
            <Time iso={step.started_at} absolute /> ·{" "}
            {fmtDuration(durationSeconds(step.started_at, step.ended_at, now))}
          </dd>
        </>
      )}
      {step?.failure_kind && (
        <>
          <dt className="ah-subtle">Failure kind</dt>
          <dd style={{ margin: 0 }}>{FAILURE_KIND_LABEL[step.failure_kind]}</dd>
        </>
      )}
      {step?.skip_cause && (
        <>
          <dt className="ah-subtle">Skip cause</dt>
          <dd style={{ margin: 0 }}>{SKIP_CAUSE_LABEL[step.skip_cause]}</dd>
        </>
      )}
      {step?.reason && (
        <>
          <dt className="ah-subtle">Reason</dt>
          <dd style={{ margin: 0 }} className="ah-mono">
            {step.reason}
          </dd>
        </>
      )}
      <dt className="ah-subtle">Sessions</dt>
      <dd style={{ margin: 0 }} className="ah-row ah-wrap">
        {step?.session_ids.length
          ? step.session_ids.map((sid) => (
              <AppLink
                key={sid}
                href={`/sessions/${sid}`}
                className="ah-mono"
                style={{ marginRight: 6 }}
              >
                {shortRunId(sid)}
              </AppLink>
            ))
          : "—"}
      </dd>
      {node.body.length > 0 && (
        <>
          <dt className="ah-subtle">Body steps</dt>
          <dd style={{ margin: 0 }}>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {node.body.map((body) => (
                <li key={body.key}>
                  <span className="ah-mono">{body.key}</span> ·{" "}
                  {nodeSummary({ ...node, id: body.key, step: body, body: [] })}
                </li>
              ))}
            </ul>
          </dd>
        </>
      )}
      <dt className="ah-subtle">Output</dt>
      <dd style={{ margin: 0 }} className="ah-subtle">
        Not in run events: the run record under .agent-runs/ holds it.
      </dd>
    </dl>
  );
}

/** An engine run's graph (plan 6.4): the declared nodes with the run's state on each. */
export function RunGraph({ run, now }: { run: WorkflowRun; now: number }) {
  const [params, setParams] = useSearchParams();
  const workflow = useWorkflow(run.project, run.workflow);
  if (workflow.isPending) return <Skeleton height={160} />;
  const layers = runLayers(run, workflow.isSuccess ? workflow.data.layers : null);
  const nodes = layers.flat();
  const selected = nodes.find((node) => node.id === params.get("node")) ?? null;
  const select = (id: string | null) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (id === null) next.delete("node");
        else next.set("node", id);
        return next;
      },
      { replace: true },
    );
  };
  const revision = workflow.data?.revision;
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <span className="ah-overline">Graph</span>
      {workflow.isError && (
        <Banner tone="warning" boxed>
          The workflow {run.workflow} could not be read; its nodes are shown in start order.
        </Banner>
      )}
      {revision !== undefined && run.revision != null && run.revision !== revision && (
        <Banner tone="info" boxed>
          This run used r{run.revision}; the graph shows the current r{revision}.
        </Banner>
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
          label="Run graph"
          layers={layers}
          selected={selected?.id ?? null}
          onSelect={select}
          state={nodeState}
          detail={nodeSummary}
        />
        {selected && (
          <NodePanel
            id={selected.id}
            onClose={() => {
              select(null);
            }}
          >
            <NodeFacts node={selected} now={now} />
          </NodePanel>
        )}
      </div>
    </div>
  );
}
