import { useState, type ReactNode, type RefObject } from "react";

import {
  Button,
  CopyButton,
  DataTable,
  Icon,
  JsonViewer,
  PathText,
  SidePanel,
  Tabs,
  HighlightedCode,
  languageName,
  languageOf,
} from "../../components";
import { DraftLine, EffectBadge } from "./parts";
import type { ScenarioAction, ScenarioStep } from "./queries";
import { pace } from "./story";

/* The action a step calls, in a side panel: what it does, its effect, the script it runs, its
 * inputs and output, and its files as the hub holds them (read-only). */

const EFFECT_WORDS: Readonly<Record<string, string>> = {
  read: "It reads; it never changes the system.",
  write: "It changes data.",
  destroy: "It deletes or replaces data.",
};

/** A file's text, read-only, with its path, its language and Copy; coloured by its language. */
export function FileText({
  path,
  text,
  truncated = false,
  caption,
}: {
  path: string;
  text: string | null | undefined;
  truncated?: boolean;
  /** What the file is for, under its path ("The code the step runs."). */
  caption?: ReactNode;
}) {
  const language = languageOf(path);
  return (
    <div className="ah-stack sc-file" style={{ gap: 6 }}>
      <div className="ah-row" style={{ gap: 6 }}>
        <Icon name="file-text" size="sm" />
        <span className="ah-mono ah-small">
          <PathText path={path} max={72} dimDir />
        </span>
        {language !== "" && (
          <span className="ah-badge ah-badge-quiet">{languageName(language)}</span>
        )}
        <span className="ah-grow" />
        {text && <CopyButton text={text} label={`Copy the text of ${path}`} compact />}
      </div>
      {caption && <span className="ah-small ah-muted">{caption}</span>}
      {text === null || text === undefined ? (
        <span className="ah-small ah-muted">This file could not be read.</span>
      ) : (
        // A scrollable region must be reachable by keyboard.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        <pre className="ah-json" tabIndex={0} aria-label={`Text of ${path}`}>
          <HighlightedCode text={text} lang={language} />
        </pre>
      )}
      {truncated && (
        <span className="ah-small ah-subtle">
          The file is longer than 64 KiB; the rest is in the file.
        </span>
      )}
    </div>
  );
}

export function ActionPanel({
  action,
  steps,
  openerRef,
  onClose,
  onShowStep,
  tools,
}: {
  action: ScenarioAction;
  steps: readonly ScenarioStep[];
  openerRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onShowStep: (id: string) => void;
  /** Buttons at the top of the panel (the builder's Edit, Add to the scenario). */
  tools?: ReactNode;
}) {
  const [tab, setTab] = useState<"script" | "document">("script");
  const usedBy = steps.filter((step) => step.action === action.ref);
  return (
    <SidePanel
      title={`Action ${action.name}`}
      closeLabel={`Close action ${action.name}`}
      onClose={onClose}
      openerRef={openerRef}
    >
      <div className="ah-stack" style={{ gap: 16 }}>
        {tools && (
          <div className="ah-row ah-wrap" style={{ gap: 8 }}>
            {tools}
          </div>
        )}
        <div className="ah-row ah-wrap" style={{ gap: 8 }}>
          <EffectBadge effect={action.effect} />
          <span className="ah-small ah-subtle">{action.draft ? "draft" : "committed"}</span>
          {action.path && (
            <span className="ah-mono ah-small ah-muted">
              <PathText path={action.path} max={48} />
            </span>
          )}
        </div>
        <dl className="sc-values">
          <div className="sc-value">
            <dt className="ah-muted">Does</dt>
            <dd>{action.description}</dd>
          </div>
          {action.effect && (
            <div className="sc-value">
              <dt className="ah-muted">Effect</dt>
              <dd>{EFFECT_WORDS[action.effect] ?? action.effect}</dd>
            </div>
          )}
          <div className="sc-value">
            <dt className="ah-muted">Runs</dt>
            <dd>
              {action.runtime === "python" ? "python via uv run" : action.runtime} ·{" "}
              <span className="ah-mono">{action.script}</span>
            </dd>
          </div>
          {action.timeout && (
            <div className="sc-value">
              <dt className="ah-muted">Timeout</dt>
              <dd>{pace(action.timeout)}</dd>
            </div>
          )}
          <div className="sc-value">
            <dt className="ah-muted">Used by</dt>
            <dd className="ah-row ah-wrap" style={{ gap: 6 }}>
              {usedBy.map((step) => (
                <Button
                  key={step.id}
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    onShowStep(step.id);
                  }}
                >
                  <span className="ah-mono">{step.id}</span>
                </Button>
              ))}
            </dd>
          </div>
        </dl>
        {action.draft && action.accept_command && (
          <DraftLine commands={[action.accept_command]} action={action.name} then="plan again" />
        )}
        {action.inputs.length > 0 && (
          <div className="ah-stack" style={{ gap: 6 }}>
            <h3 className="ah-h3" style={{ margin: 0 }}>
              Inputs
            </h3>
            <DataTable
              caption={`Inputs of ${action.name}`}
              density="compact"
              rows={[...action.inputs]}
              rowKey={(input) => input.name}
              columns={[
                {
                  id: "name",
                  label: "Input",
                  render: (input) => <span className="ah-mono">{input.name}</span>,
                },
                { id: "type", label: "Type", render: (input) => input.type },
                {
                  id: "required",
                  label: "Required",
                  render: (input) => (input.required ? "yes" : "no"),
                },
                {
                  id: "default",
                  label: "Default",
                  render: (input) =>
                    input.default === null || input.default === undefined ? (
                      <span className="ah-subtle">—</span>
                    ) : (
                      <span className="ah-mono">{JSON.stringify(input.default)}</span>
                    ),
                },
                {
                  id: "description",
                  label: "Description",
                  render: (input) => <span className="ah-small">{input.description ?? ""}</span>,
                },
              ]}
            />
          </div>
        )}
        <div className="ah-stack" style={{ gap: 6 }}>
          <h3 className="ah-h3" style={{ margin: 0 }}>
            Output
          </h3>
          <span className="ah-small ah-muted">It prints one JSON value of this shape:</span>
          <JsonViewer value={action.output_format ?? {}} maxHeight={240} />
        </div>
        <div className="ah-stack" style={{ gap: 8 }}>
          <h3 className="ah-h3" style={{ margin: 0 }}>
            Files
          </h3>
          <Tabs
            label="Files of the action"
            value={tab}
            onChange={(id) => {
              setTab(id === "document" ? "document" : "script");
            }}
            tabs={[
              { id: "script", label: "Script" },
              { id: "document", label: "Action file" },
            ]}
          />
          {tab === "script" ? (
            <FileText
              path={action.script ?? ""}
              text={action.script_text}
              truncated={action.script_truncated}
            />
          ) : (
            <FileText path={action.path ?? ""} text={action.document_text} />
          )}
          <span className="ah-small ah-subtle">
            Edit the files, or ask Claude with Discuss, and this page updates. A changed action is a
            draft until you commit it.
          </span>
        </div>
      </div>
    </SidePanel>
  );
}
