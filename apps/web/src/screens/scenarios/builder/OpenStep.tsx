import type { ReactNode } from "react";

import { CopyButton, Icon } from "../../../components";
import { ActionFiles } from "../ActionPanel";
import { DraftLine } from "../parts";
import type { ScenarioAction } from "../queries";
import { pace } from "../story";
import { TokenText, ValueToken, tokenOf } from "./CardParts";
import { looksLikeJson, parseLoose, stringifyLoose } from "./looseJson";
import { useServiceField, type ServiceOption } from "./ServicePicker";
import { resolveInputs } from "./StepScript";
import {
  conditionWords,
  record,
  shown,
  text,
  upstreamOf,
  type BuilderDocument,
  type BuilderNode,
  type Json,
} from "./model";

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
  /** The document the steps run as: what waits for what, and the scenario inputs declared. */
  document: BuilderDocument;
  /** The values the steps keep, with the step that keeps each: its row (`step`, to select it),
   * the id it runs under (`node`) and its number. A step reads only those kept before it. */
  kept: readonly { name: string; number: string; step?: string; node: string }[];
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
  /** Edits one value of the step in the side panel (a body, a value it takes from elsewhere). */
  onEditInPanel?: ((name: string) => void) | null;
  /** Selects the step that keeps a value, by its id. */
  onGoToStep?: ((step: string) => void) | null;
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

const JSON_TOKEN =
  /("(?:[^"\\]|\\.)*")(\s*:)?|\$(?:INPUTS|CTX)\.[A-Za-z0-9_]+|-?\d+(?:\.\d+)?|true|false|null|[{}[\],]/g;

