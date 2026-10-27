import type { ReactNode } from "react";

import { CopyButton, Icon } from "../../../components";
import type { ScenarioAction } from "../queries";
import { pace } from "../story";
import { firstSentence } from "./CardParts";
import { looksLikeJson, parseLoose, stringifyLoose } from "./looseJson";
import { conditionWords, shown, text, type BuilderNode, type Json } from "./model";

/* A selected step, open in place and read like an API operation (Swagger, Postman): a header
 * with what it does to the system (READ, WRITE, DELETE) and the action it runs; its parameters,
 * each with its value and where the value comes from; the request body, indented, its variables
 * drawn as {{name}}; the variables it uses by scope (the scenario's, global; kept by an earlier
 * step, local); for a check, how it polls; and what it keeps from the answer. */

/** Where the step's values can come from, as the builder knows them now. */
export interface StepSources {
  /** The environment chosen in the run bar, and the values it gives. */
  environment: { name: string; values: Readonly<Record<string, string>> } | null;
  /** The scenario's run inputs (global variables). */
  inputs: readonly string[];
  /** The values earlier steps keep (local variables), with the step that keeps each. */
  kept: readonly { name: string; number: string }[];
}

export interface OpenStepProps {
  node: BuilderNode;
  action: ScenarioAction | null;
  sources: StepSources | null;
  /** The step's own values, ordered as the action declares its inputs. */
  values: readonly [string, Json][];
  /** An edit field for `with:<name>` or `timing`, while it is being edited; else null. */
  editor: (field: string) => ReactNode;
  /** Starts editing a field (null: the value is not edited here). */
  onEdit: ((field: string) => void) | null;
}

const METHOD: Readonly<Record<string, { label: string; tone: string }>> = {
  read: { label: "READ", tone: "read" },
  write: { label: "WRITE", tone: "write" },
  destroy: { label: "DELETE", tone: "destroy" },
};

const VARIABLE = /\$(INPUTS|CTX)\.([A-Za-z0-9_]+)/g;

function record(value: Json | undefined): Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

function written(value: Json): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** A variable as Postman writes it: `{{name}}`, coloured by scope. */
function Variable({ scope, name }: { scope: string; name: string }) {
  const global = scope === "INPUTS";
  return (
    <span
      className="st-var"
      data-scope={global ? "global" : "local"}
      title={global ? `Scenario variable ${name}` : `Kept by an earlier step: ${name}`}
    >
      {`{{${name}}}`}
    </span>
  );
}

/** A text with its `$INPUTS.x` / `$CTX.x` drawn as `{{x}}`. */
function WithVariables({ value }: { value: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of value.matchAll(VARIABLE)) {
    const at = match.index;
    if (at > last) parts.push(value.slice(last, at));
    parts.push(<Variable key={at} scope={match[1] ?? ""} name={match[2] ?? ""} />);
    last = at + match[0].length;
  }
  if (last < value.length) parts.push(value.slice(last));
  return <>{parts}</>;
}

const JSON_TOKEN = /("(?:[^"\\]|\\.)*")(\s*:)?|\$(?:INPUTS|CTX)\.[A-Za-z0-9_]+/g;

/** Indented JSON, keys and strings told apart, a variable in quotes drawn as `{{name}}` alone. */
export function JsonView({ text: source }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of source.matchAll(JSON_TOKEN)) {
    const at = match.index;
    if (at > last) parts.push(<span key={`p${String(at)}`}>{source.slice(last, at)}</span>);
    const [whole, quoted, colon] = match;
    if (quoted !== undefined && colon !== undefined) {
      parts.push(
        <span key={at} className="st-json-key">
          {quoted}
        </span>,
        colon,
      );
    } else if (quoted !== undefined) {
      const inner = /^"\$(INPUTS|CTX)\.([A-Za-z0-9_]+)"$/.exec(quoted);
      parts.push(
        inner ? (
          <Variable key={at} scope={inner[1] ?? ""} name={inner[2] ?? ""} />
        ) : (
          <span key={at} className="st-json-string">
            <WithVariables value={quoted} />
          </span>
        ),
      );
    } else {
      const bare = /^\$(INPUTS|CTX)\.([A-Za-z0-9_]+)$/.exec(whole);
      parts.push(<Variable key={at} scope={bare?.[1] ?? ""} name={bare?.[2] ?? ""} />);
    }
    last = at + whole.length;
  }
  if (last < source.length) parts.push(<span key="end">{source.slice(last)}</span>);
  return <>{parts}</>;
}

