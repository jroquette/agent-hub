import type { ReactNode } from "react";

import { CopyButton, Icon } from "../../../components";
import type { ScenarioAction } from "../queries";
import { pace } from "../story";
import { ValueToken, tokenOf } from "./CardParts";
import { looksLikeJson, parseLoose, stringifyLoose } from "./looseJson";
import { conditionWords, shown, text, type BuilderNode, type Json } from "./model";

/* A selected step, open in place: part of the row, not a card inside it. It reads in the order
 * an API operation does (what it runs, the values it sends, its body, where values come from,
 * what it keeps), in the builder's own words and look: references as tokens, the body in the
 * app's code well, the effect said once by the row's badge. */

/** Where the step's values can come from, as the builder knows them now. */
export interface StepSources {
  /** The environment chosen in the run bar, and the values it gives. */
  environment: { name: string; values: Readonly<Record<string, string>> } | null;
  /** The scenario's run inputs. */
  inputs: readonly string[];
  /** The values earlier steps keep, with the step that keeps each. */
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
  /** Starts editing a field (null: nothing is edited here). */
  onEdit: ((field: string) => void) | null;
}

const REFERENCE = /\$(?:INPUTS|CTX)\.[A-Za-z0-9_]+|\$[a-z0-9_-]+\.output(?:\.[A-Za-z0-9_.]+)?/gi;

function record(value: Json | undefined): Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

function written(value: Json): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function isBody(value: Json): boolean {
  return typeof value === "object" || looksLikeJson(written(value));
}

function pretty(value: Json): string {
  if (typeof value === "object") return stringifyLoose(value, true);
  const parsed = parseLoose(written(value));
  return parsed.ok ? stringifyLoose(parsed.value, true) : written(value);
}

/** A text with its references drawn as tokens. */
function WithTokens({ value }: { value: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of value.matchAll(REFERENCE)) {
    const at = match.index;
    if (at > last) parts.push(value.slice(last, at));
    parts.push(<ValueToken key={at} value={match[0]} />);
    last = at + match[0].length;
  }
  if (last < value.length) parts.push(value.slice(last));
  return <>{parts}</>;
}

const JSON_TOKEN =
  /("(?:[^"\\]|\\.)*")(\s*:)?|\$(?:INPUTS|CTX)\.[A-Za-z0-9_]+|-?\d+(?:\.\d+)?|true|false|null|[{}[\],]/g;

/** Indented JSON in the app's code colours; a reference (quoted or bare) is a token. */
function JsonText({ source }: { source: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of source.matchAll(JSON_TOKEN)) {
    const at = match.index;
    if (at > last) parts.push(source.slice(last, at));
    const [whole, quoted, colon] = match;
    if (quoted !== undefined && colon !== undefined) {
      parts.push(
        <span key={at} className="ah-json-k">
          {quoted}
        </span>,
        <span key={`${String(at)}c`} className="ah-json-p">
          {colon}
        </span>,
      );
    } else if (quoted !== undefined) {
      const inner = quoted.slice(1, -1);
      parts.push(
        tokenOf(inner) ? (
          <ValueToken key={at} value={inner} />
        ) : (
          <span key={at} className="ah-json-s">
            <WithTokens value={quoted} />
          </span>
        ),
      );
    } else if (whole.startsWith("$")) {
      parts.push(<ValueToken key={at} value={whole} />);
    } else if (/^[{}[\],]$/.test(whole)) {
      parts.push(
        <span key={at} className="ah-json-p">
          {whole}
        </span>,
      );
    } else {
      parts.push(
        <span key={at} className="ah-json-n">
          {whole}
        </span>,
      );
    }
    last = at + whole.length;
  }
  if (last < source.length) parts.push(source.slice(last));
  return <>{parts}</>;
}

/** Where a value the step does not set comes from, with its icon. */
function Source({
  icon,
  children,
}: {
  icon?: Parameters<typeof Icon>[0]["name"];
  children: ReactNode;
}) {
  return (
    <span className="st-open-src">
      {icon && <Icon name={icon} size="sm" />}
      {children}
    </span>
  );
}