/** Indented JSON in the app's code colours; a reference (quoted or bare) is a token. It colours
 * the text `pretty` writes (the builder's loose-JSON reader and writer), so the body reads as the
 * file writes it. Not the shared JsonViewer: that walks a parsed value, writes a string unescaped
 * and an empty `{}` over two lines, and has no way to draw a reference as a token. */
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
            <TokenText value={quoted} />
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
  onEditInPanel = null,
  onGoToStep = null,
}: OpenStepProps) {
  const params = values.filter(([, value]) => !isBody(value));
  const bodies = values.filter(([, value]) => isBody(value));
  const env = sources?.environment ?? null;
  const every = text(node.every);
  const timeout = text(node.timeout);
  const keeps = Object.entries(record(node.capture));
  const specOf = (name: string) => action?.inputs.find((input) => input.name === name);

  // The values kept before this step: by the steps it waits for, directly or not.
  const before = new Set(
    sources ? upstreamOf(sources.document, node.id).map((step) => step.id) : [],
  );
  const keptBefore = (sources?.kept ?? []).filter((item) => before.has(item.node));

  // The references the step's values use, each once.
  const uses = new Map<string, string>();
  for (const [, value] of values) {
    for (const match of written(value).matchAll(/\$(INPUTS|CTX)\.([A-Za-z0-9_]+)/g)) {
      uses.set(match[0], match[2] ?? "");
    }
  }

  const given = record(node.with);
  const editChip = (field: string, label: string, title: string) =>
    onEdit ? (
      <button
        type="button"
        className="st-chip-edit"
        aria-label={`${title}: ${label}`}
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

  // Needs a value: a required input this step does not set and nothing else gives, as the Script
  // tab resolves it (resolveInputs): not a declared scenario input (whose value the environment
  // or the run gives), no default. An environment value counts only for a declared scenario
  // input, as in the Script tab. A value the step writes is its own row, even one that reads an
  // input the scenario does not declare (Values from earlier says so).
  const resolved = action
    ? resolveInputs(node, action, sources?.document ?? { nodes: [] }, env?.values ?? null)
    : [];
  const needsValue = (name: string): boolean =>
    !(name in given) && resolved.some((input) => input.name === name && input.from === "missing");
  const serviceInputs = (action?.inputs ?? []).filter((input) => input.type === "service");
  const isService = (name: string) => serviceInputs.some((input) => input.name === name);
  // A service input the step does not set yet is listed too, so where it goes is chosen here.
  const unsetServices = serviceInputs.filter((input) => !(input.name in given));
  const missing = (action?.inputs ?? []).filter(
    (input) => input.type !== "service" && needsValue(input.name),
  );
  // Counted only as listed: an unset service has its row only where it can be picked here.
  const needCount =
    missing.length + (onSet ? unsetServices.filter((input) => input.required).length : 0);
  const Needs = () => (
    <span className="st-g-missing">
      <Icon name="circle-alert" size="sm" />
      Needs a value
    </span>
  );

  // The note follows what is picked (its kind and address), never the action's own words about
  // one kind of service, which no longer hold once another kind is chosen.
  const serviceRow = (name: string, value: string, required: boolean) => (
    <ServiceRow
      key={name}
      name={name}
      value={value}
      required={required}
      needs={<Needs />}
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
        <span className="st-open-value-ref">
          <span className="st-open-mono">
            <TokenText value={said} />
          </span>
          {onEditInPanel && (
            <button
              type="button"
              className="st-g-link"
              onClick={(event) => {
                event.stopPropagation();
                onEditInPanel(name);
              }}
            >
              Change in the panel
            </button>
          )}
        </span>
      );
    }
    return editChip(field, shown(value), `Edit ${name}`);
  };

  const draft = action?.draft === true;
  return (
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions -- clicks inside keep the row as it is
    <div
      className="st-open"
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      {action?.description && <p className="st-open-about">{action.description}</p>}

      <Group title="What it does">
        <Row
          label="Action"
          value={
            <>
              <span className="st-open-mono st-open-strong">
                {action?.name ?? text(node.action)}
              </span>
              {action?.runtime && (
                <span className="st-open-quiet">{RUNTIME[action.runtime] ?? action.runtime}</span>
              )}
            </>
          }
          note={
            draft ? (
              <DraftLine
                compact
                className="st-open-draft"
                commands={action.accept_command ? [action.accept_command] : []}
                action={action.name}
              >
                It plans now; a scenario run starts once it is committed in the hub checkout.
              </DraftLine>
            ) : undefined
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

      {(params.length > 0 ||
        bodies.length > 0 ||
        missing.length > 0 ||
        (onSet && unsetServices.length > 0)) && (
        <Group
          title="Values for this step"
          status={
            needCount > 0 ? (
              <span className="st-g-missing">
                <Icon name="circle-alert" size="sm" />
                {needCount} {needCount === 1 ? "needs a value" : "need a value"}
              </span>
            ) : null
          }
        >
          {onSet && unsetServices.map((input) => serviceRow(input.name, "", input.required))}
          {missing.map((input) => (
            <Row
              key={input.name}
              label={<span className="st-open-mono">{input.name}</span>}
              value={
                <>
                  <Needs />
                  {onEditInPanel && (
                    <button
                      type="button"
                      className="st-g-link"
                      onClick={(event) => {
                        event.stopPropagation();
                        onEditInPanel(input.name);
                      }}
                    >
                      Set it in the panel
                    </button>
                  )}
                </>
              }
              note={input.description ?? undefined}
            />
          ))}
          {params.map(([name, value]) => {
            const spec = specOf(name);
            // A reference ($INPUTS.x) stays a token with its edit; a service name is picked.
            if (onSet && isService(name) && typeof value === "string" && !value.includes("$"))
              return serviceRow(name, value, spec?.required ?? false);
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
          {bodies.map(([name, value]) => {
            const body = pretty(value);
            const about = specOf(name)?.description;
            return (
              <li key={name} className="st-g-row st-g-body">
                <span className="st-g-body-head">
                  <span className="st-open-mono">{name}</span>
                  <span className="st-open-quiet">JSON</span>
                  <span className="ah-grow" />
                  {onEditInPanel && (
                    <button
                      type="button"
                      className="st-g-link"
                      onClick={(event) => {
                        event.stopPropagation();
                        onEditInPanel(name);
                      }}
                    >
                      <Icon name="pencil" size="sm" /> Edit {name}
                    </button>
                  )}
                  <CopyButton text={body} label={`Copy ${name}`} compact />
                </span>
                {/* A scrollable region is reached by keyboard. */}
                {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
                <pre className="ah-json st-open-json" tabIndex={0} aria-label={`${name}, as JSON`}>
                  <JsonText source={body} />
                </pre>
                {about && <span className="st-g-note">{about}</span>}
              </li>
            );
          })}
        </Group>
      )}

      {uses.size > 0 && (
        <Group title="Values from earlier">
          {[...uses.entries()].map(([ref, name]) => {
            const scenario = ref.startsWith("$INPUTS.");
            const envValue = scenario && env !== null ? env.values[name] : undefined;
            const kept = keptBefore.find((item) => item.name === name);
            const asked = sources?.inputs.includes(name) ?? false;
            return (
              <Row
                key={ref}
                label={<ValueToken value={ref} />}
                value={
                  <span className="st-open-value-ref">
                    <span className="st-open-quiet">
                      {scenario
                        ? envValue !== undefined
                          ? `Scenario input · ${envValue} from ${env?.name ?? ""}`
                          : asked
                            ? "Scenario input · asked when the scenario run starts"
                            : "Not asked by the scenario"
                        : kept
                          ? `Kept by ${kept.number}`
                          : "Not given by any earlier step"}
                    </span>
                    {!scenario && kept?.step && onGoToStep && (
                      <button
                        type="button"
                        className="st-g-link"
                        onClick={(event) => {
                          event.stopPropagation();
                          onGoToStep(kept.step ?? "");
                        }}
                      >
                        Go to {kept.number}
                      </button>
                    )}
                  </span>
                }
              />
            );
          })}
        </Group>
      )}

      {keeps.length > 0 && (
        <Group title="Keeps for later steps">
          {keeps.map(([name, from]) => (
            <Row
              key={name}
              label={<ValueToken value={`$CTX.${name}`} />}
              value={
                <span className="st-open-quiet">
                  from <TokenText value={written(from)} />
                </span>
              }
            />
          ))}
        </Group>
      )}
    </div>
  );
}

const RUNTIME: Readonly<Record<string, string>> = { python: "Python", shell: "Shell" };

/** A titled group of rows, as a grouped list in system settings; `status` beside its title. */
function Group({
  title,
  status = null,
  children,
}: {
  title: string;
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="st-g-section" aria-label={title}>
      <h4 className="st-g-title">
        {title}
        {status}
      </h4>
      <ul className="st-g">{children}</ul>
    </section>
  );
}

/** One row of a group: its label at the left (a note under it), its value at the right. */
function Row({
  label,
  value,
  note,
  noteText,
}: {
  label: ReactNode;
  value: ReactNode;
  note?: ReactNode;
  /** The note in words, as its tooltip, when the note is more than text. */
  noteText?: string | undefined;
}) {
  return (
    <li className="st-g-row">
      <span className="st-g-label">{label}</span>
      <span className="st-g-value">{value}</span>
      {note && (
        <span className="st-g-note" title={typeof note === "string" ? note : noteText}>
          {note}
        </span>
      )}
    </li>
  );
}

/** A service input's row: its kind where an input's name goes (the input's name moves to the
 * note), the service itself where its value goes. */
function ServiceRow({
  name,
  value,
  required,
  needs,
  options,
  environment,
  onPick,
}: {
  name: string;
  value: string;
  required: boolean;
  /** How a missing value is said (icon and words). */
  needs: ReactNode;
  options: readonly ServiceOption[];
  environment: string | null;
  onPick: (value: string) => void;
}) {
  const { kindSelect, field, about } = useServiceField({
    label: name,
    value,
    options,
    environment,
    onPick,
  });
  const empty = value === "" && required;
  const noteText = [name, empty ? "Needs a value" : required ? "Required" : null, about]
    .filter(Boolean)
    .join(" · ");
  const note = (
    <>
      <span className="st-open-mono">{name}</span>
      {empty ? (
        <>
          {" · "}
          {needs}
        </>
      ) : required ? (
        " · Required"
      ) : null}
      {about ? ` · ${about}` : ""}
    </>
  );
  return <Row label={kindSelect} note={note} noteText={noteText} value={field} />;
}
