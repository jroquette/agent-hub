import { useEffect, useId, useRef, useState } from "react";

import { Button } from "../../components";
import type { ApiProblem } from "../../lib/api";

/** The longest rejection reason the API takes (RejectLearningBody, AC-201.24). */
export const MAX_REASON_CHARS = 300;

export type DecideAction = "accept" | "reject";

export interface DecideDialogProps {
  action: DecideAction;
  /** The learning's title, named in the dialog. */
  title: string;
  /** The hub's repository the pull request opens in; `null` while unknown. */
  hubRepo: string | null;
  /** The inbox note the pull request moves (hub-relative). */
  notePath: string | null;
  /** Where an accept moves the note, relative to `brain/`. */
  target: string;
  /** Whether an accept writes the note as edited here. */
  edited?: boolean | undefined;
  pending: boolean;
  error: ApiProblem | null;
  /** Called with the trimmed reason (empty for an accept). */
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

const HEADING: Record<DecideAction, string> = {
  accept: "Accept this learning?",
  reject: "Reject this learning?",
};

function repoName(hubRepo: string | null): string {
  return hubRepo ?? "the hub's repository";
}

/** What to do next after a failed action, by status (409 conflict, 502 gh/git, 504 deadline). */
function nextStep(error: ApiProblem, hubRepo: string | null): string | null {
  switch (error.status) {
    case 409:
      return "Nothing was pushed.";
    case 502:
      return "Nothing was changed. Try again.";
    case 504:
      return `Check the pull requests of ${repoName(hubRepo)} before trying again.`;
    default:
      return null;
  }
}

function ActionError({ error, hubRepo }: { error: ApiProblem; hubRepo: string | null }) {
  const step = nextStep(error, hubRepo);
  const title = error.status === 409 ? "Could not open the pull request" : error.title;
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

const FOCUSABLE =
  "button:not([disabled]), textarea:not([disabled]), input:not([disabled]), a[href]";

/**
 * Confirms an accept or a reject (AC-201.29): both open a pull request in the hub and change nothing
 * in the brain until it is merged. A reject needs a reason of 1 to 300 characters.
 */
export function DecideDialog({
  action,
  title,
  hubRepo,
  notePath,
  target,
  edited = false,
  pending,
  error,
  onConfirm,
  onCancel,
}: DecideDialogProps) {
  const [reason, setReason] = useState("");
  const titleId = useId();
  const textId = useId();
  const reasonId = useId();
  const counterId = useId();
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const before = document.activeElement;
    // A reject starts at its reason; an accept at its confirm button (the last control).
    const items = dialog.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [];
    (dialog.current?.querySelector("textarea") ?? items[items.length - 1])?.focus();
    return () => {
      if (before instanceof HTMLElement) before.focus();
    };
  }, []);

  const trimmed = reason.trim();
  const ready = !pending && (action === "accept" || trimmed.length > 0);

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
      if (!head || !tail) return;
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
        aria-labelledby={titleId}
        aria-describedby={textId}
        aria-busy={pending}
      >
        <div className="ah-dialog-body ah-stack" style={{ gap: 10 }}>
          <h2 id={titleId} className="ah-h3">
            {HEADING[action]}
          </h2>
          <p className="ah-muted" style={{ margin: 0 }}>
            “{title}”
          </p>
          <p id={textId} style={{ margin: 0 }}>
            This opens a pull request in {repoName(hubRepo)}. Nothing changes in the brain until you
            merge it.
          </p>
          <ul className="ah-consequences">
            {action === "accept" ? (
              <>
                <li>
                  Moves <span className="ah-mono">{notePath ?? "the inbox note"}</span> to{" "}
                  <span className="ah-mono">brain/{target}</span>
                </li>
                {edited && <li>Writes the note as you edited it, in the same commit</li>}
              </>
            ) : (
              <li>
                Archives <span className="ah-mono">{notePath ?? "the inbox note"}</span> with your
                reason
              </li>
            )}
          </ul>
          {action === "reject" && (
            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={reasonId} className="ah-small">
                Reason (required)
              </label>
              <textarea
                id={reasonId}
                className="ah-input"
                rows={3}
                maxLength={MAX_REASON_CHARS}
                value={reason}
                disabled={pending}
                aria-describedby={counterId}
                onChange={(event) => {
                  setReason(event.target.value);
                }}
              />
              <span id={counterId} className="ah-small ah-subtle ah-num">
                {reason.length} / {MAX_REASON_CHARS}
              </span>
            </div>
          )}
          {pending && (
            <span role="status" className="ah-small">
              Opening the pull request in {repoName(hubRepo)}… This can take up to a minute.
            </span>
          )}
          {error && !pending && <ActionError error={error} hubRepo={hubRepo} />}
        </div>
        <div className="ah-dialog-foot">
          <Button disabled={pending} onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant={action === "accept" ? "primary" : "danger"}
            disabled={!ready}
            onClick={() => {
              onConfirm(trimmed);
            }}
          >
            {pending ? "Opening pull request…" : "Open pull request"}
          </Button>
        </div>
      </div>
    </div>
  );
}
