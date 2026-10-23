import { useId, useState, type ReactNode } from "react";

import { Button, Icon } from "../../../components";
import { EffectBadge } from "../parts";
import { maxChecks, pace, stopLines } from "../story";
import { asStep, kindLook } from "./FlowCanvas";
import {
  OPERATORS,
  conditionFromWords,
  dependsOn,
  formatCondition,
  parseCondition,
  refInWords,
  shown,
  text,
  valueSources,
  without,
  type BuilderDocument,
  type BuilderNode,
  type ConditionRow,
  type Json,
  type ValueSource,
} from "./model";
import type { BuilderProblem, LibraryAction } from "./useScenarioDraft";

/* The inspector: the selected block's fields, one per engine key, in words; values are picked
 * from what exists upstream (inputs, kept values, typed answers, earlier outputs) instead of
 * typed as references, and conditions are rows. With no block selected, the scenario's own
 * settings (description, inputs). */

type Record_ = Record<string, Json>;

function record(value: Json | undefined): Record_ {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

function Field({
  label,
  help,
  children,
  error,
}: {
  label: string;
  help?: ReactNode;
  children: (id: string) => ReactNode;
  error?: string | null | undefined;
}) {
  const id = useId();
  return (
    <div className="sb-field">
      <label htmlFor={id} className="ah-small">
        {label}
      </label>
      {children(id)}
      {help && <span className="ah-small ah-subtle">{help}</span>}
      {error && (
        <span className="ah-small sb-field-error">
          <Icon name="circle-x" size="sm" /> {error}
        </span>
      )}
    </div>
  );
}

/** A literal or a picked reference: the text field, and a picker of what exists upstream. */
export function ValueInput({
  id,
  value,
  sources,
  onChange,
  placeholder,
  label,
}: {
  id?: string;
  /** The field's accessible name when no visible label points at it. */
  label?: string;
  value: string;
  sources: readonly ValueSource[];
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const words = refInWords(value);
  const groups = [...new Set(sources.map((source) => source.group))];
  return (
    <span className="sb-value">
      {words.ref ? (
        <span className="sb-chip sb-chip-ref" title={value}>
          <Icon name="bookmark" size="sm" /> {words.text}
          <button
            type="button"
            aria-label={`Clear ${words.text}`}
            onClick={() => {
              onChange("");
            }}
          >
            <Icon name="x" size="sm" />
          </button>
        </span>
      ) : (
        <input
          id={id}
          className="ah-input"
          aria-label={label}
          value={value}
          placeholder={placeholder ?? "a value"}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
      {sources.length > 0 && (
        <select
          className="ah-input sb-pick"
          aria-label="Insert a value from earlier"
          value=""
          onChange={(event) => {
            if (event.target.value) onChange(event.target.value);
          }}
        >
          <option value="">＋ from…</option>
          {groups.map((group) => (
            <optgroup key={group} label={group}>
              {sources
                .filter((source) => source.group === group)
                .map((source) => (
                  <option key={source.ref} value={source.ref}>
                    {source.label} ({source.hint})
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
      )}
    </span>
  );
}

/** A condition typed in words, turned into rows the person checks (never sent anywhere). */
function WordsField({
  fields,
  onRows,
}: {
  fields: readonly { ref: string; label: string }[];
  onRows: (rows: ConditionRow[][]) => void;
}) {
  const [words, setWords] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [read, setRead] = useState(false);
  const use = () => {
    const result = conditionFromWords(words, fields);
    if (result.ok) {
      onRows(result.groups);
      setProblem(null);
      setRead(true);
    } else {
      setProblem(result.problem);
      setRead(false);
    }
  };
  if (fields.length === 0) return null;
  return (
    <div className="ah-stack" style={{ gap: 4 }}>
      <span className="sb-words">
        <input
          className="ah-input"
          aria-label="Type the condition in words"
          placeholder={`Type it: ${fields[0]?.label ?? "field"} is …${fields[1] ? ` and ${fields[1].label} is not …` : ""}`}
          value={words}
          onChange={(event) => {
            setWords(event.target.value);
            setRead(false);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              use();
            }
          }}
        />
        <Button size="sm" disabled={words.trim() === ""} onClick={use}>
          Use
        </Button>
      </span>
      {problem && (
        <span className="ah-small sb-field-error">
          <Icon name="circle-x" size="sm" /> {problem}
        </span>
      )}
      {read && (
        <span className="ah-small ah-subtle">Read from your words: check the rows below.</span>
      )}
    </div>
  );
}

/** "Done when" / "Only if": or-groups of and-rows, the grammar's own shape. */
export function ConditionBuilder({
  label,
  value,
  fields,
  onChange,
}: {
  label: string;
  value: string;
  fields: readonly { ref: string; label: string }[];
  onChange: (value: string) => void;
}) {
  const parsed = parseCondition(value);
  const [raw, setRaw] = useState(parsed === null);
  if (parsed === null || raw) {
    return (
      <Field label={label} help="The condition as written: `$ref op literal`, joined by && and ||.">
        {(id) => (
          <input
            id={id}
            className="ah-input ah-mono"
            value={value}
            onChange={(event) => {
              onChange(event.target.value);
            }}
            onBlur={() => {
              if (parseCondition(value) !== null) setRaw(false);
            }}
          />
        )}
      </Field>
    );
  }
  const groups = parsed.length === 0 ? [] : parsed;
  const write = (next: ConditionRow[][]) => {
    onChange(formatCondition(next));
  };
  const blank: ConditionRow = { field: fields[0]?.ref ?? "", op: "==", value: "" };
  return (
    <div className="sb-field">
      <WordsField
        fields={fields}
        onRows={(rows) => {
          write(rows);
        }}
      />
      <span className="ah-small">
        {label}{" "}
        {groups.length > 1
          ? "(any of these)"
          : groups[0] && groups[0].length > 1
            ? "(all of these)"
            : ""}
      </span>
      {groups.map((group, g) => (
        <div key={g} className="sb-cond-group">
          {g > 0 && <span className="ah-small ah-subtle">or</span>}
          {group.map((row, r) => (
            <div key={r} className="sb-cond-row">
              {r > 0 && <span className="ah-small ah-subtle">and</span>}
              <select
                className="ah-input"
                aria-label="Field"
                value={row.field}
                onChange={(event) => {
                  write(
                    groups.map((items, gi) =>
                      items.map((item, ri) =>
                        gi === g && ri === r ? { ...item, field: event.target.value } : item,
                      ),
                    ),
                  );
                }}
              >
                {!fields.some((field) => field.ref === row.field) && (
                  <option value={row.field}>{refInWords(row.field).text}</option>
                )}
                {fields.map((field) => (
                  <option key={field.ref} value={field.ref}>
                    {field.label}
                  </option>
                ))}
              </select>
              <select
                className="ah-input"
                aria-label="Operator"
                value={row.op}
                onChange={(event) => {
                  write(
                    groups.map((items, gi) =>
                      items.map((item, ri) =>
                        gi === g && ri === r ? { ...item, op: event.target.value } : item,
                      ),
                    ),
                  );
                }}
              >
                {OPERATORS.map((operator) => (
                  <option key={operator.op} value={operator.op}>
                    {operator.words}
                  </option>
                ))}
              </select>
              <input
                className="ah-input"
                aria-label="Value"
                value={row.value}
                onChange={(event) => {
                  write(
                    groups.map((items, gi) =>
                      items.map((item, ri) =>
                        gi === g && ri === r ? { ...item, value: event.target.value } : item,
                      ),
                    ),
                  );
                }}
              />
              <button
                type="button"
                className="sb-icon-btn"
                aria-label="Remove this condition"
                onClick={() => {
                  write(
                    groups
                      .map((items, gi) => (gi === g ? items.filter((_, ri) => ri !== r) : items))
                      .filter((items) => items.length > 0),
                  );
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
              write(groups.map((items, gi) => (gi === g ? [...items, blank] : items)));
            }}
          >
            and
          </Button>
        </div>
      ))}
      <span className="ah-row" style={{ gap: 6 }}>
        <Button
          size="sm"
          icon="plus"
          disabled={fields.length === 0}
          onClick={() => {
            write([...groups, [blank]]);
          }}
        >
          {groups.length === 0 ? "Add a condition" : "or"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setRaw(true);
          }}
        >
          Write it by hand
        </Button>
      </span>
      {fields.length === 0 && (
        <span className="ah-small ah-subtle">
          Choose an action with output fields first: a condition compares one of its fields.
        </span>
      )}
    </div>
  );
}

const TRIGGER_WORDS: readonly [string, string][] = [
  ["all_success", "Every block before it finished"],
  ["one_success", "At least one block before it finished"],
  ["none_failed_min_one_success", "None failed and at least one finished (after a branch)"],
  ["all_done", "Every block before it ended, even if one failed"],
];

export function BlockInspector({
  document,
  node,
  library,
  problems,
  mode,
  onChange,
  onDelete,
  onMove,
  onClose,
  summary,
  actionTools,
}: {
  document: BuilderDocument;
  node: BuilderNode;
  library: readonly LibraryAction[];
  problems: readonly BuilderProblem[];
  mode: "interactive" | "regression";
  onChange: (next: BuilderNode) => void;
  onDelete: () => void;
  /** Moves the block in its list; absent where dragging moves blocks. */
  onMove?: ((by: -1 | 1) => void) | undefined;
  onClose: () => void;
  /** What the step does, read-only, above the form (its facts). */
  summary?: ReactNode;
  /** Under the action field: make a new action, or ask Claude to write one. */
  actionTools?: ReactNode;
}) {
  const look = kindLook(node.type);
  const [id, setId] = useState(node.id);
  const [shownFor, setShownFor] = useState(node.id);
  if (shownFor !== node.id) {
    setShownFor(node.id);
    setId(node.id);
  }
  const set = (key: string, value: Json | undefined) => {
    const next: Record_ =
      value === undefined || value === "" ? without(node, key) : { ...node, [key]: value };
    onChange(next as BuilderNode);
  };
  const ref = typeof node.action === "string" ? node.action : "";
  const entry = library.find((item) => item.action.ref === ref || item.action.name === ref) ?? null;
  const outputs = (action: string) =>
    library
      .find((item) => item.action.ref === action || item.action.name === action)
      ?.output_fields.map((field) => field.path) ?? [];
  const sources = valueSources(document, node.id, outputs);
  const given = record(node.with);
  const capture = record(node.capture);
  const callsAction = node.type === "action" || node.type === "expect";
  const selfFields =
    entry?.output_fields.map((field) => ({
      ref: `$self.output.${field.path}`,
      label: field.path,
    })) ?? [];
  const whenFields = sources.map((source) => ({
    ref: source.ref,
    label: `${source.label} (${source.hint})`,
  }));
  const problemOf = (key: string) =>
    problems.find(
      (problem) =>
        problem.severity === "error" &&
        (problem.key === key || problem.key?.endsWith(`.${key}`) === true),
    )?.message;
  return (
    <section className="sb-inspector" aria-label={`Inspector: ${look.label} ${node.id}`}>
      <header className="sb-inspector-head" style={{ ["--kind" as string]: look.tint }}>
        <span className="sb-kind" aria-hidden>
          <Icon name={look.icon} size="sm" />
        </span>
        <b>{look.label}</b>
        <span className="ah-mono ah-small ah-muted">{node.id}</span>
        <span className="ah-grow" />
        {onMove && (
          <>
            <button
              type="button"
              className="sb-icon-btn"
              aria-label="Move up"
              onClick={() => {
                onMove(-1);
              }}
            >
              <Icon name="arrow-up" size="sm" />
            </button>
            <button
              type="button"
              className="sb-icon-btn"
              aria-label="Move down"
              onClick={() => {
                onMove(1);
              }}
            >
              <Icon name="arrow-down" size="sm" />
            </button>
          </>
        )}
        <button
          type="button"
          className="sb-icon-btn"
          aria-label={`Delete ${node.id}`}
          onClick={onDelete}
        >
          <Icon name="trash" size="sm" />
        </button>
        <button
          type="button"
          className="sb-icon-btn"
          aria-label="Close the inspector"
          onClick={onClose}
        >
          <Icon name="x" size="sm" />
        </button>
      </header>
      {problems.filter((problem) => problem.severity === "error").length > 0 && (
        <ul className="sb-problems">
          {problems.map((problem, index) => (
            <li key={index} data-severity={problem.severity}>
              <Icon name={problem.severity === "error" ? "circle-x" : "triangle-alert"} size="sm" />
              {problem.message}
            </li>
          ))}
        </ul>
      )}
      <div className="sb-inspector-body">
        {summary && <div className="sb-summary">{summary}</div>}
        {callsAction && (
          <>
            <Field
              label={node.type === "expect" ? "Reads with" : "Action"}
              help={entry ? entry.action.description : "Pick an action of this hub."}
              error={problemOf("action")}
            >
              {(fieldId) => (
                <select
                  id={fieldId}
                  className="ah-input"
                  value={ref}
                  onChange={(event) => {
                    set("action", event.target.value);
                  }}
                >
                  <option value="">Choose an action</option>
                  {library
                    .filter((item) => node.type !== "expect" || item.action.effect === "read")
                    .map((item) => (
                      <option
                        key={item.action.ref}
                        value={item.action.name === ref ? ref : item.action.ref}
                      >
                        {item.action.ref} · {item.action.effect}
                        {item.action.draft ? " · draft" : ""}
                      </option>
                    ))}
                </select>
              )}
            </Field>
            {actionTools && <div className="sb-action-tools">{actionTools}</div>}
            {entry && (
              <div className="ah-row ah-small" style={{ gap: 8 }}>
                <EffectBadge effect={entry.action.effect} />
                <span className="ah-muted ah-mono">{entry.action.script}</span>
              </div>
            )}
            {entry && entry.action.inputs.length > 0 && (
              <div className="sb-field">
                <span className="ah-small">Values</span>
                {entry.action.inputs.map((input) => {
                  const current = given[input.name];
                  return (
                    <div key={input.name} className="sb-value-row">
                      <span className="ah-mono ah-small" title={input.description ?? undefined}>
                        {input.name}
                        {input.required ? " *" : ""}
                      </span>
                      <ValueInput
                        label={`Value of ${input.name}`}
                        value={
                          current === undefined
                            ? ""
                            : typeof current === "string"
                              ? current
                              : JSON.stringify(current)
                        }
                        sources={sources}
                        placeholder={
                          input.default !== null && input.default !== undefined
                            ? `default: ${JSON.stringify(input.default)}`
                            : input.type
                        }
                        onChange={(value) => {
                          const next =
                            value === ""
                              ? without(given, input.name)
                              : {
                                  ...given,
                                  [input.name]:
                                    input.type === "integer" && /^-?\d+$/.test(value)
                                      ? Number(value)
                                      : value,
                                };
                          set("with", Object.keys(next).length > 0 ? next : undefined);
                        }}
                      />
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}

        {node.type === "expect" && (
          <>
            <div className="sb-two">
              <Field label="Check every" help="At least 5s." error={problemOf("every")}>
                {(fieldId) => (
                  <input
                    id={fieldId}
                    className="ah-input ah-mono"
                    value={text(node.every, "")}
                    onChange={(event) => {
                      set("every", event.target.value);
                    }}
                  />
                )}
              </Field>
              <Field label="For up to" help="At most 24h." error={problemOf("timeout")}>
                {(fieldId) => (
                  <input
                    id={fieldId}
                    className="ah-input ah-mono"
                    value={text(node.timeout, "")}
                    onChange={(event) => {
                      set("timeout", event.target.value);
                    }}
                  />
                )}
              </Field>
            </div>
            {typeof node.every === "string" &&
              typeof node.timeout === "string" &&
              maxChecks(node.every, node.timeout) !== null && (
                <span className="ah-small ah-subtle">
                  At most {maxChecks(node.every, node.timeout)} checks.
                </span>
              )}
            <ConditionBuilder
              label="Done when"
              value={typeof node.until_when === "string" ? node.until_when : ""}
              fields={selfFields}
              onChange={(value) => {
                set("until_when", value === "" ? "" : value);
              }}
            />
          </>
        )}

        {node.type === "approval" && (
          <>
            <Field label="What to do" help="What the person does by hand before answering.">
              {(fieldId) => (
                <textarea
                  id={fieldId}
                  className="ah-input"
                  rows={4}
                  value={text(node.message, "")}
                  onChange={(event) => {
                    set("message", event.target.value);
                  }}
                />
              )}
            </Field>
            <label className="ah-row ah-small" style={{ gap: 6 }}>
              <input
                type="checkbox"
                checked={node.capture_response === true}
                onChange={(event) => {
                  set("capture_response", event.target.checked ? true : undefined);
                }}
              />
              Ask me to type a value (an id, a reference); later blocks can use it.
            </label>
            <div className="sb-field">
              <span className="ah-small">Answers</span>
              {(Array.isArray(node.decisions) ? node.decisions : []).map((decision, index) => {
                const item = record(decision);
                return (
                  <div key={index} className="sb-value-row">
                    <input
                      className="ah-input ah-mono"
                      aria-label="Answer id"
                      value={text(item.id, "")}
                      onChange={(event) => {
                        const list = [...(node.decisions as Json[])];
                        list[index] = { ...item, id: event.target.value };
                        set("decisions", list);
                      }}
                    />
                    <input
                      className="ah-input"
                      aria-label="Answer label"
                      value={text(item.label, "")}
                      onChange={(event) => {
                        const list = [...(node.decisions as Json[])];
                        list[index] = { ...item, label: event.target.value };
                        set("decisions", list);
                      }}
                    />
                  </div>
                );
              })}
            </div>
          </>
        )}

        {node.type === "wait" && (
          <Field
            label="Wait for"
            help="A duration: 30s, 5m, 1h (at most 7d)."
            error={problemOf("duration")}
          >
            {(fieldId) => (
              <input
                id={fieldId}
                className="ah-input ah-mono"
                value={text(node.duration, "")}
                onChange={(event) => {
                  set("duration", event.target.value);
                }}
              />
            )}
          </Field>
        )}

        {node.type === "loop_group" && (
          <>
            <Field label="At most (rounds)">
              {(fieldId) => (
                <input
                  id={fieldId}
                  className="ah-input"
                  type="number"
                  min={1}
                  max={50}
                  value={Number(text(node.max_iterations, "1"))}
                  onChange={(event) => {
                    set("max_iterations", Number(event.target.value));
                  }}
                />
              )}
            </Field>
            <ConditionBuilder
              label="Until"
              value={typeof node.until_when === "string" ? node.until_when : ""}
              fields={(Array.isArray(node.nodes) ? (node.nodes as BuilderNode[]) : []).flatMap(
                (inner) =>
                  outputs(text(inner.action, "")).map((path) => ({
                    ref: `$${inner.id}.output.${path}`,
                    label: `${inner.id} · ${path}`,
                  })),
              )}
              onChange={(value) => {
                set("until_when", value);
              }}
            />
          </>
        )}

        {node.type === "include" && (
          <Field label="Scenario" help="Another scenario of this pack; its steps run here.">
            {(fieldId) => (
              <input
                id={fieldId}
                className="ah-input ah-mono"
                value={text(node.include, "")}
                onChange={(event) => {
                  set("include", event.target.value);
                }}
              />
            )}
          </Field>
        )}

        {callsAction && (
          <details className="sb-section">
            <summary>Keep for later</summary>
            <div className="sb-field">
              <span className="ah-small ah-subtle">
                A value of the output that later blocks can use.
              </span>
              {Object.entries(capture).map(([name, from]) => (
                <div key={name} className="sb-value-row">
                  <span className="sb-chip sb-chip-kept">
                    <Icon name="bookmark" size="sm" /> {name}
                  </span>
                  <span className="ah-small ah-muted">
                    ← {shown(from).replace(/^\$self\.output\.?/, "") || "output"}
                  </span>
                  <button
                    type="button"
                    className="sb-icon-btn"
                    aria-label={`Stop keeping ${name}`}
                    onClick={() => {
                      const next = without(capture, name);
                      set("capture", Object.keys(next).length > 0 ? next : undefined);
                    }}
                  >
                    <Icon name="x" size="sm" />
                  </button>
                </div>
              ))}
              {entry && entry.output_fields.length > 0 && (
                <select
                  className="ah-input"
                  aria-label="Keep a field of the output"
                  value=""
                  onChange={(event) => {
                    const path = event.target.value;
                    if (!path) return;
                    const name = path.replace(/[^a-z0-9_]/gi, "_").toLowerCase();
                    set("capture", { ...capture, [name]: `$self.output.${path}` });
                  }}
                >
                  <option value="">＋ Keep a field…</option>
                  {entry.output_fields.map((field) => (
                    <option key={field.path} value={field.path}>
                      {field.path}
                      {field.type ? ` (${field.type})` : ""}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </details>
        )}
        <details className="sb-section">
          <summary>Only if, and what it waits for</summary>
          <ConditionBuilder
            label="Only if"
            value={typeof node.when === "string" ? node.when : ""}
            fields={whenFields}
            onChange={(value) => {
              set("when", value);
            }}
          />
          <Field
            label="Runs after"
            help="The blocks it waits for (set by where it sits on the canvas)."
          >
            {() => (
              <span className="ah-mono ah-small">{dependsOn(node).join(", ") || "the start"}</span>
            )}
          </Field>
          {dependsOn(node).length > 1 && (
            <Field label="Runs when">
              {(fieldId) => (
                <select
                  id={fieldId}
                  className="ah-input"
                  value={text(node.trigger_rule, "all_success")}
                  onChange={(event) => {
                    set(
                      "trigger_rule",
                      event.target.value === "all_success" ? undefined : event.target.value,
                    );
                  }}
                >
                  {TRIGGER_WORDS.map(([rule, words]) => (
                    <option key={rule} value={rule}>
                      {words}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          )}
        </details>
        {callsAction && (
          <details className="sb-section" open>
            <summary>Where it can stop</summary>
            <div className="sb-field">
              <ul className="sb-stops">
                {stopLines(asStep(node), entry?.action ?? null, mode, null).map((line) => (
                  <li key={line.key}>
                    <Icon name={line.icon} size="sm" /> {line.text}
                  </li>
                ))}
              </ul>
            </div>
          </details>
        )}
        <details className="sb-section">
          <summary>Name and id</summary>
          <Field label="Name" help="What this block does, in a few words. Shown on the block.">
            {(fieldId) => (
              <input
                id={fieldId}
                className="ah-input"
                value={typeof node.description === "string" ? node.description : ""}
                placeholder="e.g. Fetch the new records"
                onChange={(event) => {
                  set("description", event.target.value);
                }}
              />
            )}
          </Field>
          <Field label="Id" help="Unique, kebab-case. Renaming updates what waits for it.">
            {(fieldId) => (
              <input
                id={fieldId}
                className="ah-input ah-mono"
                value={id}
                onChange={(event) => {
                  setId(event.target.value);
                }}
                onBlur={() => {
                  if (id !== node.id && /^[a-z][a-z0-9-]*$/.test(id)) onChange({ ...node, id });
                  else setId(node.id);
                }}
              />
            )}
          </Field>
        </details>
        {node.type === "expect" && typeof node.timeout === "string" && (
          <span className="ah-small ah-subtle">Runs up to {pace(node.timeout)}.</span>
        )}
      </div>
    </section>
  );
}

/** The scenario's own settings: its description and its inputs. */
export function ScenarioSettings({
  document,
  onChange,
  onClose,
}: {
  document: BuilderDocument;
  onChange: (next: BuilderDocument) => void;
  onClose?: () => void;
}) {
  const inputs = record(document.inputs);
  const setInputs = (next: Record_) => {
    const copy = { ...document };
    if (Object.keys(next).length === 0) delete copy.inputs;
    else copy.inputs = next;
    onChange(copy);
  };
  return (
    <section className="sb-inspector" aria-label="Scenario settings">
      <header className="sb-inspector-head">
        <Icon name="settings" size="sm" />
        <b>Scenario: description and inputs</b>
        <span className="ah-grow" />
        {onClose && (
          <button type="button" className="sb-icon-btn" aria-label="Close" onClick={onClose}>
            <Icon name="x" size="sm" />
          </button>
        )}
      </header>
      <div className="sb-inspector-body">
        <Field label="Description" help="When to use this scenario, in one sentence.">
          {(id) => (
            <textarea
              id={id}
              className="ah-input"
              rows={3}
              value={typeof document.description === "string" ? document.description : ""}
              onChange={(event) => {
                onChange({ ...document, description: event.target.value });
              }}
            />
          )}
        </Field>
        <div className="sb-field">
          <span className="ah-small">Inputs</span>
          <span className="ah-small ah-subtle">What you give the scenario when you run it.</span>
          {Object.entries(inputs).map(([name, spec]) => {
            const item = record(spec);
            return (
              <div key={name} className="sb-input-row">
                <span className="ah-mono ah-small">{name}</span>
                <select
                  className="ah-input"
                  aria-label={`Type of ${name}`}
                  value={text(item.type, "string")}
                  onChange={(event) => {
                    setInputs({ ...inputs, [name]: { ...item, type: event.target.value } });
                  }}
                >
                  {["string", "integer", "number", "boolean"].map((type) => (
                    <option key={type}>{type}</option>
                  ))}
                </select>
                <label className="ah-row ah-small" style={{ gap: 4 }}>
                  <input
                    type="checkbox"
                    checked={item.required === true}
                    onChange={(event) => {
                      const next = { ...item };
                      if (event.target.checked) next.required = true;
                      else delete next.required;
                      setInputs({ ...inputs, [name]: next });
                    }}
                  />
                  required
                </label>
                <button
                  type="button"
                  className="sb-icon-btn"
                  aria-label={`Remove input ${name}`}
                  onClick={() => {
                    setInputs(without(inputs, name));
                  }}
                >
                  <Icon name="x" size="sm" />
                </button>
              </div>
            );
          })}
          <NewInput
            onAdd={(name) => {
              setInputs({ ...inputs, [name]: { type: "string", required: true } });
            }}
          />
        </div>
      </div>
    </section>
  );
}

function NewInput({ onAdd }: { onAdd: (name: string) => void }) {
  const [name, setName] = useState("");
  const ok = /^[a-z][a-z0-9_]*$/.test(name);
  return (
    <form
      className="sb-new-input"
      onSubmit={(event) => {
        event.preventDefault();
        if (ok) {
          onAdd(name);
          setName("");
        }
      }}
    >
      <input
        className="ah-input ah-mono"
        aria-label="New input name"
        placeholder="new_input"
        value={name}
        onChange={(event) => {
          setName(event.target.value);
        }}
      />
      <Button size="sm" type="submit" icon="plus" disabled={!ok}>
        Add input
      </Button>
    </form>
  );
}
