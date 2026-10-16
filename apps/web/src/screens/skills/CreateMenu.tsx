/* The catalog's Create button: pick a kind, then build it with Claude in the Studio. The rows are
 * taller than the shared MenuItem (a name over a line saying what the kind is). */
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useNavigate } from "react-router";

import { Button, Icon } from "../../components";
import { KINDS, KIND_SUMMARY } from "./filters";
import { KIND_ICON, KIND_NAME } from "./SkillCard";
import { newDraftRoute } from "./Studio";

export function CreateMenu({ project }: { project: string }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onDown = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = [...(menu.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
    const at = items.findIndex((item) => item === document.activeElement);
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      root.current?.querySelector<HTMLButtonElement>("button")?.focus();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      items[(at + step + items.length) % items.length]?.focus();
    }
  };

  return (
    <div className="ah-create-menu" ref={root}>
      <Button
        variant="primary"
        icon="plus"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => {
          setOpen(!open);
        }}
      >
        Create with Claude
        <Icon name="chevron-down" size="sm" />
      </Button>
      {open && (
        <div
          ref={menu}
          className="ah-pop ah-create-pop"
          role="menu"
          tabIndex={-1}
          aria-label="Create with Claude"
          onKeyDown={onKeyDown}
        >
          {KINDS.map((kind) => (
            <button
              key={kind}
              type="button"
              role="menuitem"
              className="ah-create-option"
              onClick={() => {
                setOpen(false);
                void navigate(newDraftRoute(project, kind));
              }}
            >
              <span className="ah-kind-badge" data-kind={kind} aria-hidden="true">
                <Icon name={KIND_ICON[kind]} size="sm" />
              </span>
              <span className="ah-create-option-text">
                <span className="ah-create-option-name">New {KIND_NAME[kind].toLowerCase()}</span>
                <span className="ah-create-option-line">{KIND_SUMMARY[kind]}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