function isBody(value: Json): boolean {
  return typeof value === "object" || looksLikeJson(written(value));
}

function pretty(value: Json): string {
  if (typeof value === "object") return stringifyLoose(value, true);
  const parsed = parseLoose(written(value));
  return parsed.ok ? stringifyLoose(parsed.value, true) : written(value);
}

/** The variables a step's values use, by scope, each once. */
function variablesOf(values: readonly [string, Json][]): { scope: string; name: string }[] {
  const seen = new Map<string, { scope: string; name: string }>();
  for (const [, value] of values) {
    for (const match of written(value).matchAll(VARIABLE)) {
      const scope = match[1] ?? "";
      const name = match[2] ?? "";
      seen.set(`${scope}.${name}`, { scope, name });
    }
  }
  return [...seen.values()];
}

export function OpenStep({ node, action, sources, values, editor, onEdit }: OpenStepProps) {
  const method = METHOD[action?.effect ?? ""] ?? { label: "RUN", tone: "run" };
  const given = record(node.with);
  const params = values.filter(([, value]) => !isBody(value));
  const bodies = values.filter(([, value]) => isBody(value));
  const env = sources?.environment ?? null;

  // Inputs the step does not set: the scenario run or the environment gives them, or a default.
  const unset = (action?.inputs ?? []).filter((input) => !(input.name in given));
  const sourceOf = (name: string, hasDefault: boolean): ReactNode => {
    if (env && name in env.values) {
      return (
        <span className="st-src" data-src="env">
          environment {env.name}
        </span>
      );
    }
    if (sources?.inputs.includes(name)) {
      return (
        <span className="st-src" data-src="global">
          scenario variable
        </span>
      );
    }
    if (hasDefault) {
      return (
        <span className="st-src" data-src="default">
          default
        </span>
      );
    }
    return (
      <span className="st-src" data-src="run">
        scenario run
      </span>
    );
  };

  const variables = variablesOf(values);
  const every = text(node.every);
  const timeout = text(node.timeout);
  const keeps = Object.entries(record(node.capture));

  const valueCell = (name: string, value: Json): ReactNode => {
    const field = `with:${name}`;
    const editing = editor(field);
    if (editing) return editing;
    const shownValue = written(value);
    const pure = /^\$(INPUTS|CTX)\.([A-Za-z0-9_]+)$/.exec(shownValue);
    if (pure) return <Variable scope={pure[1] ?? ""} name={pure[2] ?? ""} />;
    if (
      onEdit &&
      (typeof value === "number" || typeof value === "boolean" || !shownValue.includes("$"))
    )
      return (
        <button
          type="button"
          className="st-chip-edit"
          tabIndex={-1}
          title={`Edit ${name}`}
          onClick={(event) => {
            event.stopPropagation();
            onEdit(field);
          }}
        >
          {shown(value)}
          <Icon name="pencil" size="sm" />
        </button>
      );
    return (
      <span className="st-mono">
        <WithVariables value={shownValue} />
      </span>
    );
  };

  return (
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions -- clicks inside keep the row as it is
    <div
      className="st-op"
      data-tone={method.tone}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <div className="st-op-head">
        <span className="st-op-method">{method.label}</span>
        <span className="st-op-path">{action?.name ?? text(node.action)}</span>
        {action?.draft === true && <span className="st-op-tag">draft</span>}
        {action?.runtime && <span className="st-op-tag">{action.runtime}</span>}
        <span className="st-op-summary">
          {action?.description ? firstSentence(action.description) : ""}
        </span>
      </div>

      {node.type === "expect" && every && timeout && (
        <section className="st-op-section" aria-label="Polling">
          <h4 className="st-op-title">Polling</h4>
          <div className="st-op-poll">
            <span>
              Checks{" "}
              {editor("timing") ??
                (onEdit ? (
                  <button
                    type="button"
                    className="st-chip-edit"
                    tabIndex={-1}
                    title="Edit how often it checks"
                    onClick={(event) => {
                      event.stopPropagation();
                      onEdit("timing");
                    }}
                  >
                    every {pace(every)}, up to {pace(timeout)}
                    <Icon name="pencil" size="sm" />
                  </button>
                ) : (
                  `${pace(every)}, up to ${pace(timeout)}`
                ))}
            </span>
            {text(node.until_when) && (
              <span>
                Until <b>{conditionWords(text(node.until_when))}</b>
              </span>
            )}
          </div>
        </section>
      )}

      {(params.length > 0 || unset.length > 0) && (
        <section className="st-op-section" aria-label="Parameters">
          <h4 className="st-op-title">Parameters</h4>
          <table className="st-op-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Value</th>
                <th scope="col">From</th>
                <th scope="col">Description</th>
              </tr>
            </thead>
            <tbody>
              {params.map(([name, value]) => {
                const spec = action?.inputs.find((input) => input.name === name);
                const pure = /^\$(INPUTS|CTX)\./.exec(written(value));
                return (
                  <tr key={name}>
                    <td className="st-mono">
                      {name}
                      {spec?.required && (
                        <span className="st-op-req" title="Required">
                          *
                        </span>
                      )}
                    </td>
                    <td>{valueCell(name, value)}</td>
                    <td>
                      {pure ? (
                        <span
                          className="st-src"
                          data-src={pure[1] === "INPUTS" ? "global" : "local"}
                        >
                          {pure[1] === "INPUTS" ? "scenario variable" : "kept value"}
                        </span>
                      ) : (
                        <span className="st-src" data-src="step">
                          this step
                        </span>
                      )}
                    </td>
                    <td className="st-op-desc">{spec?.description ?? ""}</td>
                  </tr>
                );
              })}
              {unset.map((input) => (
                <tr key={input.name} className="st-op-inherited">
                  <td className="st-mono">
                    {input.name}
                    {input.required && (
                      <span className="st-op-req" title="Required">
                        *
                      </span>
                    )}
                  </td>
                  <td className="st-mono">
                    {env && input.name in env.values
                      ? (env.values[input.name] ?? "")
                      : input.default !== undefined
                        ? shown(input.default as Json)
                        : `{{${input.name}}}`}
                  </td>
                  <td>{sourceOf(input.name, input.default !== undefined)}</td>
                  <td className="st-op-desc">{input.description ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {bodies.map(([name, value]) => {
        const spec = action?.inputs.find((input) => input.name === name);
        const body = pretty(value);
        return (
          <section key={name} className="st-op-section" aria-label={`Request body ${name}`}>
            <h4 className="st-op-title">
              Request body <span className="st-mono st-op-name">{name}</span>
              <span className="st-op-type">application/json</span>
              <span className="ah-grow" />
              <CopyButton text={body} label={`Copy ${name}`} compact />
            </h4>
            {spec?.description && <span className="st-op-desc">{spec.description}</span>}
            <pre className="st-json" aria-label={`${name}, as JSON`}>
              <JsonView text={body} />
            </pre>
          </section>
        );
      })}

      {variables.length > 0 && (
        <section className="st-op-section" aria-label="Variables">
          <h4 className="st-op-title">Variables</h4>
          <ul className="st-op-vars">
            {variables.map(({ scope, name }) => {
              const global = scope === "INPUTS";
              const fromEnv = global && env && name in env.values ? env.values[name] : undefined;
              const keptBy = global
                ? undefined
                : sources?.kept.find((item) => item.name === name)?.number;
              return (
                <li key={`${scope}.${name}`}>
                  <Variable scope={scope} name={name} />
                  <span className="st-src" data-src={global ? "global" : "local"}>
                    {global ? "scenario" : "kept"}
                  </span>
                  <span className="ah-small ah-muted">
                    {global
                      ? fromEnv !== undefined
                        ? `${fromEnv} · from environment ${env?.name ?? ""}`
                        : "asked when the scenario run starts"
                      : keptBy
                        ? `kept by step ${keptBy}`
                        : "kept by an earlier step"}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {keeps.length > 0 && (
        <section className="st-op-section" aria-label="Keeps">
          <h4 className="st-op-title">Keeps from the answer</h4>
          <ul className="st-op-vars">
            {keeps.map(([name, from]) => (
              <li key={name}>
                <span className="st-var" data-scope="local">{`{{${name}}}`}</span>
                <span className="ah-small ah-muted">
                  ← <span className="st-mono">{written(from)}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <span className="ah-small ah-subtle">
        Values set by this step edit here · the panel edits everything, JSON included.
      </span>
    </div>
  );
}
