import { Icon, Time } from "../../components";
import { useApi } from "../../lib/api";
import { GateDecision } from "../approvals/GateDecision";
import type { Approval } from "../approvals/queries";
import type { WorkflowRun } from "../runs-list/queries";

/* A running engine run's open gates (AC-213.18): the Approvals decision card for each gate a
 * person answers, so a waiting node is decided where the run is watched. */

/** The node of a gate id `<run>:<node>:<attempt>`. */
export function gateNode(gateId: string): string {
  return gateId.split(":")[1] ?? gateId;
}

/** The run's open gates a person answers, while it runs (one query, shared by its readers). */
export function useOpenGates(run: WorkflowRun): Approval[] {
  const running = run.status === "running";
  const open = useApi(
    "/api/v1/approvals",
    { query: { project: run.project, kind: "human_gate", status: "open", limit: 200 } },
    { enabled: running },
  );
  if (!running) return [];
  return (open.data?.items ?? []).filter((item) => item.session_id === `run:${run.id}`);
}

/** The open gate of a graph node: its own, or one in its loop_group body (`<node>__…`). */
export function gateOf(gates: readonly Approval[], nodeId: string): Approval | undefined {
  return gates.find((gate) => {
    const node = gateNode(gate.gate_id);
    return node === nodeId || node.startsWith(`${nodeId}__`);
  });
}

export function OpenGates({ run }: { run: WorkflowRun }) {
  const gates = useOpenGates(run);
  if (gates.length === 0) return null;
  return (
    <section
      aria-label="Waiting for you"
      className="ah-card ah-stack"
      style={{ gap: 12, padding: 16 }}
    >
      <div className="ah-row" style={{ gap: 6 }}>
        <Icon name="stamp" size="sm" style={{ color: "var(--waiting)" }} />
        <span className="ah-overline">Waiting for you</span>
      </div>
      {gates.map((gate) => (
        <div key={gate.id} className="ah-stack" style={{ gap: 6 }}>
          <span className="ah-small">
            <span className="ah-mono">{gateNode(gate.gate_id)}</span> waits for a decision since{" "}
            <Time iso={gate.requested_at} />
          </span>
          <GateDecision approvalId={gate.id} />
        </div>
      ))}
    </section>
  );
}
