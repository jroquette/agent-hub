/* The composer's model and effort picker: the model list, and the effort levels in a side menu. */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent } from "react";

import { Icon } from "../../components";
import { EFFORTS, effortLabel, type EffortLevel } from "./effort";

/** The space between a menu and what it opens from, and the least it keeps from the window's edge. */
const GAP = 6;
const MARGIN = 8;

const CLAUDE_ID = /^claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(\[1m\])?$/;
const capital = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

/** How a model reads: an alias capitalized, `claude-opus-5-5[1m]` as "Opus 5.5 (1M)", else its id. */
export function modelLabel(model: string): string {
  const id = CLAUDE_ID.exec(model);
  if (!id) return /^(default|opus|sonnet|haiku|fable)$/.test(model) ? capital(model) : model;
  const [, family = "", major = "", minor, wide] = id;
  return `${capital(family)} ${major}${minor ? `.${minor}` : ""}${wide ? " (1M)" : ""}`;
}

/** The row a model belongs to: `claude-opus-5-5` is the `opus` alias when that is offered. */
function rowOf(model: string, models: readonly string[]): string | null {
  if (models.includes(model)) return model;
  const family = CLAUDE_ID.exec(model)?.[1];
  return family && models.includes(family) ? family : null;
}

export interface ModelMenuProps {
  model: string;
  /** The model aliases capabilities offer; a current model that fits none gets its own row. */
  models: readonly string[];
  effort: EffortLevel | null;
  disabled?: boolean | undefined;
  onModel: (model: string) => void;
  onEffort: (effort: EffortLevel) => void;
  /** An extra row after the models, such as "Other model id…"; `checked` when it is the choice. */
  extra?: { label: string; checked: boolean; onPick: () => void } | undefined;
}

