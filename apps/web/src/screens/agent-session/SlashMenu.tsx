import { useEffect, useId, useMemo, useState, type KeyboardEvent } from "react";

import type { components } from "../../api/schema";
import { Icon } from "../../components";
import { cx } from "../../lib/cx";
import { skillRoute, useSkillCatalog } from "../skills/queries";

type CatalogItem = components["schemas"]["CatalogItem"];

/** One entry of the `/` menu: what it inserts, whether the project's hub brings it, a hint, and
 * the in-app page of a hub item (opened in a new tab). */
export interface SlashOption {
  command: string;
  hub: boolean;
  description: string | null;
  href?: string | null;
}

/** The `/word` the caret is in, when it opens the text or follows a space; else null. */
export interface SlashToken {
  start: number;
  end: number;
  query: string;
}

export function slashToken(text: string, caret: number): SlashToken | null {
  const match = /(^|\s)\/(\S*)$/.exec(text.slice(0, caret));
  if (!match) return null;
  const query = match[2] ?? "";
  const rest = /^\S*/.exec(text.slice(caret))?.[0] ?? "";
  return { start: caret - query.length - 1, end: caret + rest.length, query };
}

/** The options holding `query` (case ignored), those whose name starts with it first. */
export function matchCommands<T extends { command: string }>(
  options: readonly T[],
  query: string,
): T[] {
  const q = query.toLowerCase();
  const name = (option: T) => option.command.slice(1).toLowerCase();
  return [
    ...options.filter((option) => name(option).startsWith(q)),
    ...options.filter((option) => !name(option).startsWith(q) && name(option).includes(q)),
  ];
}

/** `/plugin:name` as `/name` and `/agent-plugin:name` as `/agent-name`: how the hub names them. */
function shortName(command: string): string {
  return command.replace(/^\/(agent-)?[^:\s]*:/, "/$1");
}

/** What the hub's catalog offers in the composer: the skills a user may call, as `/name`, and the
 * agents, as `/agent-name` (the session sends both to Claude by their exact names). */
export function hubOptions(project: string, items: readonly CatalogItem[]): SlashOption[] {
  const seen = new Set<string>();
  const options: SlashOption[] = [];
  for (const item of items) {
    const callable =
      item.kind === "agent" ||
      (item.kind === "skill" && item.mode !== "model-only" && item.mode !== "neither");
    if (!callable) continue;
    const command = item.kind === "agent" ? `/agent-${item.name}` : `/${item.name}`;
    if (seen.has(command)) continue;
    seen.add(command);
    options.push({
      command,
      hub: true,
      description: item.description,
      href: skillRoute(project, item),
    });
  }
  return options;
}

/** The hub's options first, then the session's own commands the hub does not already offer. */
export function slashOptions(
  hub: readonly SlashOption[],
  session: readonly string[],
): SlashOption[] {
  const offered = new Set(hub.map((option) => option.command));
  const rest = session
    .filter((command) => !offered.has(shortName(command)))
    .map((command) => ({ command, hub: false, description: null }));
  return [...hub, ...rest];
}

/** The `/` menu's options of a session in `project`: its hub's skills and agents, then the rest. */
export function useSlashOptions(project: string | undefined, session: readonly string[]) {
  const catalog = useSkillCatalog(project ?? "", project !== undefined);
  const items = project === undefined ? undefined : catalog.data?.items;
  return useMemo(
    () => slashOptions(hubOptions(project ?? "", items ?? []), session),
    [project, items, session],
  );
}

/** Opens a hub item's page in a new tab; nothing for an option without one. */
export function openPage(option: SlashOption): void {
  if (option.href) window.open(option.href, "_blank", "noopener");
}

function countText(count: number): string {
  if (count === 0) return "No commands";
  return count === 1 ? "1 command" : `${String(count)} commands`;
}

/**
 * The `/` menu's state for a composer holding `text` with its caret at `caret` (AC-234.28): open
 * while the caret is in a `/word` that starts the text or follows a space, until Esc closes it
 * for that word. Past the start, it opens only when something matches, so a path keeps its Enter.
 * The composer keeps focus; the active option is its `aria-activedescendant` (ARIA listbox).
 */
