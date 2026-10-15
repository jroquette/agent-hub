import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";

import type { components } from "../../api/schema";
import { AppLink, Button } from "../../components";
import { apiKey, apiPost, useApi, type ApiProblem } from "../../lib/api";
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
/** How often, and how long, the dialog looks for the started run's first event. */
const REPORT_POLL_MS = 1_000;
export const REPORT_WAIT_MS = 30_000;
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

/** The value sent for one input, or a problem; `undefined` leaves an optional input out. A
 * number field the browser could not parse (`badInput`) reads as empty: it is a problem. */
function parsed(
  spec: InputSpec,
  raw: string | boolean,
  bad = false,
): InputValue | undefined | Error {
  if (spec.type === "boolean") return raw === true;
  if (bad) return new Error(`${spec.name} must be a number.`);
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
  if (spec.type === "integer" && !Number.isSafeInteger(number)) {
    return new Error(`${spec.name} must be a whole number up to 2^53.`);
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
  disabled,
  onChange,
}: {
  spec: InputSpec;
  value: string | boolean;
  error: string | null;
  disabled: boolean;
  onChange: (value: string | boolean, bad: boolean) => void;
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
            disabled={disabled}
            aria-describedby={described || undefined}
            onChange={(event) => {
              onChange(event.target.checked, false);
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
            disabled={disabled}
            aria-invalid={error ? true : undefined}
            aria-describedby={described || undefined}
            onChange={(event) => {
              onChange(event.target.value, event.target.validity.badInput);
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

/**
 * The started run, once its child's first event lists it: Run detail only knows a run from its
 * events, so opening it before then would answer 404. Polls the runs list (never the run itself)
 * until it is there, or until REPORT_WAIT_MS passed (`late`).
 */
function useReported(
  started: RunAccepted | null,
  workflow: string,
): { ready: boolean; late: boolean } {
  const [late, setLate] = useState(false);
  const runs = useApi(
    "/api/v1/workflow-runs",
    { query: { project: started?.project ?? null, workflow, limit: 50 } },
    { enabled: started !== null && !late, refetchInterval: REPORT_POLL_MS },
  );
  useEffect(() => {
    if (started === null) return;
    const timer = setTimeout(() => {
      setLate(true);
    }, REPORT_WAIT_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [started]);
  const ready = started !== null && (runs.data?.items ?? []).some((r) => r.id === started.run_id);
  return { ready, late };
}

function StartRunDialog({ scope, onClose }: { scope: string | null; onClose: () => void }) {
  const catalog = useWorkflows(scope);
  const start = useStartRun();
  const navigate = useNavigate();
  const [started, setStarted] = useState<RunAccepted | null>(null);
  const [chosen, setChosen] = useState<{ project: string; name: string } | null>(null);
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [bad, setBad] = useState<Record<string, boolean>>({});
  const dialog = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const pickerId = useId();
  useModalFocus(dialog, { locked: start.isPending, onEscape: onClose });

  const startable = (catalog.data?.items ?? []).filter((w) => !TRACKER_WORKFLOWS.has(w.name));
  const project = chosen?.project ?? "";
  const name = chosen?.name ?? "";
  const picked = chosen ? startable.findIndex((w) => w.project === project && w.name === name) : -1;
  const detail = useWorkflow(project, name, chosen !== null);
  const specs = detail.isSuccess ? inputSpecs(detail.data.document) : [];
  const valueOf = (spec: InputSpec) => values[spec.name] ?? initialValue(spec);
  const results = specs.map(
    (spec) => [spec, parsed(spec, valueOf(spec), bad[spec.name] === true)] as const,
  );
  const invalid = results.some(([, result]) => result instanceof Error);
  const busy = start.isPending || started !== null;
  const ready = chosen !== null && detail.isSuccess && !invalid && !busy;
  const reported = useReported(started, name);
  const runPath = started ? `/runs/${encodeURIComponent(started.run_id)}` : null;

  useEffect(() => {
    if (reported.ready && runPath) {
      onClose();
      void navigate(runPath);
    }
  }, [reported.ready, runPath, onClose, navigate]);

  const submit = () => {
    const inputs: Record<string, InputValue> = {};
    for (const [spec, result] of results) {
      if (result !== undefined && !(result instanceof Error)) inputs[spec.name] = result;
    }
    start.mutate(
      { project, workflow: name, inputs },
      {
        onSuccess: (accepted) => {
          setStarted(accepted);
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
              value={picked < 0 ? "" : String(picked)}
              disabled={busy}
              onChange={(event) => {
                const next = startable[Number(event.target.value)];
                setChosen(
                  event.target.value === "" || !next
                    ? null
                    : { project: next.project, name: next.name },
                );
                setValues({});
                setTouched({});
                setBad({});
                start.reset();
              }}
            >
              <option value="">Choose a workflow…</option>
              {startable.map((w, index) => (
                <option key={JSON.stringify([w.project, w.name])} value={String(index)}>
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
              disabled={busy}
              onChange={(value, unparsed) => {
                setValues((current) => ({ ...current, [spec.name]: value }));
                setTouched((current) => ({ ...current, [spec.name]: true }));
                setBad((current) => ({ ...current, [spec.name]: unparsed }));
              }}
            />
          ))}
          {start.isPending && (
            <span role="status" className="ah-small">
              Starting the run…
            </span>
          )}
          {started && !reported.late && (
            <span role="status" className="ah-small">
              Started. Waiting for the run&apos;s first event…
            </span>
          )}
          {started && reported.late && runPath && (
            <div role="alert" className="ah-stack ah-small" style={{ gap: 4 }}>
              <span>
                The run has not reported in {REPORT_WAIT_MS / 1000} s. Its child&apos;s output is in{" "}
                <code className="ah-mono">.agent-runs/web/{started.run_id}.log</code> in the hub.
              </span>
              <AppLink href={runPath}>Open the run anyway</AppLink>
            </div>
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
