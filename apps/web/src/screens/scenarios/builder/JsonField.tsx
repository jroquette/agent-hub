import { useRef, useState } from "react";

import { Button, Icon, IconButton, SegmentedControl } from "../../../components";
import { ValueToken, tokenOf } from "./CardParts";
import { asBare, bareRef, isBare, parseLoose, stringifyLoose } from "./looseJson";
import type { ValueSource } from "./model";
import { ValuePicker } from "./ValuePicker";

/* A JSON value of a step (a message body, a payload) edited as JSON, not as one line of text:
 * as Fields (one row per key: a literal, or a value from earlier as a token) or as JSON (an
 * indented text checked as you type). Either way the file keeps it compact, and a reference that
 * stands bare where a number goes stays bare. */

type Mode = "fields" | "json";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A value of a row, as the row's text box shows it. */
function literalText(value: unknown): string {
  if (typeof value === "string") return value;
  return value === null ? "null" : JSON.stringify(value);
}

/** What a typed text becomes, keeping the kind the value had (a number stays a number). */
function typed(text: string, before: unknown): unknown {
  if (typeof before === "number" && /^-?\d+(\.\d+)?$/.test(text.trim())) return Number(text);
  if (typeof before === "boolean" && (text === "true" || text === "false")) return text === "true";
  if (before === null && text === "null") return null;
  return text;
}

export function JsonField({
  id,
  name,
  value,
  sources,
  describedBy,
  onChange,
}: {
  id: string;
  /** The input's name ("body"), for the controls' names. */
  name: string;
  value: string;
  sources: readonly ValueSource[];
  describedBy?: string | undefined;
  onChange: (value: string) => void;
}) {
  const read = parseLoose(value);
  const flat = read.ok && isObject(read.value);
  const [mode, setMode] = useState<Mode>(flat ? "fields" : "json");
  const [draft, setDraft] = useState<string | null>(null);
  const shownText = draft ?? (read.ok ? stringifyLoose(read.value, true) : value);
  const draftRead = draft === null ? null : parseLoose(draft);
  const rows = Math.min(16, Math.max(5, shownText.split("\n").length + 1));
  const box = useRef<HTMLTextAreaElement>(null);
  // Where the cursor was in the JSON text: a value from earlier goes there.
  const cursor = useRef<number | null>(null);

  const writeObject = (next: Record<string, unknown>) => {
    onChange(stringifyLoose(next));
  };

  return (
    <div className="sb-json">
      <div className="sb-json-head">
        <SegmentedControl
          label={`Edit ${name} as`}
          value={mode}
          options={[
            { id: "fields", label: "Fields", disabled: !flat },
            { id: "json", label: "JSON" },
          ].map((option) => ({
            id: option.id,
            label: option.label,
            title:
              option.id === "fields" && !flat
                ? "Fields edit a JSON object; fix the JSON or use the JSON view"
                : undefined,
          }))}
          onChange={(next) => {
            if (next === "fields" && !flat) return;
            setDraft(null);
            setMode(next as Mode);
          }}
        />
        <span className="ah-grow" />
        {mode === "json" && (
          <Button
            size="sm"
            variant="ghost"
            icon="braces"
            disabled={draftRead !== null && !draftRead.ok}
            onClick={() => {
              setDraft(null);
            }}
          >
            Format
          </Button>
        )}
      </div>

      {mode === "fields" && read.ok && isObject(read.value) ? (
        <FieldRows
          id={id}
          name={name}
          object={read.value}
          sources={sources}
          describedBy={describedBy}
          onChange={writeObject}
          onOpenJson={() => {
            setMode("json");
          }}
        />
      ) : (
        <>
          <textarea
            id={id}
            ref={box}
            className="ah-input ah-mono sb-json-text"
            style={{ height: rows * 18 + 18 }}
            rows={rows}
            spellCheck={false}
            value={shownText}
            aria-describedby={describedBy}
            aria-invalid={draftRead !== null && !draftRead.ok}
            onChange={(event) => {
              const text = event.target.value;
              setDraft(text);
              const next = parseLoose(text);
              if (next.ok) onChange(stringifyLoose(next.value));
            }}
            onSelect={(event) => {
              cursor.current = event.currentTarget.selectionStart;
            }}
            onBlur={(event) => {
              cursor.current = event.currentTarget.selectionStart;
            }}
          />
          {draftRead && !draftRead.ok ? (
            <span className="ah-small sb-field-error" role="status">
              <Icon name="circle-x" size="sm" /> Not valid JSON yet
              {draftRead.line !== null ? ` (line ${String(draftRead.line)})` : ""}: the file keeps
              the last valid value. {draftRead.message}
            </span>
          ) : (
            !read.ok &&
            draft === null && (
              <span className="ah-small sb-field-error">
                <Icon name="circle-x" size="sm" /> The value in the file is not valid JSON:{" "}
                {read.message}
              </span>
            )
          )}
          {sources.length > 0 && (
            <span className="sb-json-insert">
              <ValuePicker
                name={name}
                size="sm"
                sources={sources}
                onPick={(ref) => {
                  // At the cursor, quoted: a string value (remove the quotes for a number).
                  const at = cursor.current ?? shownText.length;
                  const text = `${shownText.slice(0, at)}"${ref}"${shownText.slice(at)}`;
                  setDraft(text);
                  const next = parseLoose(text);
                  if (next.ok) onChange(stringifyLoose(next.value));
                }}
              />
              <span className="ah-small ah-muted">
                Puts a value from earlier where the cursor is.
              </span>
            </span>
          )}
        </>
      )}
    </div>
  );
}