export function useSlashMenu(
  text: string,
  caret: number,
  options: readonly SlashOption[],
  replace: (text: string, caret: number) => void,
) {
  const listId = useId();
  const token = slashToken(text, caret);
  const key = token ? `${String(token.start)}:${token.query}` : null;
  const [dismissed, setDismissed] = useState<number | null>(null);
  if (dismissed !== null && dismissed !== token?.start) setDismissed(null);
  const [moved, setMoved] = useState({ key, index: 0 });
  const matches = token ? matchCommands(options, token.query) : [];
  const open =
    token !== null && dismissed !== token.start && (token.start === 0 || matches.length > 0);
  const shown = open ? matches : [];
  const index = moved.key === key ? moved.index : 0;
  const activeId = shown.length > 0 ? `${listId}-${String(index)}` : undefined;

  const pick = (option: SlashOption) => {
    if (!token) return;
    const before = text.slice(0, token.start);
    const after = text.slice(token.end).replace(/^ /, "");
    const inserted = `${option.command} `;
    replace(before + inserted + after, before.length + inserted.length);
  };

  /** Handles a key of the composer; true when the menu took it. */
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!open) return false;
    const chosen = shown[index];
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp": {
        if (shown.length === 0) return false;
        const step = event.key === "ArrowDown" ? 1 : -1;
        setMoved({ key, index: (index + step + shown.length) % shown.length });
        break;
      }
      case "Enter":
        // Never a send while the menu is open, even with nothing to insert.
        if (event.shiftKey) return false;
        if (event.ctrlKey || event.metaKey) {
          if (chosen !== undefined) openPage(chosen);
        } else if (chosen !== undefined) pick(chosen);
        break;
      case "Tab":
        if (event.shiftKey || chosen === undefined) return false;
        pick(chosen);
        break;
      case "Escape":
        setDismissed(token.start);
        break;
      default:
        return false;
    }
    event.preventDefault();
    return true;
  };

  return {
    onKeyDown,
    /**
     * For a polite live region: the open menu's match count, or "No commands"; empty when closed.
     * It changes with the count only, so typing within the same matches stays silent.
     */
    announcement: open ? countText(shown.length) : "",
    /** For the textarea: the listbox it controls and its active option. */
    inputProps: {
      "aria-autocomplete": "list" as const,
      "aria-controls": open ? listId : undefined,
      "aria-activedescendant": activeId,
    },
    menu: open ? <SlashMenu id={listId} options={shown} active={index} onPick={pick} /> : null,
  };
}

interface SlashMenuProps {
  id: string;
  options: readonly SlashOption[];
  active: number;
  onPick: (option: SlashOption) => void;
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
      {/* The list scrolls and is in the tab order, so its scroll is reachable by keyboard once the
          hub's items fill it (axe scrollable-region-focusable); the composer still drives it. */}
      <div id={id} role="listbox" aria-label="Commands" className="as-slash-list" tabIndex={0}>
        {options.map((option, i) => (
          <div
            key={option.command}
            id={`${id}-${String(i)}`}
            role="option"
            aria-selected={i === active}
            aria-label={option.hub ? `${option.command}, from the hub` : option.command}
            tabIndex={-1}
            className={cx("as-slash-option", i === active && "as-slash-active")}
            // On mousedown, so the composer never loses focus.
            onMouseDown={(event) => {
              event.preventDefault();
              onPick(option);
            }}
          >
            {option.hub && (
              <span className="as-slash-hub" aria-hidden="true">
                hub
              </span>
            )}
            <span className="as-slash-command">{option.command}</span>
            <span className="as-slash-desc ah-muted" aria-hidden="true">
              {option.description}
            </span>
            {option.href && (
              // Not a link: an option holds no control (its children are presentational); the
              // keyboard opens the active option's page with Ctrl/Cmd+Enter.
              <span
                className="as-slash-open"
                aria-hidden="true"
                title={`Open ${option.command} in a new tab (Ctrl/Cmd+Enter)`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  openPage(option);
                }}
              >
                <Icon name="external-link" size="sm" />
              </span>
            )}
          </div>
        ))}
      </div>
      {options.length === 0 && <p className="ah-small ah-muted as-slash-empty">No commands</p>}
    </div>
  );
}
