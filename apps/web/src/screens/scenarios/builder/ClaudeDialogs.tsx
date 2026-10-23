import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { components } from "../../../api/schema";
import { Banner, Button, Dialog, Icon, SegmentedControl } from "../../../components";
import { apiCommand, apiKey, apiPost, useApi, type ApiProblem } from "../../../lib/api";
import type { DescribeScope } from "./claude";

/* The builder's dialogs around Claude and new actions: describe a scenario (or its next steps) in
 * words for Claude to turn into blocks; write a new action yourself, from a script template. */

type Schemas = components["schemas"];
export type ProposalView = Schemas["ProposalView"];
type NewAction = Schemas["NewAction"];
type InputType = NonNullable<NewAction["inputs"]>[number]["type"];
type OutputType = NonNullable<NewAction["outputs"]>[number]["type"];
type ActionView = Schemas["ScenarioActionView"];

const EXAMPLE = `Create a B2B order by hand in the storefront (paid on credit, €1000 or more) and give me its order id.
Send FETCH_ORDERS for webshop t_ws_7e8111d33041 to the webshop-events queue.
Wait until the order is ON_HOLD and its cover is PENDING (check every 15 s, up to 10 min).
Send INSURANCE_RESOLVE_COVER_JOBS to the payments-queue and wait until the cover is QUOTED or REFUSED.
If QUOTED: switch the order to FedEx with a DB script and reprocess it. If REFUSED: stop.
Run the poller until the cover is ACTIVATED (at most 3 rounds).`;

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
  onCreated,
  onClose,
}: {
  project: string;
  pack: string;
  /** For a check: the action can only read. */
  readOnly: boolean;
  onCreated: (action: ActionView) => void;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [effect, setEffect] = useState<NewAction["effect"]>(readOnly ? "read" : "write");
  const [runtime, setRuntime] = useState<"python" | "sh">("python");
  const [inputs, setInputs] = useState<Row[]>([]);
  const [outputs, setOutputs] = useState<Row[]>([]);
  const [script, setScript] = useState<string | null>(null);
  const create = useMutation<ActionView, ApiProblem, NewAction>({
    mutationFn: (body) =>
      apiPost("/api/v1/projects/{project}/actions", body, { path: { project } }),
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
      title="New action"
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
            {create.isPending ? "Writing…" : "Write the action"}
          </Button>
        </>
      }
    >
      <div className="ah-stack" style={{ gap: 12 }}>
        <span className="ah-small ah-muted">
          Saved as actions/{pack}/{name || "<name>"}.yaml with its script. It is a draft until you
          commit it in the hub: the plan denies a draft.
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
              placeholder="render-invoice-pdf"
              value={name}
              onChange={(event) => {
                setName(event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"));
              }}
            />
          </label>
          <label className="ah-stack ah-small" style={{ gap: 4 }}>
            What it does
            <input
              className="ah-input"
              placeholder="Render the invoice PDF and upload it"
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
