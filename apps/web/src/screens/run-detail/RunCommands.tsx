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
export type Action = "cancel" | "resume" | "abandon";

interface CommandLook {
  label: string;
  icon: IconName;
  variant: "default" | "danger";
  heading: string;
  text: string;
  done: string;
}

/** Each command's words for `noun` ("run", or "scenario run": the glossary never says "run" alone
 * for one). */
function commandLook(action: Action, noun: string): CommandLook {
  switch (action) {
    case "cancel":
      return {
        label: "Cancel",
        icon: "square",
        variant: "danger",
        heading: `Cancel this ${noun}?`,
        text: `Stops the ${noun}'s child with SIGINT (SIGKILL after 10 s if it does not stop), then ends the ${noun} cancelled. Only a ${noun} hub web started can be cancelled here.`,
        done: `Cancel sent. The ${noun} ends cancelled once its child stops.`,
      };
    case "resume":
      return {
        label: "Resume",
        icon: "rotate-ccw",
        variant: "default",
        heading: `Resume this ${noun}?`,
        text: `Continues the ${noun} in a new child on this machine, reusing what completed. A gate still waiting pauses it again.`,
        done: `Resume sent. The ${noun} resumes; its events update this page.`,
      };
    case "abandon":
      return {
        label: "Abandon",
        icon: "x",
        variant: "danger",
        heading: `Abandon this ${noun}?`,
        text: `Ends the ${noun} cancelled without running anything more. It cannot be resumed afterwards.`,
        done: `The ${noun} is abandoned: it ended cancelled.`,
      };
  }
}

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
  noun,
  pending,
  error,
  onConfirm,
  onClose,
}: {
  action: Action;
  noun: string;
  pending: boolean;
  error: ApiProblem | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const look = commandLook(action, noun);
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
              <b style={{ fontWeight: 600 }}>
                Could not {action} the {noun}
              </b>
              <span className="ah-small">{error.detail ?? error.title}</span>
            </div>
          )}
        </div>
        <div className="ah-dialog-foot">
          <Button disabled={pending} onClick={onClose}>
            {`Keep ${noun}`}
          </Button>
          <Button variant={look.variant} disabled={pending} onClick={onConfirm}>
            {`${look.label} ${noun}`}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Run detail's Cancel, Resume and Abandon buttons, for what the run allows. `noun` names the run
 * ("scenario run" on a scenario run's page, whose buttons then name it too); `only` keeps those
 * commands alone (a scenario run offers Cancel only, E-15). */
export function RunCommands({
  run,
  noun = "run",
  only,
}: {
  run: WorkflowRun;
  noun?: string;
  only?: readonly Action[];
}) {
  const command = useRunCommand(run.id);
  const [asking, setAsking] = useState<Action | null>(null);
  const actions = runActions(run).filter((action) => only === undefined || only.includes(action));
  // A run's buttons say the verb alone; another noun is named on the button too.
  const buttonLabel = (action: Action) =>
    noun === "run" ? commandLook(action, noun).label : `${commandLook(action, noun).label} ${noun}`;
  if (actions.length === 0 && !command.isSuccess) return null;
  return (
    <>
      {actions.length > 0 && (
        <div role="group" aria-label="Run commands" className="ah-row" style={{ gap: 8 }}>
          {actions.map((action) => (
            <Button
              key={action}
              variant={commandLook(action, noun).variant}
              icon={commandLook(action, noun).icon}
              disabled={command.isPending}
              onClick={() => {
                command.reset();
                setAsking(action);
              }}
            >
              {buttonLabel(action)}
            </Button>
          ))}
        </div>
      )}
      {command.isSuccess && (
        <span role="status" className="ah-small">
          {commandLook(command.variables, noun).done}
        </span>
      )}
      {asking && (
        <ConfirmDialog
          action={asking}
          noun={noun}
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
