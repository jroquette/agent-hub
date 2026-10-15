import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";

import type { components } from "../../api/schema";
import { Button, type IconName } from "../../components";
import { apiCommand, apiKey, type ApiProblem } from "../../lib/api";
import { useModalFocus } from "../../lib/modalFocus";
import type { WorkflowRun } from "../runs-list/queries";

/* Cancel, resume and abandon an engine run from Run detail (AC-213.19, plan 10.3), each after a
 * confirmation. The server decides what a run allows; its answer and events tell the rest. */

type RunAccepted = components["schemas"]["RunAccepted"];
type Action = "cancel" | "resume" | "abandon";

const COMMAND: Record<
  Action,
  {
    label: string;
    icon: IconName;
    variant: "default" | "danger";
    heading: string;
    text: string;
    done: string;
  }
> = {
  cancel: {
    label: "Cancel",
    icon: "square",
    variant: "danger",
    heading: "Cancel this run?",
    text: "Stops the run's child with SIGINT (SIGKILL after 10 s if it does not stop), then ends the run cancelled. Only a run hub web started can be cancelled here.",
    done: "Cancel sent. The run ends cancelled once its child stops.",
  },
  resume: {
    label: "Resume",
    icon: "rotate-ccw",
    variant: "default",
    heading: "Resume this run?",
    text: "Continues the run in a new child on this machine, reusing what completed. A gate still waiting pauses it again.",
    done: "Resume sent. The run resumes; its events update this page.",
  },
  abandon: {
    label: "Abandon",
    icon: "x",
    variant: "danger",
    heading: "Abandon this run?",
    text: "Ends the run cancelled without running anything more. It cannot be resumed afterwards.",
    done: "The run is abandoned: it ended cancelled.",
  },
};

/** What the run allows from the web: an engine run that has not ended done or cancelled. */
export function runActions(run: WorkflowRun): Action[] {
  if (!run.content_hash || run.workflow === "issue-to-pr") return [];
  if (run.status === "running") return ["cancel", "resume", "abandon"];
  if (run.status === "failed") return ["resume", "abandon"];
  return [];
}

function useRunCommand(runId: string) {
  const client = useQueryClient();
  const path = { path: { run_id: runId } };
  return useMutation<RunAccepted, ApiProblem, Action>({
    mutationFn: (action) => {
      switch (action) {
        case "cancel":
          return apiCommand("/api/v1/workflow-runs/{run_id}/cancel", path);
        case "resume":
          return apiCommand("/api/v1/workflow-runs/{run_id}/resume", path);
        case "abandon":
          return apiCommand("/api/v1/workflow-runs/{run_id}/abandon", path);
      }
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/workflow-runs/{run_id}", path) });
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/workflow-runs") });
      // A cancel or abandon closes the run's open gates.
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/approvals") });
    },
  });
}

function ConfirmDialog({
  action,
  pending,
  error,
  onConfirm,
  onClose,
}: {
  action: Action;
  pending: boolean;
  error: ApiProblem | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const look = COMMAND[action];
  const dialog = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const textId = useId();
  useModalFocus(dialog, { locked: pending, onEscape: onClose });
  return (
    <div className="ah-scrim">
      <div
        ref={dialog}
        className="ah-dialog"
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-labelledby={titleId}
        aria-describedby={textId}
        aria-busy={pending}
      >
        <div className="ah-dialog-body ah-stack" style={{ gap: 10 }}>
          <h2 id={titleId} className="ah-h3">
            {look.heading}
          </h2>
          <p id={textId} style={{ margin: 0 }}>
            {look.text}
          </p>
          {pending && (
            <span role="status" className="ah-small">
              Sending…
            </span>
          )}
          {error && !pending && (
            <div
              role="alert"
              className="ah-stack"
              style={{
                gap: 2,
                border: "1px solid var(--failed)",
                borderLeft: "3px solid var(--failed)",
                borderRadius: "var(--radius-md)",
                padding: "8px 12px",
              }}
            >
              <b style={{ fontWeight: 600 }}>Could not {action} the run</b>
              <span className="ah-small">{error.detail ?? error.title}</span>
            </div>
          )}
        </div>
        <div className="ah-dialog-foot">
          <Button disabled={pending} onClick={onClose}>
            Keep run
          </Button>
          <Button variant={look.variant} disabled={pending} onClick={onConfirm}>
            {`${look.label} run`}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Run detail's Cancel, Resume and Abandon buttons, for what the run allows. */
export function RunCommands({ run }: { run: WorkflowRun }) {
  const command = useRunCommand(run.id);
  const [asking, setAsking] = useState<Action | null>(null);
  const actions = runActions(run);
  if (actions.length === 0 && !command.isSuccess) return null;
  return (
    <>
      {actions.length > 0 && (
        <div role="group" aria-label="Run commands" className="ah-row" style={{ gap: 8 }}>
          {actions.map((action) => (
            <Button
              key={action}
              variant={COMMAND[action].variant}
              icon={COMMAND[action].icon}
              disabled={command.isPending}
              onClick={() => {
                command.reset();
                setAsking(action);
              }}
            >
              {COMMAND[action].label}
            </Button>
          ))}
        </div>
      )}
      {command.isSuccess && (
        <span role="status" className="ah-small">
          {COMMAND[command.variables].done}
        </span>
      )}
      {asking && (
        <ConfirmDialog
          action={asking}
          pending={command.isPending}
          error={command.isError ? command.error : null}
          onConfirm={() => {
            command.mutate(asking, {
              onSuccess: () => {
                setAsking(null);
              },
            });
          }}
          onClose={() => {
            setAsking(null);
          }}
        />
      )}
    </>
  );
}
