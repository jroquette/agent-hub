import { useState, type ReactNode } from "react";

import { Button, Icon, IconButton, PathText } from "../../../components";
import { shown, text, type BuilderDocument, type Json } from "./model";

/* The Variables tab (scenario builder v6): every value the scenario uses, grouped by where it
 * comes from in the chosen environment: asked when the scenario run starts, the environment's
 * own values (non-secret, kept in hub.local.json or hub.json), and the values steps keep for
 * later ones. Selecting a variable marks the steps that use it. */

export interface KeptValue {
  name: string;
  /** The step that keeps it, and its number in the list. */
  step: string;
  number: string;
}

export interface VariablesPanelProps {
  document: BuilderDocument;
  environment: string | null;
  /** The environment's values; null when they cannot be read. */
  environmentValues: Readonly<Record<string, string>> | null;
  kept: readonly KeptValue[];
  /** How many steps use each variable. */
  usage: ReadonlyMap<string, number>;
  /** How many `x: $INPUTS.x` repeats the steps hold (values they get anyway). */
  repeats: number;
  selected: string | null;
  onSelect: (name: string | null) => void;
  onEditInputs: () => void;
  onRemoveRepeats: () => void;
  /** Moves these run inputs' defaults into the environment at once, then drops the repeats. */
  onKeepAll: ((names: readonly string[]) => Promise<void>) | null;
  /** How many steps the scenario has (a value most of them use belongs to the environment). */
  stepCount: number;
  /** Saves an environment value (null removes it); resolves when written. */
  onSaveValue: ((name: string, value: string | null) => Promise<void>) | null;
  onOpenEnvironments: () => void;
  onOpenStep: (id: string) => void;
}

function record(value: Json | undefined): Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

function used(count: number | undefined): string {
  if (!count) return "not used";
  return `used by ${String(count)} ${count === 1 ? "step" : "steps"}`;
}

function ValueEditor({
  name,
  initial,
  environment,
  isNew,
  keep,
  onSave,
  onClose,
}: {
  name: string;
  initial: string;
  environment: string;
  isNew: boolean;
  /** Moving a run input's default into the environment. */
  keep: boolean;
  onSave: (name: string, value: string | null) => Promise<void>;
  onClose: () => void;
}) {
  const [key, setKey] = useState(name);
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = (next: string | null) => {
    setBusy(true);
    setError(null);
    onSave(key.trim(), next)
      .then(onClose)
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Could not save the value.");
      })
      .finally(() => {
        setBusy(false);
      });
  };
  return (
    <form
      className="sb-var-editor"
      aria-label={isNew ? `Add a value to ${environment}` : `Value ${name} in ${environment}`}
      onSubmit={(event) => {
        event.preventDefault();
        run(value);
      }}
    >
      <b className="ah-small">
        {isNew
          ? `Add a value to ${environment}`
          : keep
            ? `Keep ${name} in ${environment}?`
            : `${name} in ${environment}`}
      </b>
      {keep && (
        <span className="ah-small ah-muted">
          Every step whose action has an input named {name} gets this value in {environment}. The
          scenario keeps its default for other environments.
        </span>
      )}
      {isNew && (
        <label className="ah-stack ah-small" style={{ gap: 4 }}>
          Name
          <input
            className="ah-input ah-mono"
            value={key}
            placeholder="aws_account_id"
            pattern="[a-z][a-z0-9_]*"
            required
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the popover opens on purpose
            autoFocus
            onChange={(event) => {
              setKey(event.target.value);
            }}
          />
        </label>
      )}
      <label className="ah-stack ah-small" style={{ gap: 4 }}>
        Value
        <input
          className="ah-input ah-mono"
          value={value}
          required
          // eslint-disable-next-line jsx-a11y/no-autofocus -- the popover opens on purpose
          autoFocus={!isNew}
          onChange={(event) => {
            setValue(event.target.value);
          }}
        />
      </label>
      <span className="ah-small ah-muted">
        Saves to hub.local.json now, for you only; not part of the scenario file. Values are plain
        text: put secrets in the env file, never here.
      </span>
      {error && (
        <span className="ah-small" style={{ color: "var(--failed)" }}>
          {error}
        </span>
      )}
      <span className="ah-row" style={{ gap: 6 }}>
        {!isNew && !keep && (
          <Button
            size="sm"
            variant="ghost"
            icon="trash"
            disabled={busy}
            onClick={() => {
              run(null);
            }}
          >
            Remove
          </Button>
        )}
        <span className="ah-grow" />
        <Button size="sm" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button size="sm" variant="primary" type="submit" disabled={busy || key.trim() === ""}>
          {busy ? "Saving…" : keep ? `Keep in ${environment}` : "Save value"}
        </Button>
      </span>
    </form>
  );
}

