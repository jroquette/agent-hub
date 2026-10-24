import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { components } from "../../../api/schema";
import { Banner, Button, Dialog, Icon, SegmentedControl } from "../../../components";
import { apiCommand, apiKey, apiPost, apiPut, useApi, type ApiProblem } from "../../../lib/api";
import type { DescribeScope } from "./claude";

/* The builder's dialogs around Claude and new actions: describe a scenario (or its next steps) in
 * words for Claude to turn into blocks; write a new action yourself, from a script template. */

type Schemas = components["schemas"];
export type ProposalView = Schemas["ProposalView"];
type NewAction = Schemas["NewAction"];
type InputType = NonNullable<NewAction["inputs"]>[number]["type"];
type OutputType = NonNullable<NewAction["outputs"]>[number]["type"];
type ActionView = Schemas["ScenarioActionView"];

const EXAMPLE = `For example:
I create a record by hand and type its id.
Send a message to a queue so the service picks the record up.
Wait until the service shows the record as processed (check every 15 s, up to 10 min).
If it was accepted, call the service's API to continue; if it was rejected, stop.
Run the job until the record reaches its final state (at most 3 rounds).`;

/** Claude's proposal for the scenario, read every few seconds while one is expected. */
export function useProposal(project: string, name: string, poll: boolean) {
  return useApi(
    "/api/v1/scenarios/{project}/{name}/proposal",
    { path: { project, name } },
    { refetchInterval: poll ? 3000 : false, retry: false },
  );
}

export function useDismissProposal(project: string, name: string) {
  const client = useQueryClient();
  return useMutation<unknown, ApiProblem>({
    mutationFn: () =>
      apiCommand("/api/v1/scenarios/{project}/{name}/proposal/dismiss", {
        path: { project, name },
      }),
    onSettled: () => {
      client.removeQueries({
        queryKey: apiKey("/api/v1/scenarios/{project}/{name}/proposal", {
          path: { project, name },
        }),
      });
    },
  });
}

export function DescribeDialog({
  empty,
  after,
  onSend,
  onClose,
}: {
  /** The scenario has no steps yet: describing it builds the whole flow. */
  empty: boolean;
  /** The selected block: new steps can go after it. */
  after: string | null;
  onSend: (text: string, scope: DescribeScope) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [scope, setScope] = useState<DescribeScope>(empty ? "whole" : "after");
  return (
    <Dialog
      title="Describe it to Claude"
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            icon="message-square"
            disabled={text.trim() === ""}
            onClick={() => {
              onSend(text.trim(), scope);
            }}
          >
            Ask Claude for blocks
          </Button>
        </>
      }
    >
      <div className="ah-stack" style={{ gap: 10 }}>
        <span className="ah-small ah-muted">
          Say what the scenario does in your own words, step by step: what to send or run, what to
          wait for and how long, what you do by hand, what to check, and what happens when it goes
          one way or another. Claude turns it into blocks of this scenario (reusing the hub&apos;s
          actions, writing new ones as drafts) and shows them here as suggestions: nothing changes
          until you accept them and save.
        </span>
        {!empty && (
          <SegmentedControl
            label="What it describes"
            value={scope}
            onChange={(id) => {
              setScope(id === "whole" ? "whole" : "after");
            }}
            options={[
              { id: "after", label: after ? `Steps after ${after}` : "Steps at the end" },
              { id: "whole", label: "The whole scenario" },
            ]}
          />
        )}
        <textarea
          className="ah-input sb-describe"
          aria-label="Describe the scenario"
          rows={10}
          placeholder={EXAMPLE}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        <span className="ah-small ah-subtle">
          Claude works in the hub folder through the Discuss panel; each file it writes asks you
          first there.
        </span>
      </div>
    </Dialog>
  );
}

const TEMPLATES: Readonly<Record<"python" | "sh", (name: string) => string>> = {
  python: (name) => `# /// script
# requires-python = ">=3.12"
# ///
"""${name}: reads one JSON object on stdin and prints one JSON value."""
import json
import sys

request = json.load(sys.stdin)  # {"mode": "plan" | "run", "inputs": {...}, "endpoint": {...}}
inputs = request["inputs"]

if request["mode"] == "plan":
    # Change nothing here: no credential is available in plan mode.
    print(json.dumps({"summary": f"${name} with {inputs}"}))
    sys.exit(0)

# Run mode: do the work, then print the output fields.
print(json.dumps({}))
`,
  sh: (name) => `#!/bin/sh
# ${name}: reads one JSON object on stdin and prints one JSON value.
request=$(cat)
mode=$(printf '%s' "$request" | jq -r .mode)
if [ "$mode" = "plan" ]; then
  # Change nothing here: no credential is available in plan mode.
  printf '{"summary": "${name}"}\\n'
  exit 0
fi
# Run mode: do the work, then print the output fields.
printf '{}\\n'
`,
};