function FieldRows({
  id,
  name,
  object,
  sources,
  describedBy,
  onChange,
  onOpenJson,
}: {
  id: string;
  name: string;
  object: Record<string, unknown>;
  sources: readonly ValueSource[];
  describedBy?: string | undefined;
  onChange: (next: Record<string, unknown>) => void;
  onOpenJson: () => void;
}) {
  const entries = Object.entries(object);
  const set = (key: string, next: unknown) => {
    onChange(Object.fromEntries(entries.map(([k, v]) => [k, k === key ? next : v])));
  };
  const rename = (key: string, to: string) => {
    if (to === key || to === "" || to in object) return;
    onChange(Object.fromEntries(entries.map(([k, v]) => [k === key ? to : k, v])));
  };
  return (
    <div className="sb-json-rows" role="group" aria-label={`Fields of ${name}`} id={id}>
      {entries.length === 0 && <span className="ah-small ah-muted">No fields yet.</span>}
      {entries.map(([key, item]) => {
        const ref = isBare(item) ? bareRef(item) : typeof item === "string" ? item : null;
        const token = ref !== null ? tokenOf(ref) : null;
        return (
          <div key={key} className="sb-json-row">
            <span className="sb-json-row-head">
              <KeyInput
                value={key}
                label={`Name of the field ${key} in ${name}`}
                onRename={(to) => {
                  rename(key, to);
                }}
              />
              <IconButton
                icon="x"
                size="sm"
                label={`Remove the field ${key} from ${name}`}
                onClick={() => {
                  onChange(Object.fromEntries(entries.filter(([k]) => k !== key)));
                }}
              />
            </span>
            <span className="sb-json-value">
              {token && ref !== null ? (
                <span className="sb-json-token">
                  <ValueToken value={ref} />
                  {isBare(item) && <span className="ah-small ah-muted">as a number</span>}
                  <IconButton
                    icon="x"
                    size="sm"
                    label={`Type a value for ${key} instead`}
                    onClick={() => {
                      set(key, "");
                    }}
                  />
                </span>
              ) : isObject(item) || Array.isArray(item) ? (
                <span className="sb-json-token">
                  <span className="ah-mono ah-small">
                    {Array.isArray(item)
                      ? `[${String(item.length)} ${item.length === 1 ? "item" : "items"}]`
                      : `{${String(Object.keys(item).length)} fields}`}
                  </span>
                  <Button size="sm" variant="ghost" onClick={onOpenJson}>
                    Edit as JSON
                  </Button>
                </span>
              ) : (
                <input
                  className="ah-input ah-mono"
                  aria-label={`Value of ${key} in ${name}`}
                  aria-describedby={describedBy}
                  value={literalText(item)}
                  onChange={(event) => {
                    set(key, typed(event.target.value, item));
                  }}
                />
              )}
            </span>
            <ValuePicker
              name={`${name} · ${key}`}
              size="sm"
              sources={sources}
              onPick={(picked) => {
                set(key, typeof item === "number" || isBare(item) ? asBare(picked) : picked);
              }}
            />
          </div>
        );
      })}
      <Button
        size="sm"
        variant="ghost"
        icon="plus"
        onClick={() => {
          let n = entries.length + 1;
          while (`field_${String(n)}` in object) n += 1;
          onChange({ ...object, [`field_${String(n)}`]: "" });
        }}
      >
        Add a field
      </Button>
    </div>
  );
}

/** A field's name, renamed when the box is left (so typing never re-orders the rows). */
function KeyInput({
  value,
  label,
  onRename,
}: {
  value: string;
  label: string;
  onRename: (to: string) => void;
}) {
  const [text, setText] = useState(value);
  const [shownFor, setShownFor] = useState(value);
  if (shownFor !== value) {
    setShownFor(value);
    setText(value);
  }
  return (
    <input
      className="ah-input ah-mono sb-json-key"
      aria-label={label}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
      }}
      onBlur={() => {
        if (text.trim() === "") setText(value);
        else onRename(text.trim());
      }}
    />
  );
}