export function VariablesPanel({
  document,
  environment,
  environmentValues,
  kept,
  usage,
  repeats,
  selected,
  onSelect,
  onEditInputs,
  onRemoveRepeats,
  onKeepAll,
  stepCount,
  onSaveValue,
  onOpenEnvironments,
  onOpenStep,
}: VariablesPanelProps) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<{
    name: string;
    value: string;
    isNew: boolean;
    keep?: boolean;
  } | null>(null);
  const needle = query.trim().toLowerCase();
  const match = (name: string) => needle === "" || name.toLowerCase().includes(needle);
  const inputs = Object.entries(record(document.inputs));
  const fromEnv = environmentValues ?? {};
  // A run input the environment gives a value is listed under the environment.
  const asked = inputs.filter(([name]) => !(name in fromEnv));
  const envNames = Object.keys(fromEnv);
  const declared = new Set(inputs.map(([name]) => name));
  const envUsed = envNames.filter((name) => declared.has(name) || (usage.get(name) ?? 0) > 0);
  const envOther = envNames.filter((name) => !envUsed.includes(name));
  const [showOther, setShowOther] = useState(false);
  const [keeping, setKeeping] = useState(false);
  const [keepError, setKeepError] = useState<string | null>(null);
  // Run inputs with a default that most steps use: an account, a name.
  const shared =
    environmentValues === null
      ? []
      : asked
          .filter(
            ([name, spec]) =>
              record(spec).default !== undefined &&
              stepCount > 0 &&
              (usage.get(name) ?? 0) * 2 >= stepCount,
          )
          .map(([name]) => name);

  const editorView =
    editing && onSaveValue && environment ? (
      <ValueEditor
        key={editing.name || "new"}
        name={editing.name}
        initial={editing.value}
        environment={environment}
        isNew={editing.isNew}
        keep={editing.keep === true}
        onSave={onSaveValue}
        onClose={() => {
          setEditing(null);
        }}
      />
    ) : null;

  const row = (
    name: string,
    value: string | null,
    note: string,
    onOpen: () => void,
    extra?: ReactNode,
  ) => (
    <li key={name}>
      <button
        type="button"
        className="sb-var"
        aria-pressed={selected === name}
        onClick={() => {
          onSelect(selected === name ? null : name);
          onOpen();
        }}
      >
        <span className="sb-var-line">
          <span className="ah-mono sb-var-name">{name}</span>
          <span className="sb-var-value ah-mono">
            {value === null ? (
              <span className="ah-subtle">required</span>
            ) : (
              <PathText path={value} max={22} />
            )}
          </span>
        </span>
        <span className="sb-var-note">{note}</span>
      </button>
      {extra}
      {editing && !editing.isNew && editing.name === name && editorView}
    </li>
  );

  return (
    <div className="sb-left-body">
      <input
        className="ah-input"
        type="search"
        aria-label="Find a variable"
        placeholder="Find a variable"
        data-left-search
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />

      <section className="sb-vars" aria-labelledby="vars-asked">
        <header className="sb-vars-head">
          <h3 id="vars-asked">Asked when the scenario run starts</h3>
          <IconButton icon="pencil" size="sm" label="Edit the run inputs" onClick={onEditInputs} />
        </header>
        {asked.length === 0 ? (
          <span className="ah-small ah-subtle">Nothing: the scenario asks for no value.</span>
        ) : (
          <ul>
            {asked
              .filter(([name]) => match(name))
              .map(([name, spec]) => {
                const item = record(spec);
                const fallback = item.default === undefined ? null : shown(item.default);
                const description = text(item.description, "");
                return row(
                  name,
                  fallback,
                  [used(usage.get(name)), description].filter(Boolean).join(" · "),
                  () => undefined,
                  // A value many steps share (an account, a name) belongs to the environment.
                  environment &&
                    onSaveValue &&
                    environmentValues !== null &&
                    fallback !== null &&
                    (usage.get(name) ?? 0) >= 3 ? (
                    <button
                      type="button"
                      className="sb-link sb-var-keep"
                      onClick={() => {
                        setEditing({ name, value: fallback, isNew: false, keep: true });
                      }}
                    >
                      <Icon name="corner-down-right" size="sm" /> Keep in {environment}
                    </button>
                  ) : undefined,
                );
              })}
          </ul>
        )}
        {shared.length > 0 && onKeepAll && environment && (
          <div className="sb-var-tip sb-var-tip-accent">
            <span>
              <b className="ah-mono">{shared.join(", ")}</b> {shared.length === 1 ? "is" : "are"}{" "}
              used by most steps: a fact of the environment, not of this scenario. Keep{" "}
              {shared.length === 1 ? "it" : "them"} in {environment}
              {repeats > 0 ? " and drop the repeats" : ""}?
            </span>
            <Button
              size="sm"
              variant="primary"
              disabled={keeping}
              onClick={() => {
                setKeeping(true);
                setKeepError(null);
                onKeepAll(shared)
                  .catch((reason: unknown) => {
                    setKeepError(
                      reason instanceof Error ? reason.message : "Could not save the values.",
                    );
                  })
                  .finally(() => {
                    setKeeping(false);
                  });
              }}
            >
              {keeping ? "Saving…" : `Keep in ${environment}`}
            </Button>
            {keepError && <span style={{ color: "var(--failed)" }}>{keepError}</span>}
          </div>
        )}
        {repeats > 0 && shared.length === 0 && (
          <div className="sb-var-tip">
            <span>
              {repeats} {repeats === 1 ? "value repeats" : "values repeat"} a run value in a step (
              <span className="ah-mono">x: $INPUTS.x</span>). Each step takes it anyway.
            </span>
            <Button size="sm" onClick={onRemoveRepeats}>
              Remove the repeats
            </Button>
          </div>
        )}
      </section>

      <section className="sb-vars" aria-labelledby="vars-env">
        <header className="sb-vars-head">
          <h3 id="vars-env">{environment ? `From ${environment}` : "From the environment"}</h3>
          {environment && onSaveValue && environmentValues !== null && (
            <IconButton
              icon="plus"
              size="sm"
              label={`Add a value to ${environment}`}
              onClick={() => {
                setEditing({ name: "", value: "", isNew: true });
              }}
            />
          )}
        </header>
        {!environment ? (
          <span className="ah-small ah-muted">
            No environment declared for this project. Keep values such as aws_account_id in one
            place by adding one.{" "}
            <Button size="sm" variant="ghost" onClick={onOpenEnvironments}>
              Open Environments
            </Button>
          </span>
        ) : environmentValues === null ? (
          <span className="ah-small ah-muted">
            The values of {environment} cannot be read. Run ./hub doctor to see why.
          </span>
        ) : (
          <>
            {envNames.length === 0 && (
              <span className="ah-small ah-muted">
                {environment} has no values yet. A value here reaches every step whose action has an
                input of the same name, so steps need not repeat it.
              </span>
            )}
            <ul>
              {envUsed.filter(match).map((name) =>
                row(name, fromEnv[name] ?? "", used(usage.get(name)), () => {
                  if (onSaveValue) setEditing({ name, value: fromEnv[name] ?? "", isNew: false });
                }),
              )}
              {showOther &&
                envOther.filter(match).map((name) =>
                  row(name, fromEnv[name] ?? "", "not used by this scenario", () => {
                    if (onSaveValue) setEditing({ name, value: fromEnv[name] ?? "", isNew: false });
                  }),
                )}
            </ul>
            {envOther.length > 0 && (
              <Button
                size="sm"
                variant="ghost"
                icon={showOther ? "chevron-up" : "chevron-down"}
                aria-expanded={showOther}
                onClick={() => {
                  setShowOther(!showOther);
                }}
              >
                {showOther
                  ? "Hide the values this scenario does not use"
                  : `${String(envOther.length)} more ${envOther.length === 1 ? "value" : "values"} this scenario does not use`}
              </Button>
            )}
            {editing?.isNew && editorView}
            <span className="ah-small ah-subtle">
              <Icon name="lock" size="sm" /> Plain text, never secrets.{" "}
              <button type="button" className="sb-link" onClick={onOpenEnvironments}>
                Open environment {environment}
              </button>
            </span>
          </>
        )}
      </section>

      <section className="sb-vars" aria-labelledby="vars-kept">
        <header className="sb-vars-head">
          <h3 id="vars-kept">Kept by steps</h3>
        </header>
        {kept.length === 0 ? (
          <span className="ah-small ah-subtle">
            No step keeps a value yet. A step can keep one of its action&apos;s outputs for later
            steps (Keep for later steps, in its editor).
          </span>
        ) : (
          <ul>
            {kept
              .filter((item) => match(item.name))
              .map((item) =>
                row(item.name, `← step ${item.number}`, used(usage.get(item.name)), () => {
                  onOpenStep(item.step);
                }),
              )}
          </ul>
        )}
      </section>
    </div>
  );
}
