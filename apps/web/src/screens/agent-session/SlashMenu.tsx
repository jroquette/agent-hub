import { useEffect, useId, useState, type KeyboardEvent } from "react";

import { cx } from "../../lib/cx";

/** What follows a `/` that starts the composer, while it is still one word; else null. */
export function slashQuery(text: string): string | null {
  const match = /^\/(\S*)$/.exec(text);
  return match ? (match[1] ?? "") : null;
}

/** The commands holding `query` (case ignored), those whose name starts with it first. */
export function matchCommands(commands: readonly string[], query: string): string[] {
  const q = query.toLowerCase();
  const name = (command: string) => command.slice(1).toLowerCase();
  return [
    ...commands.filter((command) => name(command).startsWith(q)),
    ...commands.filter((command) => !name(command).startsWith(q) && name(command).includes(q)),
  ];
}

/**
 * The `/` menu's state for a composer holding `text` (AC-234.28): open while the text is one
 * `/word`, until Esc closes it for that word. The composer keeps focus; the active option is
 * its `aria-activedescendant` (ARIA listbox pattern).
 */
export function useSlashMenu(
  text: string,
  commands: readonly string[],
  insert: (command: string) => void,
) {
  const listId = useId();
  const query = slashQuery(text);
  const [dismissed, setDismissed] = useState(false);
  if (query === null && dismissed) setDismissed(false);
  const [moved, setMoved] = useState({ query, index: 0 });
  const open = query !== null && !dismissed;
  const options = open ? matchCommands(commands, query) : [];
  const index = moved.query === query ? moved.index : 0;
  const activeId = options.length > 0 ? `${listId}-${String(index)}` : undefined;

  const pick = (command: string) => {
    insert(`${command} `);
  };

  /** Handles a key of the composer; true when the menu took it. */
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!open) return false;
    const chosen = options[index];
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp": {
        if (options.length === 0) return false;
        const step = event.key === "ArrowDown" ? 1 : -1;
        setMoved({ query, index: (index + step + options.length) % options.length });
        break;
      }
      case "Enter":
        // Never a send while the menu is open, even with nothing to insert.
        if (event.shiftKey) return false;
        if (chosen !== undefined) pick(chosen);
        break;
      case "Tab":
        if (event.shiftKey || chosen === undefined) return false;
        pick(chosen);
        break;
      case "Escape":
        setDismissed(true);
        break;
      default:
        return false;
    }
    event.preventDefault();
    return true;
  };

  return {
    onKeyDown,
    /** For the textarea: the listbox it controls and its active option. */
    inputProps: {
      "aria-autocomplete": "list" as const,
      "aria-controls": open ? listId : undefined,
      "aria-activedescendant": activeId,
    },
    menu: open ? <SlashMenu id={listId} options={options} active={index} onPick={pick} /> : null,
  };
}

interface SlashMenuProps {
  id: string;
  options: readonly string[];
  active: number;
  onPick: (command: string) => void;
}

/** The list of the `/` menu; "No commands" when nothing matches or the session listed none. */
export function SlashMenu({ id, options, active, onPick }: SlashMenuProps) {
  const activeId = `${id}-${String(active)}`;
  useEffect(() => {
    const option = document.getElementById(activeId);
    // jsdom has no scrollIntoView.
    if (option && "scrollIntoView" in option) option.scrollIntoView({ block: "nearest" });
  }, [activeId]);
  return (
    <div className="as-slash">
      <div id={id} role="listbox" aria-label="Commands" className="as-slash-list">
        {options.map((command, i) => (
          <div
            key={command}
            id={`${id}-${String(i)}`}
            role="option"
            aria-selected={i === active}
            tabIndex={-1}
            className={cx("as-slash-option", i === active && "as-slash-active")}
            // On mousedown, so the composer never loses focus.
            onMouseDown={(event) => {
              event.preventDefault();
              onPick(command);
            }}
          >
            {command}
          </div>
        ))}
      </div>
      {options.length === 0 && <p className="ah-small ah-muted as-slash-empty">No commands</p>}
    </div>
  );
}
