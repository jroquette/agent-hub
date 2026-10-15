import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { useNavigate } from "react-router";

import type { components } from "../../api/schema";
import { Button } from "../../components";
import { apiKey, apiPost, type ApiProblem } from "../../lib/api";
import { useModalFocus } from "../../lib/modalFocus";
import { useWorkflow, useWorkflows } from "../workflows/queries";

/* Start a workflow run from hub web (AC-213.19, plan 10.3): a workflow picker and a form built
 * from its `inputs:`. A web start is always live (decision of 2026-10-15); a dry run belongs to
 * the CLI. issue-to-pr writes to the tracker and starts from `hub run`. */

type StartRunRequest = components["schemas"]["StartRunRequest"];
type RunAccepted = components["schemas"]["RunAccepted"];
type InputValue = string | number | boolean;

/** Workflows the web cannot start: their tracker writes need the parent `hub run`. */
const TRACKER_WORKFLOWS = new Set(["issue-to-pr"]);
/** The longest text input the API takes (one argv element). */
export const MAX_INPUT_CHARS = 16_384;

interface InputSpec {
  name: string;
  type: "string" | "integer" | "number" | "boolean";
  required: boolean;
  default: unknown;
  description: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The declared inputs, as the workflow document writes them (keys left out take defaults). */
export function inputSpecs(document: unknown): InputSpec[] {
  const declared = isRecord(document) ? document.inputs : undefined;
  if (!isRecord(declared)) return [];
  return Object.entries(declared).map(([name, raw]) => {
    const spec = isRecord(raw) ? raw : {};
    const type = spec.type;
    return {
      name,
      type: type === "integer" || type === "number" || type === "boolean" ? type : "string",
      required: spec.required === true,
      default: spec.default,
      description: typeof spec.description === "string" ? spec.description : null,
    };
  });
}

function initialValue(spec: InputSpec): string | boolean {
  if (spec.type === "boolean") return spec.default === true;
  const value = spec.default;
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

/** The value sent for one input, or a problem; `undefined` leaves an optional input out. */
function parsed(spec: InputSpec, raw: string | boolean): InputValue | undefined | Error {
  if (spec.type === "boolean") return raw === true;
  const text = String(raw);
  if (text.trim() === "") {
    return spec.required ? new Error(`${spec.name} is required.`) : undefined;
  }
  if (spec.type === "string") return text;
  const number = Number(text);
  if (!Number.isFinite(number)) return new Error(`${spec.name} must be a number.`);
  if (spec.type === "integer" && !Number.isInteger(number)) {
    return new Error(`${spec.name} must be a whole number.`);
  }
  return number;
}

function useStartRun() {
  const client = useQueryClient();
  return useMutation<RunAccepted, ApiProblem, StartRunRequest>({
    mutationFn: (body) => apiPost("/api/v1/workflow-runs", body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/workflow-runs") });
    },
  });
}

function InputField({
  spec,
  value,
  error,
  onChange,
}: {
  spec: InputSpec;
  value: string | boolean;
  error: string | null;
  onChange: (value: string | boolean) => void;
}) {
  const field = useId();
  const hint = useId();
  const problem = useId();
  const described = [spec.description ? hint : null, error ? problem : null]
    .filter(Boolean)
    .join(" ");
  const label = `${spec.name}${spec.required ? " (required)" : ""}`;
  return (
    <div className="ah-stack" style={{ gap: 4 }}>
      {spec.type === "boolean" ? (
        <label htmlFor={field} className="ah-row ah-small" style={{ gap: 6 }}>
          <input
            id={field}
            type="checkbox"
            checked={value === true}
            aria-describedby={described || undefined}
            onChange={(event) => {
              onChange(event.target.checked);
            }}
          />
          {label}
        </label>
      ) : (
        <>
          <label htmlFor={field} className="ah-small">
            {label}
          </label>
          <input
            id={field}
            className="ah-input"
            type={spec.type === "string" ? "text" : "number"}
            step={spec.type === "integer" ? 1 : "any"}
            maxLength={spec.type === "string" ? MAX_INPUT_CHARS : undefined}
            value={String(value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={described || undefined}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          />
        </>
      )}
      {spec.description && (
        <span id={hint} className="ah-small ah-subtle">
          {spec.description}
        </span>
      )}
      {error && (
        <span id={problem} className="ah-small" style={{ color: "var(--failed)" }}>
          {error}
        </span>
      )}
    </div>
  );
}

function StartRunDialog({ scope, onClose }: { scope: string | null; onClose: () => void }) {
  const catalog = useWorkflows(scope);
  const start = useStartRun();
  const navigate = useNavigate();
  const [chosen, setChosen] = useState("");
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const dialog = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const pickerId = useId();
  useModalFocus(dialog, { locked: start.isPending, onEscape: onClose });

  const startable = (catalog.data?.items ?? []).filter((w) => !TRACKER_WORKFLOWS.has(w.name));
  const [project = "", name = ""] = chosen ? chosen.split("/") : [];
  const detail = useWorkflow(project, name, chosen !== "");
  const specs = detail.isSuccess ? inputSpecs(detail.data.document) : [];
  const valueOf = (spec: InputSpec) => values[spec.name] ?? initialValue(spec);
  const results = specs.map((spec) => [spec, parsed(spec, valueOf(spec))] as const);
  const invalid = results.some(([, result]) => result instanceof Error);
  const ready = chosen !== "" && detail.isSuccess && !invalid && !start.isPending;

  const submit = () => {
    const inputs: Record<string, InputValue> = {};
    for (const [spec, result] of results) {
      if (result !== undefined && !(result instanceof Error)) inputs[spec.name] = result;
    }
    start.mutate(
      { project, workflow: name, inputs },
      {
        onSuccess: (accepted) => {
          onClose();
          void navigate(`/runs/${encodeURIComponent(accepted.run_id)}`);
        },
      },
    );
  };

  return (
    <div className="ah-scrim">
      <div
        ref={dialog}
        className="ah-dialog"
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-labelledby={titleId}
        aria-busy={start.isPending}
      >
        <div className="ah-dialog-body ah-stack" style={{ gap: 12 }}>
          <h2 id={titleId} className="ah-h3">
            Start a workflow run
          </h2>
          <p className="ah-small" style={{ margin: 0 }}>
            Runs live on this machine: its commands and agents run in the hub, as{" "}
            <code className="ah-mono">hub workflow run --live</code> does. A dry run belongs to the
            CLI; issue-to-pr starts from hub run.
          </p>
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={pickerId} className="ah-small">
              Workflow
            </label>
            <select
              id={pickerId}
              className="ah-input"
              value={chosen}
              disabled={start.isPending}
              onChange={(event) => {
                setChosen(event.target.value);
                setValues({});
                setTouched({});
                start.reset();
              }}
            >
              <option value="">Choose a workflow…</option>
              {startable.map((w) => (
                <option key={`${w.project}/${w.name}`} value={`${w.project}/${w.name}`}>
                  {`${w.project} / ${w.name}`}
                </option>
              ))}
            </select>
            {catalog.isSuccess && startable.length === 0 && (
              <span className="ah-small ah-muted">No workflow here can start from the web.</span>
            )}
            {catalog.isError && (
              <span className="ah-small" style={{ color: "var(--failed)" }}>
                Could not list the workflows: {catalog.error.detail ?? catalog.error.title}
              </span>
            )}
          </div>
          {detail.isError && (
            <span className="ah-small" style={{ color: "var(--failed)" }}>
              Could not read the workflow: {detail.error.detail ?? detail.error.title}
            </span>
          )}
          {results.map(([spec, result]) => (
            <InputField
              key={spec.name}
              spec={spec}
              value={valueOf(spec)}
              error={
                result instanceof Error && (touched[spec.name] || !spec.required)
                  ? result.message
                  : null
              }
              onChange={(value) => {
                setValues((current) => ({ ...current, [spec.name]: value }));
                setTouched((current) => ({ ...current, [spec.name]: true }));
              }}
            />
          ))}
          {start.isPending && (
            <span role="status" className="ah-small">
              Starting the run…
            </span>
          )}
          {start.isError && (
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
              <b style={{ fontWeight: 600 }}>Could not start the run</b>
              <span className="ah-small">{start.error.detail ?? start.error.title}</span>
            </div>
          )}
        </div>
        <div className="ah-dialog-foot">
          <Button disabled={start.isPending} onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" icon="play" disabled={!ready} onClick={submit}>
            Start run
          </Button>
        </div>
      </div>
    </div>
  );
}

/** The runs list's "Start run" button and its dialog. */
export function StartRun({ project }: { project: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="primary"
        icon="play"
        onClick={() => {
          setOpen(true);
        }}
      >
        Start run
      </Button>
      {open && (
        <StartRunDialog
          scope={project}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}