interface Row {
  name: string;
  type: string;
  required?: boolean;
}

export function NewActionDialog({
  project,
  pack,
  readOnly,
  existing = null,
  onCreated,
  onClose,
}: {
  project: string;
  pack: string;
  /** For a check: the action can only read. */
  readOnly: boolean;
  /** An action to edit (its form filled in); null writes a new one. */
  existing?: ActionView | null;
  onCreated: (action: ActionView) => void;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [effect, setEffect] = useState<NewAction["effect"]>(
    existing?.effect === "read" || existing?.effect === "write" || existing?.effect === "destroy"
      ? existing.effect
      : readOnly
        ? "read"
        : "write",
  );
  const [runtime, setRuntime] = useState<"python" | "sh">(
    existing?.runtime === "sh" ? "sh" : "python",
  );
  const [inputs, setInputs] = useState<Row[]>(
    (existing?.inputs ?? []).map((input) => ({
      name: input.name,
      type: input.type,
      required: input.required,
    })),
  );
  const [outputs, setOutputs] = useState<Row[]>(
    Object.entries(
      (existing?.output_format?.properties ?? {}) as Record<string, { type?: string }>,
    ).map(([field, schema]) => ({ name: field, type: schema.type ?? "string" })),
  );
  const [script, setScript] = useState<string | null>(existing?.script_text ?? null);
  const create = useMutation<ActionView, ApiProblem, NewAction>({
    mutationFn: (body) =>
      existing
        ? apiPut("/api/v1/projects/{project}/actions/{pack}/{name}", body, {
            path: { project, pack, name: existing.name },
          })
        : apiPost("/api/v1/projects/{project}/actions", body, { path: { project } }),
    onSuccess: (action) => {
      void client.invalidateQueries({
        queryKey: apiKey("/api/v1/projects/{project}/actions", { path: { project } }),
      });
      onCreated(action);
    },
  });
  const valid = /^[a-z][a-z0-9-]*$/.test(name) && description.trim() !== "";
  const text = script ?? TEMPLATES[runtime](name || "my-action");
  const rows = (
    list: Row[],
    set: (next: Row[]) => void,
    types: readonly string[],
    label: string,
    withRequired: boolean,
  ) => (
    <div className="ah-stack" style={{ gap: 4 }}>
      <span className="ah-small">{label}</span>
      {list.map((row, index) => (
        <div key={index} className="sb-action-row">
          <input
            className="ah-input ah-mono"
            aria-label={`${label} name`}
            placeholder="name"
            value={row.name}
            onChange={(event) => {
              set(
                list.map((item, at) =>
                  at === index ? { ...item, name: event.target.value } : item,
                ),
              );
            }}
          />
          <select
            className="ah-input"
            aria-label={`${label} type`}
            value={row.type}
            onChange={(event) => {
              set(
                list.map((item, at) =>
                  at === index ? { ...item, type: event.target.value } : item,
                ),
              );
            }}
          >
            {types.map((type) => (
              <option key={type}>{type}</option>
            ))}
          </select>
          {withRequired && (
            <label className="ah-row ah-small" style={{ gap: 4 }}>
              <input
                type="checkbox"
                checked={row.required === true}
                onChange={(event) => {
                  set(
                    list.map((item, at) =>
                      at === index ? { ...item, required: event.target.checked } : item,
                    ),
                  );
                }}
              />
              required
            </label>
          )}
          <button
            type="button"
            className="sb-icon-btn"
            aria-label={`Remove ${row.name || "this row"}`}
            onClick={() => {
              set(list.filter((_, at) => at !== index));
            }}
          >
            <Icon name="x" size="sm" />
          </button>
        </div>
      ))}
      <Button
        size="sm"
        variant="ghost"
        icon="plus"
        onClick={() => {
          set([...list, { name: "", type: types[0] ?? "string", required: withRequired }]);
        }}
      >
        Add
      </Button>
    </div>
  );
  return (
    <Dialog
      title={existing ? `Edit action ${existing.name}` : "New action"}
      size="lg"
      onClose={onClose}
      pending={create.isPending}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            icon="save"
            disabled={!valid || create.isPending}
            onClick={() => {
              create.mutate({
                pack,
                name,
                description: description.trim(),
                effect,
                runtime,
                inputs: inputs
                  .filter((row) => row.name !== "")
                  .map((row) => ({
                    name: row.name,
                    type: row.type as InputType,
                    required: row.required === true,
                  })),
                outputs: outputs
                  .filter((row) => row.name !== "")
                  .map((row) => ({
                    name: row.name,
                    type: row.type as OutputType,
                  })),
                script_text: text,
              } as NewAction);
            }}
          >
            {create.isPending ? "Writing…" : existing ? "Save the action" : "Write the action"}
          </Button>
        </>
      }
    >
      <div className="ah-stack" style={{ gap: 12 }}>
        <span className="ah-small ah-muted">
          {existing
            ? `Every scenario that runs ${existing.name} uses the new version: it is a draft again until you commit it in the hub, and the plan denies a draft.`
            : `Saved as actions/${pack}/${name || "<name>"}.yaml with its script. It is a draft until you commit it in the hub: the plan denies a draft.`}
        </span>
        {create.error && (
          <Banner tone="error" boxed>
            Could not write the action: {create.error.detail ?? create.error.title}
          </Banner>
        )}
        <div className="sb-two">
          <label className="ah-stack ah-small" style={{ gap: 4 }}>
            Name
            <input
              className="ah-input ah-mono"
              placeholder="send-message"
              value={name}
              disabled={existing !== null}
              onChange={(event) => {
                setName(event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"));
              }}
            />
          </label>
          <label className="ah-stack ah-small" style={{ gap: 4 }}>
            What it does
            <input
              className="ah-input"
              placeholder="Send one JSON message to a queue"
              value={description}
              onChange={(event) => {
                setDescription(event.target.value);
              }}
            />
          </label>
        </div>
        <div className="ah-row ah-wrap" style={{ gap: 16 }}>
          <span className="ah-stack ah-small" style={{ gap: 4 }}>
            Effect
            <SegmentedControl
              label="Effect"
              value={effect}
              onChange={(id) => {
                setEffect(id === "read" ? "read" : id === "destroy" ? "destroy" : "write");
              }}
              options={
                readOnly
                  ? [{ id: "read", label: "Reads only" }]
                  : [
                      { id: "read", label: "Reads only" },
                      { id: "write", label: "Changes data" },
                      { id: "destroy", label: "Deletes or replaces" },
                    ]
              }
            />
          </span>
          <span className="ah-stack ah-small" style={{ gap: 4 }}>
            Runtime
            <SegmentedControl
              label="Runtime"
              value={runtime}
              onChange={(id) => {
                setRuntime(id === "sh" ? "sh" : "python");
              }}
              options={[
                { id: "python", label: "Python" },
                { id: "sh", label: "Shell" },
              ]}
            />
          </span>
        </div>
        <div className="sb-two">
          {rows(
            inputs,
            setInputs,
            ["string", "integer", "number", "boolean", "service"],
            "Inputs",
            true,
          )}
          {rows(
            outputs,
            setOutputs,
            ["string", "integer", "number", "boolean", "object", "array"],
            "Output fields",
            false,
          )}
        </div>
        <label className="ah-stack ah-small" style={{ gap: 4 }}>
          Script
          <textarea
            className="ah-input ah-mono sb-script"
            rows={14}
            value={text}
            spellCheck={false}
            onChange={(event) => {
              setScript(event.target.value);
            }}
          />
        </label>
      </div>
    </Dialog>
  );
}

/** Ask Claude to write one action from a description (it writes a draft in the hub). */
export function AskActionDialog({
  onSend,
  onClose,
}: {
  onSend: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  return (
    <Dialog
      title="Ask Claude to write an action"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            icon="message-square"
            disabled={text.trim() === ""}
            onClick={() => {
              onSend(text.trim());
            }}
          >
            Ask Claude
          </Button>
        </>
      }
    >
      <div className="ah-stack" style={{ gap: 8 }}>
        <span className="ah-small ah-muted">
          Say what the action does, what it takes and what it should print back. Claude writes its
          YAML and its script in the hub as a draft (each file asks you first in the Discuss panel);
          it shows up in the palette once written.
        </span>
        <textarea
          className="ah-input sb-describe"
          aria-label="Describe the action"
          rows={6}
          placeholder="e.g. Call a service's HTTP API with a JSON body and print the response status and body"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
      </div>
    </Dialog>
  );
}