export function ModelMenu({
  model,
  models,
  effort,
  disabled = false,
  onModel,
  onEffort,
  extra,
}: ModelMenuProps) {
  const [open, setOpen] = useState(false);
  const [efforts, setEfforts] = useState(false);
  const [mainAt, setMainAt] = useState<CSSProperties>({});
  const [subAt, setSubAt] = useState<CSSProperties>({});
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const main = useRef<HTMLDivElement>(null);
  const sub = useRef<HTMLDivElement>(null);
  const effortRow = useRef<HTMLButtonElement>(null);

  const close = () => {
    setOpen(false);
    setEfforts(false);
    trigger.current?.focus({ preventScroll: true });
  };

  useEffect(() => {
    if (!open) return;
    (
      main.current?.querySelector<HTMLElement>('[aria-checked="true"]') ??
      main.current?.querySelector("button")
    )?.focus({
      preventScroll: true,
    });
    const onDown = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) {
        setOpen(false);
        setEfforts(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  // Placed against the window, so a scrolling parent (the new session dialog) cannot clip them.
  useLayoutEffect(() => {
    if (!open || !trigger.current || !main.current) return;
    const pill = trigger.current.getBoundingClientRect();
    const room = window.innerWidth - main.current.offsetWidth - MARGIN;
    setMainAt({
      left: Math.max(MARGIN, Math.min(pill.left, room)),
      bottom: window.innerHeight - pill.top + GAP,
    });
  }, [open]);

  // Beside the list where it fits; a narrow panel or a phone shows it over the list.
  useLayoutEffect(() => {
    if (!efforts || !main.current || !sub.current) return;
    const list = main.current.getBoundingClientRect();
    const width = sub.current.offsetWidth;
    const right = list.right + GAP;
    const left = list.left - GAP - width;
    const over = Math.max(MARGIN, Math.min(list.left, window.innerWidth - width - MARGIN));
    const beside =
      right + width + MARGIN <= window.innerWidth ? right : left >= MARGIN ? left : over;
    setSubAt({ left: beside, bottom: window.innerHeight - list.bottom });
  }, [efforts, mainAt]);

  useEffect(() => {
    if (!efforts) return;
    (
      sub.current?.querySelector<HTMLElement>('[aria-checked="true"]') ??
      sub.current?.querySelector("button")
    )?.focus({
      preventScroll: true,
    });
  }, [efforts]);

  const closeEfforts = () => {
    setEfforts(false);
    effortRow.current?.focus({ preventScroll: true });
  };

  const moveFocus = (event: KeyboardEvent, holder: HTMLElement | null) => {
    const items = [...(holder?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
    const at = items.findIndex((item) => item === document.activeElement);
    const step = event.key === "ArrowDown" ? 1 : -1;
    items[(at + step + items.length) % items.length]?.focus({ preventScroll: true });
  };

  const onMainKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      moveFocus(event, main.current);
    } else if (event.key === "ArrowRight" && document.activeElement === effortRow.current) {
      event.preventDefault();
      setEfforts(true);
    }
  };

  const onSubKey = (event: KeyboardEvent<HTMLDivElement>) => {
    event.stopPropagation();
    if (event.key === "Escape" || event.key === "ArrowLeft") {
      event.preventDefault();
      closeEfforts();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      moveFocus(event, sub.current);
    }
  };

  const row = rowOf(model, models);
  const rows = row === null && !extra?.checked ? [...models, model] : models;
  const costly = effort === "max";

  return (
    <div className="as-model-menu" ref={root}>
      <button
        ref={trigger}
        type="button"
        className="as-pill as-model-trigger"
        title="Model and effort"
        aria-label={`Model and effort: ${extra?.checked ? extra.label : modelLabel(model)}${effort ? `, ${effortLabel(effort)}` : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => {
          if (open) close();
          else setOpen(true);
        }}
      >
        <span className="as-pill-value">{extra?.checked ? extra.label : modelLabel(model)}</span>
        {effort && <span className="as-model-effort">{effortLabel(effort)}</span>}
        {costly && <Icon name="triangle-alert" size="sm" className="as-model-warn" />}
        <Icon name="chevron-down" size="sm" className="as-pill-caret" />
      </button>
      {open && (
        <div
          ref={main}
          className="ah-pop as-model-pop"
          style={mainAt}
          role="menu"
          tabIndex={-1}
          aria-label="Model and effort"
          onKeyDown={onMainKey}
        >
          {rows.map((option) => (
            <button
              key={option}
              type="button"
              role="menuitemradio"
              aria-checked={!extra?.checked && (option === row || option === model)}
              className="as-model-option"
              onMouseEnter={() => {
                setEfforts(false);
              }}
              onClick={() => {
                if (option !== row && option !== model) onModel(option);
                close();
              }}
            >
              <span className="as-model-name">
                {option === row ? modelLabel(model) : modelLabel(option)}
              </span>
              {!extra?.checked && (option === row || option === model) && (
                <Icon name="check" size="sm" className="as-model-check" />
              )}
            </button>
          ))}
          {extra && (
            <button
              type="button"
              role="menuitemradio"
              aria-checked={extra.checked}
              className="as-model-option"
              onMouseEnter={() => {
                setEfforts(false);
              }}
              onClick={() => {
                extra.onPick();
                close();
              }}
            >
              <span className="as-model-name">{extra.label}</span>
              {extra.checked && <Icon name="check" size="sm" className="as-model-check" />}
            </button>
          )}
          <div className="as-model-rule" role="separator" />
          <button
            ref={effortRow}
            type="button"
            role="menuitem"
            aria-haspopup="menu"
            aria-expanded={efforts}
            className="as-model-option as-model-effort-row"
            data-open={efforts || undefined}
            onMouseEnter={() => {
              setEfforts(true);
            }}
            onClick={() => {
              // Hover has usually opened it already: a click must not close it again.
              setEfforts(true);
            }}
          >
            <span className="as-model-name">Effort</span>
            <span className="as-model-hint">{effort ? effortLabel(effort) : "Default"}</span>
            {costly && <Icon name="triangle-alert" size="sm" className="as-model-warn" />}
            <Icon name="chevron-right" size="sm" className="as-pill-caret" />
          </button>
          {efforts && (
            <div
              ref={sub}
              className="ah-pop as-model-pop as-model-sub"
              style={subAt}
              role="menu"
              tabIndex={-1}
              aria-label="Effort"
              onKeyDown={onSubKey}
            >
              <p className="as-model-note">
                More effort means fuller answers, but it takes longer and uses your limits faster.
              </p>
              {EFFORTS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="menuitemradio"
                  aria-checked={option.value === effort}
                  className="as-model-option"
                  onClick={() => {
                    if (option.value !== effort) onEffort(option.value);
                    close();
                  }}
                >
                  <span className="as-model-name">{option.label}</span>
                  {option.tag && (
                    <span className="as-model-tag" data-costly={option.costly ?? undefined}>
                      {option.costly && <Icon name="triangle-alert" size="sm" />}
                      {option.tag}
                    </span>
                  )}
                  {option.value === effort && (
                    <Icon name="check" size="sm" className="as-model-check" />
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
