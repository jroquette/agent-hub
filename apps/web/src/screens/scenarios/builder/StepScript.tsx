import { useState } from "react";

import { Button, DataTable, Dialog, Icon, Tabs } from "../../../components";
import { FileText } from "../ActionPanel";
import { EffectBadge } from "../parts";
import type { ScenarioAction } from "../queries";
import { pace } from "../story";
import { ValueToken, tokenOf } from "./CardParts";
import { shown, type BuilderDocument, type BuilderNode, type Json } from "./model";

/* The Script tab of the step editor (scenario builder v6): what the step will run, with what.
 * The action's description and facts, where each of its inputs gets its value in the chosen
 * environment (this step, the environment, the scenario run, a default, or nothing), what it
 * gives back, and its script and action file as the hub holds them (read-only). */

export type InputSource = "step" | "environment" | "run" | "default" | "missing";

export interface ResolvedInput {
  name: string;
  required: boolean;
  description: string | null;
  from: InputSource;
  /** The value as written (a literal, or a reference shown as a token); null when missing. */
  value: string | null;
}

function record(value: Json | undefined): Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

/** Where each input of the step's action gets its value, first match wins: the value the step
 * sets, then (for an input named like a scenario input) the chosen environment's value, the
 * scenario input's default or the value asked at start, then the action input's default. */
export function resolveInputs(
  node: BuilderNode,
  action: ScenarioAction,
  document: BuilderDocument,
  environmentValues: Readonly<Record<string, string>> | null,
): ResolvedInput[] {
  const given = record(node.with);
  const declared = record(document.inputs);
  return action.inputs.map((input) => {
    const base = {
      name: input.name,
      required: input.required,
      description: input.description ?? null,
    };
    const own = given[input.name];
    if (own !== undefined && own !== `$INPUTS.${input.name}`) {
      return { ...base, from: "step", value: shown(own) };
    }
    if (input.name in declared) {
      const fromEnv = environmentValues?.[input.name];
      if (fromEnv !== undefined) return { ...base, from: "environment", value: fromEnv };
      const fallback = record(declared[input.name]).default;
      return {
        ...base,
        from: "run",
        value: fallback === undefined ? null : shown(fallback),
      };
    }
    if (input.default !== null && input.default !== undefined) {
      return { ...base, from: "default", value: shown(input.default as Json) };
    }
    return { ...base, from: input.required ? "missing" : "default", value: null };
  });
}

const RUNTIME_WORDS: Readonly<Record<string, string>> = {
  python: "Python, run with uv",
  shell: "Shell",
};

function SourceCell({ from, environment }: { from: InputSource; environment: string | null }) {
  switch (from) {
    case "step":
      return <span>this step</span>;
    case "environment":
      return (
        <span className="ah-row" style={{ gap: 4 }}>
          <Icon name="server" size="sm" /> {environment}
        </span>
      );
    case "run":
      return (
        <span className="ah-row" style={{ gap: 4 }}>
          <Icon name="flag" size="sm" /> scenario run
        </span>
      );
    case "default":
      return <span className="ah-muted">default</span>;
    case "missing":
      return (
        <span className="ah-row" style={{ gap: 4, color: "var(--failed)" }}>
          <Icon name="circle-x" size="sm" /> Missing
        </span>
      );
  }
}

