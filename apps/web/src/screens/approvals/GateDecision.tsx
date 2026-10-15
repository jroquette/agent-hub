import { useEffect, useId, useRef, useState } from "react";

import { Button, Skeleton, type IconName } from "../../components";
import type { ApiProblem } from "../../lib/api";
import { useDecideGate, useWorkflowGate, type WorkflowGate } from "./queries";

/* A workflow gate decided from hub web (AC-213.18): one button per declared decision or option
 * (or Respond for a wait that takes text only), a dialog for the text when the gate takes one,
 * then the run resumes on the server. Nothing here tracks the run: its events do. */

/** At most 4 bytes a character, so a text this long fits the API's 65,536 UTF-8 bytes. */
export const MAX_TEXT_CHARS = 16_384;

interface Choice {
  id: string | null;
  label: string;
}

const LOOK: Record<string, { variant: "primary" | "danger"; icon: IconName }> = {
  approve: { variant: "primary", icon: "check" },
  reject: { variant: "danger", icon: "x" },
};

function choicesOf(gate: WorkflowGate): Choice[] {
  if (gate.form === "text") return [{ id: null, label: "Respond" }];
  return gate.choices.map((choice) => ({ id: choice.id, label: choice.label }));
}

/** A refused answer changed nothing; a failed resume or an unknown outcome may have. */
function nextStep(error: ApiProblem): string | null {
  if (error.status === 409 || error.status === 422) return "Nothing was recorded.";
  return null;
}

function DecisionError({ error }: { error: ApiProblem }) {
  const step = nextStep(error);
  const title = error.status === 502 ? error.title : "Could not record the decision";
  return (
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
      <b style={{ fontWeight: 600 }}>{title}</b>
      {error.detail && <span className="ah-small">{error.detail}</span>}
      {step && <span className="ah-small ah-muted">{step}</span>}
    </div>
  );
}

const FOCUSABLE = "button:not([disabled]), textarea:not([disabled])";

interface TextDialogProps {
  choice: Choice;
  required: boolean;
  pending: boolean;
  error: ApiProblem | null;
  onConfirm: (text: string) => void;
  onCancel: () => void;
}

/** Asks for the gate's text: a reason (optional) or a response (required). */
function TextDialog({ choice, required, pending, error, onConfirm, onCancel }: TextDialogProps) {
  const [text, setText] = useState("");
  const titleId = useId();
  const fieldId = useId();
  const counterId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const trimmed = text.trim();
  const ready = !pending && (!required || trimmed.length > 0);
  const heading = choice.id === null ? "Respond to this gate?" : `${choice.label}?`;
  const label = required ? "Response (required)" : "Reason (optional)";

  useEffect(() => {
    const before = document.activeElement;
    dialog.current?.querySelector("textarea")?.focus();
    return () => {
      if (before instanceof HTMLElement) before.focus();
    };
  }, []);

  // Escape cancels (not while the request runs) and Tab cycles inside the dialog.
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        if (!pending) onCancel();
        return;
      }
      if (event.key !== "Tab") return;
      const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)];
      const head = items[0];
      const tail = items[items.length - 1];
      if (!head || !tail) {
        // Every control is off while the request runs: focus stays on the dialog itself.
        event.preventDefault();
        node.focus();
        return;
      }
      if (event.shiftKey && document.activeElement === head) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && document.activeElement === tail) {
        event.preventDefault();
        head.focus();
      }
    };
    node.addEventListener("keydown", onKeyDown);
    return () => {
      node.removeEventListener("keydown", onKeyDown);
    };
  }, [pending, onCancel]);

  return (
    <div className="ah-scrim">
      <div
        ref={dialog}
        className="ah-dialog"
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-labelledby={titleId}
        aria-busy={pending}
      >
        <div className="ah-dialog-body ah-stack" style={{ gap: 10 }}>
          <h2 id={titleId} className="ah-h3">
            {heading}
          </h2>
          <p style={{ margin: 0 }}>
            The run records your answer and goes on from this gate. The text stays in the run's
            record; it is never sent in an event.
          </p>
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId} className="ah-small">
              {label}
            </label>
            <textarea
              id={fieldId}
              className="ah-input"
              rows={4}
              maxLength={MAX_TEXT_CHARS}
              value={text}
              disabled={pending}
              aria-describedby={counterId}
              onChange={(event) => {
                setText(event.target.value);
              }}
            />
            <span id={counterId} className="ah-small ah-subtle ah-num">
              {text.length} / {MAX_TEXT_CHARS}
            </span>
          </div>
          {pending && (
            <span role="status" className="ah-small">
              Recording the decision and resuming the run…
            </span>
          )}
          {error && !pending && <DecisionError error={error} />}
        </div>
        <div className="ah-dialog-foot">
          <Button disabled={pending} onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant={LOOK[choice.id ?? ""]?.variant ?? "primary"}
            disabled={!ready}
            onClick={() => {
              onConfirm(trimmed);
            }}
          >
            {choice.label}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** The decision card of an open workflow gate, in Approvals and in Run detail. */
export function GateDecision({ approvalId }: { approvalId: string }) {
  const gate = useWorkflowGate(approvalId);
  const decide = useDecideGate(approvalId);
  const [asking, setAsking] = useState<Choice | null>(null);

  if (gate.isPending) return <Skeleton width="60%" height={28} />;
  if (gate.isError) {
    return (
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        This gate cannot be decided here: {gate.error.detail ?? gate.error.title}
      </p>
    );
  }
  const takesText = gate.data.text !== "off";
  const send = (choice: Choice, text: string) => {
    decide.mutate(
      { ...(choice.id === null ? {} : { decision: choice.id }), ...(text ? { text } : {}) },
      {
        onSuccess: () => {
          setAsking(null);
        },
      },
    );
  };

  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <div role="group" aria-label="Decide this gate" className="ah-row" style={{ gap: 8 }}>
        {choicesOf(gate.data).map((choice) => {
          const look = LOOK[choice.id ?? ""];
          return (
            <Button
              key={choice.id ?? "respond"}
              variant={look?.variant ?? "default"}
              icon={look?.icon ?? "message-square"}
              // After a success the choices stay off until the refetched gate closes the card.
              disabled={decide.isPending || decide.isSuccess}
              onClick={() => {
                decide.reset();
                if (takesText) setAsking(choice);
                else send(choice, "");
              }}
            >
              {choice.label}
            </Button>
          );
        })}
      </div>
      {!asking && decide.isPending && (
        <span role="status" className="ah-small">
          Recording the decision and resuming the run…
        </span>
      )}
      {decide.isSuccess && (
        <span role="status" className="ah-small">
          Decision recorded. The run resumes; its events update this page.
        </span>
      )}
      {!asking && decide.isError && <DecisionError error={decide.error} />}
      {asking && (
        <TextDialog
          choice={asking}
          required={gate.data.text === "required"}
          pending={decide.isPending}
          error={decide.isError ? decide.error : null}
          onConfirm={(text) => {
            send(asking, text);
          }}
          onCancel={() => {
            setAsking(null);
          }}
        />
      )}
    </div>
  );
}