export function OpenStep({ node, action, sources, values, editor, onEdit }: OpenStepProps) {
  const given = record(node.with);
  const params = values.filter(([, value]) => !isBody(value));
  const bodies = values.filter(([, value]) => isBody(value));
  const env = sources?.environment ?? null;
  const inherited = (action?.inputs ?? []).filter((input) => !(input.name in given));
  const every = text(node.every);
  const timeout = text(node.timeout);
  const keeps = Object.entries(record(node.capture));
  const specOf = (name: string) => action?.inputs.find((input) => input.name === name);

  // The references the step's values use, each once.
  const uses = new Map<string, string>();
  for (const [, value] of values) {
    for (const match of written(value).matchAll(/\$(INPUTS|CTX)\.([A-Za-z0-9_]+)/g)) {
      uses.set(match[0], match[2] ?? "");
    }
  }

  const editChip = (field: string, label: ReactNode, title: string) =>
    onEdit ? (
      <button
        type="button"
        className="st-chip-edit"
        tabIndex={-1}
        title={title}
        onClick={(event) => {
          event.stopPropagation();
          onEdit(field);
        }}
      >
        <span className="st-chip-text">{label}</span>
        <Icon name="pencil" size="sm" />
      </button>
    ) : (
      <span>{label}</span>
    );

  const valueOf = (name: string, value: Json): ReactNode => {
    const field = `with:${name}`;
    const editing = editor(field);
    if (editing) return editing;
    const said = written(value);
    if (said.includes("$")) {
      return (
        <span className="st-open-mono">
          <WithTokens value={said} />
        </span>
      );
    }
    return editChip(field, shown(value), `Edit ${name}`);
  };

  return (
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions -- clicks inside keep the row as it is
    <div
      className="st-open"
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      {action?.description && <p className="st-open-about">{action.description}</p>}
      <dl className="st-open-dl">
        <div className="st-open-pair">
          <dt>Runs</dt>
          <dd className="st-open-runs">
            <span className="st-open-mono st-open-strong">{action?.name ?? text(node.action)}</span>
            <span className="st-open-quiet">
              {[action?.runtime, action?.draft === true ? "Draft action" : null]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </dd>
        </div>

        {node.type === "expect" && every && timeout && (
          <div className="st-open-pair">
            <dt>Checks</dt>
            <dd className="st-open-runs">
              {editor("timing") ??
                editChip(
                  "timing",
                  `every ${pace(every)}, up to ${pace(timeout)}`,
                  "Edit how often it checks",
                )}
              {text(node.until_when) && (
                <span className="st-open-quiet">until {conditionWords(text(node.until_when))}</span>
              )}
            </dd>
          </div>
        )}

        {(params.length > 0 || inherited.length > 0) && (
          <div className="st-open-pair">
            <dt>With</dt>
            <dd>
              <div className="st-open-with">
                {params.map(([name, value]) => {
                  const spec = specOf(name);
                  return (
                    <div key={name} className="st-open-param">
                      <span className="st-open-name">{name}</span>
                      <span className="st-open-value">{valueOf(name, value)}</span>
                      <span className="st-open-src">set here</span>
                      {spec?.description && (
                        <span className="st-open-desc" title={spec.description}>
                          {spec.required ? "required · " : ""}
                          {spec.description}
                        </span>
                      )}
                    </div>
                  );
                })}
                {inherited.length > 0 && <span className="st-open-sub">From the scenario</span>}
                {inherited.map((input) => {
                  const fromEnv = env !== null && input.name in env.values;
                  const isInput = sources?.inputs.includes(input.name) ?? false;
                  return (
                    <div key={input.name} className="st-open-param st-open-inherited">
                      <span className="st-open-name">{input.name}</span>
                      <span className="st-open-value">
                        {fromEnv ? (
                          <span className="st-open-mono">{env.values[input.name]}</span>
                        ) : input.default !== undefined ? (
                          <span className="st-open-mono">{shown(input.default as Json)}</span>
                        ) : (
                          <ValueToken value={`$INPUTS.${input.name}`} />
                        )}
                      </span>
                      {fromEnv ? (
                        <Source icon="server">environment {env.name}</Source>
                      ) : input.default !== undefined ? (
                        <Source>default</Source>
                      ) : (
                        <Source icon="flag">
                          {isInput ? "scenario input · asked at start" : "from the run"}
                        </Source>
                      )}
                      {input.description && (
                        <span className="st-open-desc" title={input.description}>
                          {input.description}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </dd>
          </div>
        )}

        {bodies.map(([name, value]) => {
          const body = pretty(value);
          const about = specOf(name)?.description;
          return (
            <div key={name} className="st-open-pair">
              <dt>
                Body
                <span className="st-open-label-2">{name}</span>
              </dt>
              <dd className="st-open-body">
                {/* A scrollable region is reached by keyboard. */}
                {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
                <pre className="ah-json st-open-json" tabIndex={0} aria-label={`${name}, as JSON`}>
                  <JsonText source={body} />
                </pre>
                <span className="st-open-copy">
                  <CopyButton text={body} label={`Copy ${name}`} compact />
                </span>
                {about && <span className="st-open-desc">{about}</span>}
              </dd>
            </div>
          );
        })}

        {uses.size > 0 && (
          <div className="st-open-pair">
            <dt>Uses</dt>
            <dd>
              <div className="st-open-uses">
                {[...uses.entries()].map(([ref, name]) => {
                  const scenario = ref.startsWith("$INPUTS.");
                  const envValue = scenario && env !== null ? env.values[name] : undefined;
                  const keptBy = sources?.kept.find((item) => item.name === name)?.number;
                  return (
                    <div key={ref} className="st-open-use">
                      <ValueToken value={ref} />
                      <span className="st-open-quiet">
                        {scenario
                          ? envValue !== undefined
                            ? `scenario input · ${envValue} from environment ${env?.name ?? ""}`
                            : "scenario input · asked when the scenario run starts"
                          : keptBy
                            ? `kept by ${keptBy}`
                            : "kept by an earlier step"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </dd>
          </div>
        )}

        {keeps.length > 0 && (
          <div className="st-open-pair">
            <dt>Keeps</dt>
            <dd>
              <div className="st-open-uses">
                {keeps.map(([name, from]) => (
                  <div key={name} className="st-open-use">
                    <ValueToken value={`$CTX.${name}`} />
                    <span className="st-open-quiet">
                      ← <WithTokens value={written(from)} />
                    </span>
                  </div>
                ))}
              </div>
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}
