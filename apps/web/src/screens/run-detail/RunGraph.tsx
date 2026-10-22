import { useMemo } from "react";

import { AppLink, Banner, Icon, Skeleton, StatusBadge, Time } from "../../components";
import { fmtDuration } from "../../lib/format";
import {
  durationSeconds,
  FAILURE_KIND_LABEL,
  SKIP_CAUSE_LABEL,
  shortRunId,
} from "../runs-list/model";
import type { WorkflowRun } from "../runs-list/queries";
import { NodePanel, useNodeParam, WorkflowGraph } from "../workflows/WorkflowGraph";
import { useWorkflow } from "../workflows/queries";
import { GateDecision } from "../approvals/GateDecision";
import type { Approval } from "../approvals/queries";
import { gateNode, gateOf, useOpenGates } from "./OpenGates";
import { nodeState, nodeSummary, runLayers, STATE_LOOK, type RunNode } from "./graph";

function NodeGate({ gate }: { gate: Approval }) {
  return (
    <div className="ah-stack" style={{ gap: 6, marginBottom: 12 }}>
      <span className="ah-small">
        Waiting for a decision at <span className="ah-mono">{gateNode(gate.gate_id)}</span>
      </span>
      <GateDecision approvalId={gate.id} />
    </div>
  );
}

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

/** How to read the run graph: the states, and what an arrow means. */
function RunLegend() {
  return (
    <details className="ah-flow-legend">
      <summary>
        <Icon name="info" size="sm" />
        How to read
      </summary>
      <div className="ah-flow-legend-body" aria-label="Legend">
        {(["running", "failed", "ok", "skipped", "pending"] as const).map((state) => (
          <span key={state}>
            <StatusBadge status={STATE_LOOK[state].status} label={STATE_LOOK[state].label} quiet />
          </span>
        ))}
        <span>
          <StatusBadge status="waiting" label="Waiting for a decision" quiet />
        </span>
        <span>Arrows point to the step that waits.</span>
        <span>Drag to move · ⌘ or Ctrl + scroll to zoom · Shift + scroll moves sideways.</span>
      </div>
    </details>
  );
}

/** An engine run's graph (plan 6.4): the declared nodes with the run's state on each. */
export function RunGraph({ run, now }: { run: WorkflowRun; now: number }) {
  const node = useNodeParam();
  const workflow = useWorkflow(run.project, run.workflow);
  const gates = useOpenGates(run);
  const declared = workflow.isSuccess ? workflow.data.layers : null;
  // The clock re-renders a live run each second; the layers change only with its steps.
  const layers = useMemo(() => runLayers(run, declared), [run, declared]);
  // Every node by id, a group's own steps (`<group>__<id>`) too, for their states.
  const byId = useMemo(() => {
    const map = new Map<string, RunNode>();
    for (const n of layers.flat()) {
      map.set(n.id, n);
      for (const body of n.body) {
        map.set(body.key, {
          id: body.key,
          type: body.kind ?? "step",
          depends_on: [],
          step: body,
          body: [],
        });
      }
    }
    return map;
  }, [layers]);
  const stateOf = (id: string): string | undefined => {
    const n = byId.get(id);
    if (gateOf(gates, id)) return "waiting";
    return n ? nodeState(n) : "pending";
  };
  const firstToSee = useMemo(() => {
    const all = [...byId.values()];
    return (
      all.find((n) => gateOf(gates, n.id)) ??
      all.find((n) => nodeState(n) === "failed") ??
      all.find((n) => nodeState(n) === "running")
    )?.id;
    // The first view is placed once: the gates at load are enough.
  }, [byId, gates]);
  if (workflow.isPending) return <Skeleton height={420} />;
  const selected = node.nodeId ? (byId.get(node.nodeId) ?? null) : null;
  const selectedGate = selected ? gateOf(gates, selected.id) : undefined;
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
      <WorkflowGraph
        label="Run graph"
        className="wf-canvas-run"
        wheel="page"
        layers={layers}
        document={workflow.data?.document}
        selected={selected?.id ?? null}
        onSelect={node.open}
        onClose={node.close}
        focusFirst={firstToSee ?? null}
        state={stateOf}
        overlay={<RunLegend />}
        detail={(id) => {
          if (gateOf(gates, id)) {
            return <StatusBadge status="waiting" label="Waiting for a decision" quiet />;
          }
          const n = byId.get(id);
          const look = STATE_LOOK[n ? nodeState(n) : "pending"];
          return <StatusBadge status={look.status} label={n ? nodeSummary(n) : look.label} quiet />;
        }}
        panel={
          selected ? (
            <NodePanel id={selected.id} focusOnOpen={node.openedByUser} onClose={node.close}>
              {selectedGate && <NodeGate gate={selectedGate} />}
              <NodeFacts node={selected} now={now} />
            </NodePanel>
          ) : undefined
        }
      />
    </div>
  );
}
