import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import type { components } from "../../api/schema";
import { Button, Icon, ProblemError } from "../../components";
import { ApiProblem, apiKey, apiPost } from "../../lib/api";

type AcRow = components["schemas"]["AcRow"];
type EvalRecord = components["schemas"]["EvalRecord"];

/**
 * The owner checked a criterion by hand (a manual test, a look at the screen) and says it passes:
 * the server writes an owner sign-off eval (SHIP) over this AC only, and its row reads "Signed off".
 * features.json is left as the agents wrote it. Once signed off, the card says so instead.
 */
export function MarkAcPassing({ ac, project, slug }: { ac: AcRow; project: string; slug: string }) {
  const client = useQueryClient();
  const formId = useId();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const path = { path: { project, slug } };
  const mark = useMutation<EvalRecord, ApiProblem>({
    mutationFn: () =>
      apiPost(
        "/api/v1/features/{project}/{slug}/owner-signoff",
        { acs: [ac.id], decision: "done", note: note.trim() || null },
        path,
      ),
    onSuccess: () => {
      setOpen(false);
      setNote("");
      for (const key of [
        apiKey("/api/v1/features"),
        apiKey("/api/v1/features/{project}/{slug}", path),
        apiKey("/api/v1/features/{project}/{slug}/tickets", path),
      ]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });

  if (ac.signed_off) {
    return (
      <div className="ah-ac-note" style={{ color: "var(--done)" }}>
        <Icon name="circle-check" size="sm" />
        You checked this by hand and signed it off; it counts as passing.
      </div>
    );
  }
  if (ac.passes) return null;
  if (!open) {
    return (
      <div className="ah-row" style={{ gap: 8 }}>
        <Button
          size="sm"
          icon="check"
          onClick={() => {
            setOpen(true);
          }}
        >
          I checked it, mark as passing
        </Button>
        <span className="ah-small ah-muted">
          For a check you did by hand. Writes an owner sign-off eval for {ac.id}.
        </span>
      </div>
    );
  }
  return (
    <form
      id={formId}
      className="ah-eval-decision ah-stack"
      aria-label={`Mark ${ac.id} as passing`}
      onSubmit={(event) => {
        event.preventDefault();
        mark.mutate();
      }}
    >
      <span className="ah-stack" style={{ gap: 2 }}>
        <b>Mark {ac.id} as passing</b>
        <span className="ah-small ah-muted">
          Writes an owner sign-off eval (SHIP) over {ac.id}, signed by you. features.json and the
          existing evals are kept.
        </span>
      </span>
      <label className="ah-stack ah-small" style={{ gap: 4 }}>
        <span>Note (optional)</span>
        <textarea
          className="ah-input ah-eval-note"
          rows={2}
          maxLength={2000}
          value={note}
          placeholder="What you checked, and where"
          onChange={(event) => {
            setNote(event.target.value);
          }}
        />
      </label>
      {mark.error && (
        <ProblemError
          compact
          title={`Could not mark ${ac.id} as passing`}
          detail={mark.error.detail ?? mark.error.title}
          status={mark.error.status || undefined}
        />
      )}
      <span className="ah-row" style={{ gap: 8 }}>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setOpen(false);
          }}
        >
          Cancel
        </Button>
        <Button size="sm" variant="primary" type="submit" icon="check" disabled={mark.isPending}>
          {mark.isPending ? "Saving…" : "Mark as passing"}
        </Button>
      </span>
    </form>
  );
}
