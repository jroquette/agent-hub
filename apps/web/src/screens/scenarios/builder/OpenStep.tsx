import type { ReactNode } from "react";

import { CopyButton, Icon } from "../../../components";
import type { ScenarioAction } from "../queries";
import { pace } from "../story";
import { ValueToken, tokenOf } from "./CardParts";
import { looksLikeJson, parseLoose, stringifyLoose } from "./looseJson";
import { useServiceField, type ServiceOption } from "./ServicePicker";
import { ActionFiles } from "./StepScript";
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
  /** The services declared in the environment, for a `service` input's picker. */
  services?: readonly ServiceOption[];
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
  /** Sets one value of the step (a service picked from the list). */
  onSet?: ((name: string, value: Json) => void) | null;
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

export function OpenStep({
  node,
  action,
  sources,
  values,
  editor,
  onEdit,
  onSet = null,
}: OpenStepProps) {
  const params = values.filter(([, value]) => !isBody(value));
  const bodies = values.filter(([, value]) => isBody(value));
  const env = sources?.environment ?? null;
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

  // A service input is picked from the declared services, never typed; one the step does not
  // set yet is listed too, so a place to send to is chosen right here.
  const serviceInputs = (action?.inputs ?? []).filter((input) => input.type === "service");
  const unsetServices = serviceInputs.filter(
    (input) => !values.some(([name]) => name === input.name),
  );
  const isService = (name: string) => serviceInputs.some((input) => input.name === name);
  const serviceRow = (name: string, value: string, required: boolean, about: string | null) => (
    <ServiceRow
      key={name}
      name={name}
      value={value}
      note={`${name}${required ? " · required" : ""}${about ? ` · ${about}` : ""}`}
      options={sources?.services ?? []}
      environment={env?.name ?? null}
      onPick={(picked) => {
        onSet?.(name, picked);
      }}
    />
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

      <Group title="Runs">
        <Row
          label={
            <span className="st-open-mono st-open-strong">{action?.name ?? text(node.action)}</span>
          }
          value={
            <span className="st-open-quiet">
              {[action?.runtime, action?.draft === true ? "Draft action" : null]
                .filter(Boolean)
                .join(" · ")}
            </span>
          }
        />
        {node.type === "expect" && every && timeout && (
          <Row
            label="Checks"
            value={
              editor("timing") ??
              editChip(
                "timing",
                `every ${pace(every)}, up to ${pace(timeout)}`,
                "Edit how often it checks",
              )
            }
          />
        )}
        {node.type === "expect" && text(node.until_when) && (
          <Row label="Until" value={conditionWords(text(node.until_when))} />
        )}
        {action && (action.script_text != null || action.document_text != null) && (
          <li className="st-g-row st-g-more">
            {/* Folded: what will run is one click away, never in the way. */}
            <details className="st-code">
              <summary>
                <Icon name="chevron-right" size="sm" />
                Show the code it runs
                <span className="st-open-quiet">{action.script ?? ""}</span>
              </summary>
              <div className="st-code-files">
                <ActionFiles action={action} captions />
              </div>
            </details>
          </li>
        )}
      </Group>

      {(params.length > 0 || (onSet && unsetServices.length > 0)) && (
        <Group title="Set in this step">
          {onSet &&
            unsetServices.map((input) =>
              serviceRow(input.name, "", input.required, input.description ?? null),
            )}
          {params.map(([name, value]) => {
            const spec = specOf(name);
            if (onSet && isService(name) && typeof value === "string")
              return serviceRow(name, value, spec?.required ?? false, spec?.description ?? null);
            return (
              <Row
                key={name}
                label={<span className="st-open-mono">{name}</span>}
                note={
                  spec?.description
                    ? `${spec.required ? "Required · " : ""}${spec.description}`
                    : undefined
                }
                value={valueOf(name, value)}
              />
            );
          })}
        </Group>
      )}

      {uses.size > 0 && (
        <Group title="Variables">
          {[...uses.entries()].map(([ref, name]) => {
            const scenario = ref.startsWith("$INPUTS.");
            const envValue = scenario && env !== null ? env.values[name] : undefined;
            const keptBy = sources?.kept.find((item) => item.name === name)?.number;
            return (
              <Row
                key={ref}
                label={<ValueToken value={ref} />}
                value={
                  <span className="st-open-quiet">
                    {scenario
                      ? envValue !== undefined
                        ? `scenario input · ${envValue} from environment ${env?.name ?? ""}`
                        : "scenario input · asked when the scenario run starts"
                      : keptBy
                        ? `kept by ${keptBy}`
                        : "kept by an earlier step"}
                  </span>
                }
              />
            );
          })}
        </Group>
      )}

      {bodies.map(([name, value]) => {
        const body = pretty(value);
        const about = specOf(name)?.description;
        return (
          <section key={name} className="st-g-section" aria-label={`Body ${name}`}>
            <h4 className="st-g-title">
              Body <span className="st-open-mono">{name}</span>
            </h4>
            <div className="st-open-body">
              {/* A scrollable region is reached by keyboard. */}
              {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
              <pre className="ah-json st-open-json" tabIndex={0} aria-label={`${name}, as JSON`}>
                <JsonText source={body} />
              </pre>
              <span className="st-open-copy">
                <CopyButton text={body} label={`Copy ${name}`} compact />
              </span>
            </div>
            {about && <span className="st-g-foot">{about}</span>}
          </section>
        );
      })}

      {keeps.length > 0 && (
        <Group title="Keeps">
          {keeps.map(([name, from]) => (
            <Row
              key={name}
              label={<ValueToken value={`$CTX.${name}`} />}
              value={
                <span className="st-open-quiet">
                  from <WithTokens value={written(from)} />
                </span>
              }
            />
          ))}
        </Group>
      )}
    </div>
  );
}

/** A titled group of rows, as a grouped list in system settings. */
function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="st-g-section" aria-label={title}>
      <h4 className="st-g-title">{title}</h4>
      <ul className="st-g">{children}</ul>
    </section>
  );
}

/** One row of a group: its label at the left (a note under it), its value at the right. */
function Row({
  label,
  value,
  note,
  source,
  quiet = false,
}: {
  label: ReactNode;
  value: ReactNode;
  note?: string | undefined;
  source?: ReactNode;
  quiet?: boolean;
}) {
  return (
    <li className="st-g-row" data-quiet={quiet ? "true" : undefined}>
      <span className="st-g-label">
        {label}
        {note && (
          <span className="st-g-note" title={note}>
            {note}
          </span>
        )}
      </span>
      <span className="st-g-value">
        {value}
        {source}
      </span>
    </li>
  );
}

/** A service input's row: its kind where an input's name goes (the input's name moves to the
 * note), the service itself where its value goes. */
function ServiceRow({
  name,
  value,
  note,
  options,
  environment,
  onPick,
}: {
  name: string;
  value: string;
  note: string;
  options: readonly ServiceOption[];
  environment: string | null;
  onPick: (value: string) => void;
}) {
  const { kindSelect, field } = useServiceField({
    label: name,
    value,
    options,
    environment,
    onPick,
  });
  return <Row label={kindSelect} note={note} value={field} />;
}
