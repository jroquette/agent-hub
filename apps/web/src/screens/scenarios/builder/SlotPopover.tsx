import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button, Icon } from "../../../components";
import { EffectBadge } from "../parts";
import { ConditionBuilder, ValueInput } from "./Inspector";
import type { ValueSource } from "./model";
import type { LibraryAction } from "./useScenarioDraft";

/* The popover a block's slot opens: fill the slot right where it shows, without the side panel.
 * One body per kind of slot (choose an action, a value, a condition, a text, a scenario); Done
 * (or Enter in a one-line field) applies, Esc or a click outside cancels. */

const WIDTH = 380;

export function SlotFrame({
  anchor,
  title,
  onClose,
  children,
  wide = false,
}: {
  anchor: DOMRect;
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const width = wide ? 520 : WIDTH;
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("keydown", escape);
    };
  }, [onClose]);
  const left = Math.max(8, Math.min(window.innerWidth - width - 8, anchor.left - 12));
  const below = anchor.bottom + 6;
  const top = below + 360 > window.innerHeight ? Math.max(8, anchor.top - 366) : below;
  return (
    <>
      <div className="bk-menu-scrim" onPointerDown={onClose} aria-hidden />
      <div
        className="ah-pop bk-menu bk-slot-pop"
        role="dialog"
        aria-label={title}
        style={{ left, top, width }}
      >
        <div className="bk-menu-head">{title}</div>
        {children}
      </div>
    </>
  );
}

/** Choose the action a block runs (a check offers only reading actions). */
export function ActionChoice({
  library,
  pack,
  readOnly,
  current,
  onPick,
  onNew,
  onAskClaude,
}: {
  library: readonly LibraryAction[];
  pack: string;
  readOnly: boolean;
  current: string;
  onPick: (ref: string) => void;
  /** Opens the new action form. */
  onNew: () => void;
  /** Asks Claude to write an action from this description. */
  onAskClaude: (description: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [asking, setAsking] = useState(false);
  const [described, setDescribed] = useState("");
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    field.current?.focus();
  }, []);
  const shown = library.filter(
    (item) =>
      (!readOnly || item.action.effect === "read") &&
      `${item.action.ref} ${item.action.description ?? ""}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <>
      <input
        ref={field}
        className="ah-input"
        aria-label="Find an action"
        placeholder="Find an action"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      <div className="bk-menu-list">
        {shown.map((item) => {
          const ref = item.action.pack === pack ? item.action.name : item.action.ref;
          return (
            <button
              key={item.action.ref}
              type="button"
              className="bk-menu-row"
              aria-current={ref === current ? true : undefined}
              onClick={() => {
                onPick(ref);
              }}
            >
              <Icon name="circle-play" size="sm" />
              <span className="bk-menu-label">{ref}</span>
              <span className="bk-menu-hint">
                <EffectBadge effect={item.action.effect} /> {item.action.description}
              </span>
            </button>
          );
        })}
        {shown.length === 0 && (
          <span className="ah-small ah-subtle">
            {readOnly
              ? "No reading action matches: a “wait until” polls an action that only reads."
              : "No action matches."}
          </span>
        )}
      </div>
      <div className="bk-menu-group">No action fits?</div>
      {asking ? (
        <form
          className="ah-stack"
          style={{ gap: 6 }}
          onSubmit={(event) => {
            event.preventDefault();
            if (described.trim() !== "") onAskClaude(described.trim());
          }}
        >
          <textarea
            className="ah-input bk-textarea"
            rows={3}
            aria-label="Describe the action"
            placeholder={
              readOnly
                ? "e.g. Read one record by id from a service and print its status"
                : "e.g. Send one JSON message to a queue"
            }
            value={described}
            onChange={(event) => {
              setDescribed(event.target.value);
            }}
          />
          <span className="ah-row" style={{ gap: 6, justifyContent: "flex-end" }}>
            <Button size="sm" variant="primary" type="submit" icon="message-square">
              Ask Claude to write it
            </Button>
          </span>
        </form>
      ) : (
        <span className="ah-row" style={{ gap: 6 }}>
          <Button
            size="sm"
            icon="message-square"
            onClick={() => {
              setAsking(true);
            }}
          >
            Ask Claude to write it
          </Button>
          <Button size="sm" variant="ghost" icon="plus" onClick={onNew}>
            New action…
          </Button>
        </span>
      )}
    </>
  );
}

/** A literal, or a value picked from what exists before this block. */
export function ValueChoice({
  value,
  sources,
  description,
  onApply,
}: {
  value: string;
  sources: readonly ValueSource[];
  description: string | null;
  onApply: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  return (
    <form
      className="ah-stack"
      style={{ gap: 8 }}
      onSubmit={(event) => {
        event.preventDefault();
        onApply(draft);
      }}
    >
      {description && <span className="ah-small ah-muted">{description}</span>}
      <ValueInput value={draft} sources={sources} onChange={setDraft} />
      {sources.length > 0 && (
        <span className="ah-small ah-subtle">
          Type a value, or pick one from “＋ from…”: an input, a value kept earlier, what you typed
          at a manual step, or an earlier block’s output.
        </span>
      )}
      <span className="ah-row" style={{ gap: 6, justifyContent: "flex-end" }}>
        <Button size="sm" type="submit" variant="primary">
          Done
        </Button>
      </span>
    </form>
  );
}

/** A condition, as rows, applied on Done. */
export function ConditionChoice({
  value,
  fields,
  onApply,
}: {
  value: string;
  fields: readonly { ref: string; label: string }[];
  onApply: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <ConditionBuilder label="When" value={draft} fields={fields} onChange={setDraft} />
      <span className="ah-row" style={{ gap: 6, justifyContent: "flex-end" }}>
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            onApply(draft);
          }}
        >
          Done
        </Button>
      </span>
    </div>
  );
}

/** A text (what to do by hand, a scenario name). */
export function TextChoice({
  value,
  multiline,
  placeholder,
  onApply,
}: {
  value: string;
  multiline: boolean;
  placeholder: string;
  onApply: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const field = useRef<HTMLTextAreaElement & HTMLInputElement>(null);
  useEffect(() => {
    field.current?.focus();
  }, []);
  return (
    <form
      className="ah-stack"
      style={{ gap: 8 }}
      onSubmit={(event) => {
        event.preventDefault();
        onApply(draft);
      }}
    >
      {multiline ? (
        <textarea
          ref={field}
          className="ah-input bk-textarea"
          rows={3}
          aria-label={placeholder}
          placeholder={placeholder}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
        />
      ) : (
        <input
          ref={field}
          className="ah-input"
          aria-label={placeholder}
          placeholder={placeholder}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
        />
      )}
      <span className="ah-row" style={{ gap: 6, justifyContent: "flex-end" }}>
        <Button size="sm" type="submit" variant="primary">
          Done
        </Button>
      </span>
    </form>
  );
}
