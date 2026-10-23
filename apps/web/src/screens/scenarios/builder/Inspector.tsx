import { useId, useState, type ReactNode, type RefObject } from "react";

import {
  Banner,
  Button,
  CopyButton,
  Icon,
  IconButton,
  MenuItem,
  PathText,
  SidePanel,
  type IconName,
} from "../../../components";
import { DraftLine, EffectBadge } from "../parts";
import type { ScenarioPlanRow } from "../queries";
import { maxChecks, pace, stopLines } from "../story";
import { TokenText, ValueToken, cardTitle, tokenOf } from "./CardParts";
import { asStep, kindLook } from "./FlowCanvas";
import {
  OPERATORS,
  conditionFromWords,
  conditionWords,
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

/** A field of the form: the label above, the control, its help and its error. */
function Field({
  label,
  help,
  children,
  error,
  optional = false,
}: {
  label: string;
  help?: ReactNode;
  children: (id: string) => ReactNode;
  error?: string | null | undefined;
  /** Says "(optional)" after the label: required is the default, unmarked. */
  optional?: boolean;
}) {
  const id = useId();
  return (
    <div className="sb-field">
      <label htmlFor={id} className="sb-label">
        {label}
        {optional && <span className="ah-muted"> (optional)</span>}
      </label>
      {children(id)}
      {help && <span className="ah-small ah-muted">{help}</span>}
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

/** A section of the step form: a small heading, then its fields. */
function Section({
  title,
  help,
  children,
}: {
  title: string;
  help?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section className="sb-section-v5" aria-labelledby={id}>
      <h3 id={id} className="sb-section-title">
        {title}
      </h3>
      {help && <p className="sb-section-help">{help}</p>}
      {children}
    </section>
  );
}

/** A closed-by-default part of the form, opened by the app's ghost button. */
function Disclosure({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="sb-disclosure">
      <Button
        variant="ghost"
        size="sm"
        iconRight={open ? "chevron-up" : "chevron-down"}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => {
          setOpen(!open);
        }}
      >
        {label}
      </Button>
      {open && (
        <div id={id} className="sb-disclosure-body">
          {children}
        </div>
      )}
    </div>
  );
}

const SOURCE_GROUP_ICON: Readonly<Record<string, IconName>> = {
  "Scenario inputs": "flag",
  "Kept values": "bookmark",
  Answers: "hand",
  "Earlier outputs": "corner-down-right",
};

/** An input of the step's action: the label above, the value (literal, reference or long text),
 * the button that puts a value from earlier into it, the help and the default. */
function ValueField({
  name,
  required,
  description,
  fallback,
  type,
  value,
  sources,
  onChange,
}: {
  name: string;
  required: boolean;
  description: string | null;
  fallback: Json | undefined;
  type: string;
  value: string;
  sources: readonly ValueSource[];
  onChange: (value: string) => void;
}) {
  const id = useId();
  const helpId = `${id}-help`;
  const [menu, setMenu] = useState(false);
  const token = tokenOf(value);
  const long = type === "object" || type === "array" || /^\s*[[{]/.test(value) || value.length > 40;
  const uses = long ? [...value.matchAll(REFERENCES)].map((match) => match[0]) : [];
  const groups = [...new Set(sources.map((source) => groupOf(source)))];
  const help = [
    description,
    fallback !== null && fallback !== undefined ? `Default: ${shown(fallback)}` : null,
  ].filter(Boolean);
  const pick = (ref: string) => {
    setMenu(false);
    if (long && value !== "" && !token) onChange(`${value}${ref}`);
    else onChange(ref);
  };
  return (
    <div className="sb-field">
      <label htmlFor={id} className="sb-label">
        <span className="ah-mono">{name}</span>
        {!required && <span className="ah-muted"> (optional)</span>}
      </label>
      <div className="sb-value-v5">
        {token ? (
          <span className="sb-token-field">
            <input
              id={id}
              className="ah-input ah-mono"
              readOnly
              value={token.label}
              aria-describedby={help.length > 0 ? helpId : undefined}
              title={token.title}
            />
            <span className="sb-token-overlay" aria-hidden>
              <ValueToken value={value} />
              <span className="ah-muted">{token.title.replace(token.label, "").trim()}</span>
            </span>
            <IconButton
              icon="x"
              size="sm"
              label="Type a value instead"
              onClick={() => {
                onChange("");
              }}
            />
          </span>
        ) : long ? (
          <textarea
            id={id}
            className="ah-input ah-mono sb-textarea"
            rows={3}
            value={value}
            aria-describedby={help.length > 0 ? helpId : undefined}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          />
        ) : (
          <input
            id={id}
            className="ah-input"
            value={value}
            inputMode={type === "integer" || type === "number" ? "numeric" : undefined}
            placeholder={
              fallback !== null && fallback !== undefined ? shown(fallback) : `a ${type || "value"}`
            }
            aria-describedby={help.length > 0 ? helpId : undefined}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          />
        )}
        {sources.length > 0 && (
          <span className="sb-value-pick">
            <IconButton
              icon="corner-down-right"
              label={`Use a value from earlier for ${name}`}
              aria-haspopup="menu"
              aria-expanded={menu}
              onClick={() => {
                setMenu(!menu);
              }}
            />
            {menu && (
              <div
                className="ah-pop sb-value-menu"
                role="menu"
                tabIndex={-1}
                aria-label={`Values from earlier for ${name}`}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.stopPropagation();
                    setMenu(false);
                  }
                }}
              >
                {groups.map((group) => (
                  <div key={group} role="group" aria-label={group}>
                    <div className="sb-menu-group">{group}</div>
                    {sources
                      .filter((source) => groupOf(source) === group)
                      .map((source) => (
                        <MenuItem
                          key={source.ref}
                          icon={SOURCE_GROUP_ICON[group] ?? "corner-down-right"}
                          hint={<span className="ah-small ah-muted">{source.hint}</span>}
                          onClick={() => {
                            pick(source.ref);
                          }}
                        >
                          <span className="ah-mono">{source.label}</span>
                        </MenuItem>
                      ))}
                  </div>
                ))}
              </div>
            )}
          </span>
        )}
      </div>
      {uses.length > 0 && (
        <span className="sb-uses">
          Uses{" "}
          {uses.map((ref, index) => (
            <ValueToken key={`${ref}-${String(index)}`} value={ref} />
          ))}
        </span>
      )}
      {help.length > 0 && (
        <span id={helpId} className="ah-small ah-muted">
          {help.join(" · ")}
        </span>
      )}
    </div>
  );
}

const REFERENCES = /\$(?:INPUTS|CTX)\.[A-Za-z0-9_]+|\$[a-z0-9_-]+\.output(?:\.[A-Za-z0-9_.]+)?/gi;

/** The menu group of a value source, in the design's words. */
function groupOf(source: ValueSource): string {
  const words: Record<ValueSource["group"], string> = {
    "Scenario inputs": "Scenario inputs",
    "Kept earlier": "Kept values",
    "Typed by you": "Answers",
    "Outputs of earlier blocks": "Earlier outputs",
  };
  return words[source.group];
}

const DECISION_WORDS: Readonly<Record<string, string>> = {
  allow: "runs without asking",
  ask: "asks you first",
  deny: "denied",
};

export function BlockInspector({
  document,
  node,
  number,
  library,
  problems,
  mode,
  onChange,
  onClose,
  openerRef,
  onOpenAction,
  plan,
  actionTools,
  footer,
}: {
  document: BuilderDocument;
  node: BuilderNode;
  /** The step's number on the board ("3", "3.1"). */
  number: string | undefined;
  library: readonly LibraryAction[];
  problems: readonly BuilderProblem[];
  mode: "interactive" | "regression";
  onChange: (next: BuilderNode) => void;
  onClose: () => void;
  /** The card that opened the form: focus goes back to it on close. */
  openerRef: RefObject<HTMLElement | null>;
  /** "Open action …": the action's own panel. */
  onOpenAction: (ref: string) => void;
  /** A preview in an environment: what the step would do there. */
  plan: { row: ScenarioPlanRow; environment: string } | null;
  /** Under the action field: make a new action, or ask Claude to write one. */
  actionTools?: ReactNode;
  /** The form's foot: what can be done with the step (delete, duplicate, ask Claude). */
  footer?: ReactNode;
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
  const action = entry?.action ?? null;
  const outputs = (name: string) =>
    library
      .find((item) => item.action.ref === name || item.action.name === name)
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
  const errors = problems.filter((problem) => problem.severity === "error");
  const warnings = problems.filter((problem) => problem.severity !== "error");
  const gives = Object.keys(record(action?.output_format?.properties as Json | undefined));
  const stops = callsAction ? stopLines(asStep(node), action, mode, null) : [];
  const conditionSet = typeof node.when === "string" && node.when !== "";
  return (
    <SidePanel
      layout="inline"
      focusOnOpen={false}
      title={
        <span className="sb-form-title">
          <span
            className="sb-form-eyebrow"
            style={{ ["--kind" as string]: look.tint, ["--kind-soft" as string]: look.soft }}
          >
            <span className="bk-icon" aria-hidden>
              <Icon name={look.icon} size="sm" />
            </span>
            {number ? `Step ${number} · ${look.label}` : look.label}
          </span>
          <span className="sb-form-name">
            <TokenText value={cardTitle(node, action)} />
          </span>
        </span>
      }
      closeLabel={`Close step ${node.id}`}
      onClose={onClose}
      openerRef={openerRef}
      footer={footer}
    >
      <section className="sb-inspector-v5" aria-label={`Inspector: ${look.label} ${node.id}`}>
        <div className="sb-form-id">
          <span className="ah-mono ah-small ah-muted">{node.id}</span>
          <CopyButton text={node.id} label={`Copy the id ${node.id}`} compact />
        </div>
        {errors.length > 0 && (
          <Banner tone="error" live={false}>
            {errors.map((problem, index) => (
              <div key={index}>{problem.message}</div>
            ))}
          </Banner>
        )}
        {warnings.length > 0 && (
          <Banner tone="warning" live={false}>
            {warnings.map((problem, index) => (
              <div key={index}>{problem.message}</div>
            ))}
          </Banner>
        )}

        <Section title="Name">
          <Field
            label="Step name"
            optional
            help="Shown on the card. Without one, the card shows what the action does."
          >
            {(fieldId) => (
              <input
                id={fieldId}
                className="ah-input"
                value={typeof node.description === "string" ? node.description : ""}
                placeholder={cardTitle({ ...node, description: "" }, action)}
                onChange={(event) => {
                  set("description", event.target.value);
                }}
              />
            )}
          </Field>
        </Section>

        {callsAction && (
          <Section title={node.type === "expect" ? "What it reads" : "What it runs"}>
            <Field
              label={node.type === "expect" ? "Reads with" : "Action"}
              help={
                node.type === "expect"
                  ? "Only actions that only read can check a state."
                  : undefined
              }
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
                  {ref !== "" && !entry && <option value={ref}>{ref} (not in this hub)</option>}
                  {library
                    .filter((item) => node.type !== "expect" || item.action.effect === "read")
                    .map((item) => (
                      <option
                        key={item.action.ref}
                        value={item.action.name === ref ? ref : item.action.ref}
                      >
                        {item.action.ref} · {item.action.effect ?? "effect not declared"}
                        {item.action.draft ? " · draft" : ""}
                      </option>
                    ))}
                </select>
              )}
            </Field>
            {action && (
              <div className="sb-action-well">
                {action.description && <p className="ah-small">{action.description}</p>}
                <dl className="sc-values">
                  <div className="sc-value">
                    <dt>Runs</dt>
                    <dd>
                      {action.runtime === "python" ? "Python" : "Shell"} ·{" "}
                      <span className="ah-mono">
                        <PathText path={action.script ?? ""} max={40} dimDir />
                      </span>
                    </dd>
                  </div>
                  <div className="sc-value">
                    <dt>Effect</dt>
                    <dd>
                      <EffectBadge effect={action.effect} words />
                    </dd>
                  </div>
                  <div className="sc-value">
                    <dt>Gives</dt>
                    <dd>{gives.length > 0 ? gives.join(", ") : "No output declared"}</dd>
                  </div>
                  {action.timeout && (
                    <div className="sc-value">
                      <dt>Timeout</dt>
                      <dd>{pace(action.timeout)}</dd>
                    </div>
                  )}
                  {plan && (
                    <div className="sc-value">
                      <dt>In {plan.environment}</dt>
                      <dd>
                        {DECISION_WORDS[plan.row.decision] ?? plan.row.decision}
                        {plan.row.reason ? ` (${plan.row.reason})` : ""}: {plan.row.plan}
                      </dd>
                    </div>
                  )}
                </dl>
                {action.draft && (
                  <DraftLine
                    commands={action.accept_command ? [action.accept_command] : []}
                    action={action.name}
                    then="plan again"
                  />
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    onOpenAction(action.ref);
                  }}
                >
                  Open action {action.name}
                </Button>
              </div>
            )}
            {actionTools && <div className="sb-action-tools">{actionTools}</div>}
          </Section>
        )}

        {node.type === "expect" && (
          <>
            <Section title="Done when">
              <ConditionBuilder
                label="Done when"
                value={typeof node.until_when === "string" ? node.until_when : ""}
                fields={selfFields}
                onChange={(value) => {
                  set("until_when", value === "" ? "" : value);
                }}
              />
            </Section>
            <Section title="Timing">
              <div className="ah-env-grid">
                <Field label="Check every" help="At least 5 s." error={problemOf("every")}>
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
                <Field label="For up to" help="At most 24 h." error={problemOf("timeout")}>
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
                  <span className="ah-small ah-muted">
                    At most {maxChecks(node.every, node.timeout)} checks.
                  </span>
                )}
            </Section>
          </>
        )}

        {callsAction && action && action.inputs.length > 0 && (
          <Section title="Inputs" help={`What this step gives ${action.name}.`}>
            {action.inputs.map((input) => {
              const current = given[input.name];
              return (
                <ValueField
                  key={input.name}
                  name={input.name}
                  required={input.required}
                  description={input.description ?? null}
                  fallback={input.default as Json | undefined}
                  type={input.type}
                  value={
                    current === undefined
                      ? ""
                      : typeof current === "string"
                        ? current
                        : JSON.stringify(current)
                  }
                  sources={sources}
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
              );
            })}
          </Section>
        )}

        {node.type === "approval" && (
          <>
            <Section title="What you do">
              <Field
                label="What to do"
                help="What the person does by hand before answering. Scenario inputs and kept values can go in the text."
              >
                {(fieldId) => (
                  <textarea
                    id={fieldId}
                    className="ah-input sb-textarea"
                    rows={5}
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
                Ask me to type a value (an id, a reference); later steps can use it.
              </label>
            </Section>
            <Section title="Answers">
              {(Array.isArray(node.decisions) ? node.decisions : []).map((decision, index) => {
                const item = record(decision);
                const list = Array.isArray(node.decisions) ? [...node.decisions] : [];
                return (
                  <div key={index} className="sb-answer">
                    <Field
                      label="Label"
                      help={<span className="ah-mono">{text(item.id, "")}</span>}
                    >
                      {(fieldId) => (
                        <input
                          id={fieldId}
                          className="ah-input"
                          value={text(item.label, "")}
                          onChange={(event) => {
                            list[index] = { ...item, label: event.target.value };
                            set("decisions", list);
                          }}
                        />
                      )}
                    </Field>
                    <IconButton
                      icon="x"
                      size="sm"
                      label={`Remove answer ${text(item.label, text(item.id, ""))}`}
                      onClick={() => {
                        set(
                          "decisions",
                          list.filter((_, at) => at !== index),
                        );
                      }}
                    />
                  </div>
                );
              })}
              <Button
                variant="ghost"
                size="sm"
                icon="plus"
                onClick={() => {
                  const list = Array.isArray(node.decisions) ? [...node.decisions] : [];
                  list.push({ id: `answer-${String(list.length + 1)}`, label: "New answer" });
                  set("decisions", list);
                }}
              >
                Add an answer
              </Button>
            </Section>
          </>
        )}

        {node.type === "wait" && (
          <Section title="Pause">
            <Field
              label="Pause for"
              help="A duration: 30s, 5m, 1h; at most 7 days."
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
          </Section>
        )}

        {node.type === "loop_group" && (
          <Section title="Repeat">
            <ConditionBuilder
              label="Repeat until"
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
          </Section>
        )}

        {node.type === "include" && (
          <Section title="Scenario">
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
          </Section>
        )}

        {callsAction && (
          <Section
            title="Keep for later"
            help="Keep a field of the output so later steps can use it."
          >
            {Object.entries(capture).map(([name, from]) => (
              <div key={name} className="sb-kept-row">
                <ValueToken value={`$CTX.${name}`} />
                <span className="ah-small ah-muted">
                  ← {shown(from).replace(/^\$self\.output\.?/, "") || "output"}
                </span>
                <span className="ah-grow" />
                <IconButton
                  icon="x"
                  size="sm"
                  label={`Stop keeping ${name}`}
                  onClick={() => {
                    const next = without(capture, name);
                    set("capture", Object.keys(next).length > 0 ? next : undefined);
                  }}
                />
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
                <option value="">Keep a field</option>
                {entry.output_fields.map((field) => (
                  <option key={field.path} value={field.path}>
                    {field.path}
                    {field.type ? ` (${field.type})` : ""}
                  </option>
                ))}
              </select>
            )}
          </Section>
        )}

        <div className="sb-more">
          <Disclosure
            label={
              conditionSet
                ? `More: only if ${conditionWords(text(node.when))}`
                : "More: only if, order and id"
            }
          >
            <ConditionBuilder
              label="Only if"
              value={typeof node.when === "string" ? node.when : ""}
              fields={whenFields}
              onChange={(value) => {
                set("when", value);
              }}
            />
            <Field label="Runs after" help="Set by where it sits on the canvas.">
              {() => (
                <span className="ah-mono ah-small">
                  {dependsOn(node).join(", ") || "the start"}
                </span>
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
          </Disclosure>
          {stops.length > 0 && (
            <Disclosure
              label={`Where it can stop: ${String(stops.length)} ${stops.length === 1 ? "way" : "ways"}`}
            >
              <ul className="sb-stops">
                {stops.map((line) => (
                  <li key={line.key}>
                    <Icon name={line.icon} size="sm" /> {line.text}
                  </li>
                ))}
              </ul>
            </Disclosure>
          )}
        </div>
      </section>
    </SidePanel>
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