export function StepScript({
  node,
  number,
  action,
  document,
  environment,
  environmentValues,
}: {
  node: BuilderNode;
  number: string | undefined;
  action: ScenarioAction;
  document: BuilderDocument;
  environment: string | null;
  environmentValues: Readonly<Record<string, string>> | null;
}) {
  const rows = resolveInputs(node, action, document, environmentValues);
  const gives = Object.keys(record(action.output_format?.properties as Json | undefined));
  const kept = Object.entries(record(node.capture));
  const keptAs = (field: string) =>
    kept.find(([, from]) => shown(from) === `$self.output.${field}`)?.[0];
  return (
    <div className="sb-script">
      <section className="sb-section-v5" aria-label="What it does">
        <h3 className="sb-section-title">What it does</h3>
        {action.description && <p className="sb-script-desc">{action.description}</p>}
        <span className="sb-script-facts">
          <EffectBadge effect={action.effect} words />
          <span>{RUNTIME_WORDS[action.runtime ?? ""] ?? action.runtime}</span>
          {action.timeout && <span>stops after {pace(action.timeout)}</span>}
          <span
            title={
              action.draft
                ? `Not committed yet: ${action.accept_command ?? "commit it in the hub checkout"}`
                : undefined
            }
          >
            {action.draft ? "Draft, not committed yet" : "Committed"}
          </span>
        </span>
      </section>

      {rows.length > 0 && (
        <section className="sb-section-v5" aria-label="How this step fills each input">
          <h3 className="sb-section-title">
            How this step fills each input
            {environment && <span className="ah-muted"> · in {environment}</span>}
          </h3>
          <DataTable
            caption={`How step ${number ?? node.id} fills the inputs of ${action.name}`}
            density="compact"
            rows={rows}
            rowKey={(row) => row.name}
            columns={[
              {
                id: "name",
                label: "Input",
                render: (row) => <span className="ah-mono">{row.name}</span>,
              },
              {
                id: "from",
                label: "From",
                render: (row) => <SourceCell from={row.from} environment={environment} />,
              },
              {
                id: "value",
                label: "Value",
                render: (row) =>
                  row.value === null ? (
                    <span className="ah-subtle">{row.from === "run" ? "asked at start" : "—"}</span>
                  ) : tokenOf(row.value) ? (
                    <ValueToken value={row.value} />
                  ) : (
                    <span className="ah-mono sb-script-value" title={row.value}>
                      {row.value}
                    </span>
                  ),
              },
            ]}
          />
        </section>
      )}

      <section className="sb-section-v5" aria-label="Gives">
        <h3 className="sb-section-title">Gives</h3>
        {gives.length === 0 ? (
          <span className="ah-small ah-muted">No output declared.</span>
        ) : (
          <span className="sb-script-gives">
            {gives.map((field) => (
              <span key={field} className="ah-mono">
                {field}
                {keptAs(field) && <span className="ah-muted"> (kept as {keptAs(field)})</span>}
              </span>
            ))}
          </span>
        )}
      </section>

      <section className="sb-section-v5" aria-label="Files">
        <ActionFiles action={action} />
        <span className="ah-small ah-subtle">
          Edit the files in your editor, or ask in Chat, and this updates. A changed action is a
          draft until you commit it.
        </span>
      </section>
    </div>
  );
}

/** An action's two files in tabs, Script first (what runs) and the action file (what it
 * declares), with Expand into a dialog; `captions` says what each one is for. */
export function ActionFiles({
  action,
  captions = false,
}: {
  action: ScenarioAction;
  captions?: boolean;
}) {
  const [file, setFile] = useState<"script" | "document">("script");
  const [expanded, setExpanded] = useState(false);
  const path = file === "script" ? (action.script ?? "") : (action.path ?? "");
  const text = file === "script" ? action.script_text : action.document_text;
  const caption = !captions ? undefined : file === "script" ? (
    <>
      <b>Runs.</b> The code this step executes: the hub calls it with the step&apos;s values as its
      inputs.
    </>
  ) : (
    <>
      <b>Declares.</b> The action file is not run: it names the script, the inputs it takes, whether
      it changes data and what it answers.
    </>
  );
  const fileView = (
    <FileText
      path={path}
      text={text}
      truncated={file === "script" ? action.script_truncated : false}
      caption={caption}
    />
  );
  return (
    <>
      <span className="ah-row" style={{ gap: 8 }}>
        <Tabs
          label="Files of the action"
          value={file}
          onChange={(id) => {
            setFile(id === "document" ? "document" : "script");
          }}
          tabs={[
            { id: "script", label: "Script" },
            { id: "document", label: "Action file" },
          ]}
        />
        <span className="ah-grow" />
        <Button
          size="sm"
          variant="ghost"
          icon="expand"
          onClick={() => {
            setExpanded(true);
          }}
        >
          Expand
        </Button>
      </span>
      {fileView}
      {expanded && (
        <Dialog
          title={`${path} · ${action.name}`}
          onClose={() => {
            setExpanded(false);
          }}
          size="lg"
        >
          <div className="sb-script-dialog">{fileView}</div>
        </Dialog>
      )}
    </>
  );
}
