import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Icon } from "../../../components";
import { blockItem, CATEGORIES } from "./palette";
import type { BuilderDocument } from "./model";
import type { Item } from "./program";
import type { LibraryAction } from "./useScenarioDraft";

/* The insert menu a "+" opens: find a block or one of the hub's actions and add it right there,
 * or describe the step in words and hand it to Claude (the Discuss panel). One list, filtered by
 * what is typed; ↑/↓ move, Enter adds, Shift+Enter adds a reading action as a "wait until",
 * Esc closes. */

interface Row {
  key: string;
  label: string;
  hint: string;
  group: string;
  make: (asCheck: boolean) => Item | null;
  icon: Parameters<typeof Icon>[0]["name"];
}

const MENU_WIDTH = 420;

export function InsertMenu({
  anchor,
  where,
  library,
  pack,
  taken,
  onPick,
  onAskClaude,
  onClose,
}: {
  anchor: DOMRect;
  where: string;
  library: readonly LibraryAction[];
  pack: string;
  taken: BuilderDocument;
  onPick: (item: Item) => void;
  onAskClaude: (text: string) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    field.current?.focus();
  }, []);

  const rows: Row[] = [
    ...CATEGORIES.flatMap((category) =>
      category.entries.map((entry): Row => ({
        key: `block:${entry.key}`,
        label: entry.label,
        hint: entry.hint,
        group: "Blocks",
        icon: entry.icon,
        make: () => entry.make(taken),
      })),
    ),
    ...library.map((item): Row => ({
      key: `action:${item.action.ref}`,
      label: item.action.pack === pack ? item.action.name : item.action.ref,
      hint: `${item.action.effect ?? ""}${item.action.draft ? " · draft" : ""} · ${item.action.description ?? ""}`,
      group: item.action.pack === pack ? `Actions in ${pack}` : "Other actions",
      icon: "circle-play",
      make: (asCheck) =>
        blockItem(
          taken,
          asCheck && item.action.effect === "read" ? "expect" : "action",
          item.action.pack === pack ? item.action.name : item.action.ref,
        ),
    })),
  ];
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? rows.filter((row) => `${row.label} ${row.hint}`.toLowerCase().includes(needle))
    : rows;
  const describe = query.trim();
  const total = shown.length + (describe ? 1 : 0);
  const pick = (index: number, asCheck: boolean) => {
    if (index === shown.length) {
      onAskClaude(describe);
      return;
    }
    const item = shown[index]?.make(asCheck);
    if (item) onPick(item);
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((at) => Math.min(total - 1, at + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((at) => Math.max(0, at - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (event.metaKey || event.ctrlKey) {
        if (describe) onAskClaude(describe);
      } else pick(Math.min(active, total - 1), event.shiftKey);
    }
  };
  const left = Math.max(8, Math.min(window.innerWidth - MENU_WIDTH - 8, anchor.left - 20));
  const below = anchor.bottom + 6;
  const top = below + 420 > window.innerHeight ? Math.max(8, anchor.top - 426) : below;
  let lastGroup = "";
  return (
    <>
      <div className="bk-menu-scrim" onPointerDown={onClose} aria-hidden />
      <div
        className="ah-pop bk-menu"
        role="dialog"
        aria-label={`Add a block ${where}`}
        style={{ left, top, width: MENU_WIDTH }}
      >
        <div className="bk-menu-head">Add a block {where}</div>
        <input
          ref={field}
          className="ah-input"
          aria-label="Find a block or action, or describe the step"
          placeholder="Find a block or action, or describe the step"
          value={query}
          onKeyDown={onKey}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
        />
        <div className="bk-menu-list" role="listbox" aria-label="Blocks and actions">
          {shown.map((row, index) => {
            const head = row.group !== lastGroup ? row.group : null;
            lastGroup = row.group;
            return (
              <div key={row.key}>
                {head && <div className="bk-menu-group">{head}</div>}
                <button
                  type="button"
                  role="option"
                  aria-selected={index === active}
                  className="bk-menu-row"
                  onPointerEnter={() => {
                    setActive(index);
                  }}
                  onClick={(event) => {
                    pick(index, event.shiftKey);
                  }}
                >
                  <Icon name={row.icon} size="sm" />
                  <span className="bk-menu-label">{row.label}</span>
                  <span className="bk-menu-hint">{row.hint}</span>
                </button>
              </div>
            );
          })}
          {describe && (
            <>
              <div className="bk-menu-group">Claude</div>
              <button
                type="button"
                role="option"
                aria-selected={active === shown.length}
                className="bk-menu-row bk-menu-ai"
                onPointerEnter={() => {
                  setActive(shown.length);
                }}
                onClick={() => {
                  onAskClaude(describe);
                }}
              >
                <Icon name="message-square" size="sm" />
                <span className="bk-menu-label">Describe it to Claude: “{describe}”</span>
                <span className="bk-menu-hint">⌘ Enter</span>
              </button>
            </>
          )}
          {shown.length === 0 && !describe && (
            <span className="ah-small ah-subtle">Nothing matches.</span>
          )}
        </div>
        <div className="bk-menu-foot">
          ↑↓ to move · Enter adds · Shift+Enter adds a reading action as “wait until” · Esc closes
        </div>
      </div>
    </>
  );
}
