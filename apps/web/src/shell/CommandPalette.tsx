import { useEffect, useId, useMemo, useState } from "react";
import type { KeyboardEvent } from "react";
import { useNavigate } from "react-router";

import type { components } from "../api/schema";
import { Kbd } from "../components/core";
import { Icon, type IconName } from "../components/Icon";
import { Skeleton } from "../components/feedback";
import { useApi } from "../lib/api";
import { isInAppPath } from "../lib/safeHref";
import { NAV } from "./Sidebar";

type SearchHit = components["schemas"]["SearchHit"];
type SearchKind = components["schemas"]["SearchKind"];

/** Result groups in the design's fixed order (spec 01); empty groups are hidden. */
const GROUPS: readonly { kind: SearchKind; title: string; icon: IconName; mono?: boolean }[] = [
  { kind: "session", title: "Sessions", icon: "square-terminal" },
  { kind: "run", title: "Workflow runs", icon: "route" },
  { kind: "approval", title: "Approvals", icon: "stamp" },
  { kind: "feature", title: "Features", icon: "list-checks" },
  { kind: "file", title: "Files", icon: "file-text", mono: true },
  { kind: "command", title: "Commands", icon: "terminal", mono: true },
  { kind: "tool", title: "Tools", icon: "plug" },
  { kind: "learning", title: "Learnings", icon: "lightbulb" },
];

export const SEARCH_DEBOUNCE_MS = 120;

interface PaletteItem {
  key: string;
  icon: IconName;
  label: string;
  sub?: string | undefined;
  hint?: string | undefined;
  mono?: boolean | undefined;
  href: string;
}

const SHORTCUT: Record<string, string> = {
  "/": "g p",
  "/approvals": "g a",
  "/sessions": "g s",
  "/runs": "g r",
  "/features": "g f",
  "/health": "g h",
  "/settings": "g ,",
};

const SCREENS: PaletteItem[] = NAV.flatMap((group) =>
  group.items.flatMap((item) => [
    {
      key: `screen:${item.id}`,
      icon: item.icon ?? "circle-dot",
      label: item.label,
      hint: SHORTCUT[item.to],
      href: item.to,
    },
    ...(item.children ?? []).map((child) => ({
      key: `screen:${child.id}`,
      icon: "lightbulb" as const,
      label: child.label,
      href: child.to,
    })),
  ]),
).filter((item, i, all) => all.findIndex((other) => other.href === item.href) === i);

function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value);
    }, ms);
    return () => {
      clearTimeout(timer);
    };
  }, [value, ms]);
  return debounced;
}

export interface CommandPaletteProps {
  onClose: () => void;
  initialQuery?: string | undefined;
  project?: string | null | undefined;
}

/** Jump to a session, run, approval, file or screen by id, key or name (spec 01). */
export function CommandPalette({ onClose, initialQuery = "", project }: CommandPaletteProps) {
  const navigate = useNavigate();
  const listId = useId();
  const [query, setQuery] = useState(initialQuery);
  const [selected, setSelected] = useState(0);
  const term = useDebounced(query.trim(), SEARCH_DEBOUNCE_MS);
  const search = useApi(
    "/api/v1/search",
    { query: { q: term, project: project ?? null, limit: 40 } },
    { enabled: term.length > 0 },
  );

  const groups = useMemo(() => {
    const lower = query.trim().toLowerCase();
    const screens = SCREENS.filter((s) => !lower || s.label.toLowerCase().includes(lower));
    const hits: SearchHit[] = term ? (search.data?.items ?? []) : [];
    const found = GROUPS.map((group) => ({
      title: group.title,
      items: hits
        .filter((hit) => hit.kind === group.kind && isInAppPath(hit.href))
        .map((hit, i): PaletteItem => ({
          key: `${hit.kind}:${hit.href}:${String(i)}`,
          icon: group.icon,
          label: hit.label,
          sub: [hit.detail, hit.project].filter(Boolean).join(" · ") || undefined,
          mono: group.mono,
          href: hit.href,
        })),
    }));
    return [...found, { title: "Screens", items: screens }].filter((g) => g.items.length > 0);
  }, [query, term, search.data]);

  const flat = groups.flatMap((g) => g.items);
  const active = Math.min(selected, Math.max(0, flat.length - 1));

  const open = (item: PaletteItem | undefined) => {
    if (!item) return;
    onClose();
    void navigate(item.href);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setSelected((active + step + flat.length) % Math.max(1, flat.length));
    } else if (event.key === "Enter") {
      event.preventDefault();
      open(flat[active]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  };

  const loading = term.length > 0 && search.isPending;
  const noMatch = term.length > 0 && !search.isPending && flat.length === 0;
  let index = -1;
  return (
    <div
      className="ah-scrim"
      data-testid="palette-scrim"
      style={{ zIndex: "var(--z-palette)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="presentation"
    >
      <div
        className="ah-palette"
        role="dialog"
        aria-modal="true"
        data-shell-layer=""
        aria-label="Command palette"
      >
        <div className="ah-palette-input">
          <Icon name="search" />
          <input
            // The palette exists to type into: focus belongs in its field.
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={flat.length ? `${listId}-${String(active)}` : undefined}
            aria-autocomplete="list"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelected(0);
            }}
            onKeyDown={onKeyDown}
            placeholder="Search sessions, runs, issues, files, agents, screens…"
            aria-label="Search"
          />
          <Kbd>Esc</Kbd>
        </div>
        <div className="ah-palette-list" role="listbox" id={listId} aria-label="Results">
          {loading && (
            <div className="ah-palette-item" aria-hidden="true">
              <Skeleton width="60%" />
            </div>
          )}
          {noMatch && (
            <div className="ah-palette-group" role="status">
              No match for &quot;{term}&quot;. Try an issue key like AGH-48, an 8-character id, or a
              file name.
            </div>
          )}
          {groups.map((group) => (
            <div key={group.title} role="group" aria-label={group.title}>
              <div className="ah-palette-group" aria-hidden="true">
                {group.title}
              </div>
              {group.items.map((item) => {
                index += 1;
                const mine = index;
                const isSelected = mine === active;
                return (
                  // Options are chosen with the arrows and Enter in the combobox above.
                  // eslint-disable-next-line jsx-a11y/click-events-have-key-events
                  <div
                    key={item.key}
                    id={`${listId}-${String(mine)}`}
                    role="option"
                    tabIndex={-1}
                    aria-selected={isSelected}
                    className="ah-palette-item"
                    onClick={() => {
                      open(item);
                    }}
                    onMouseMove={() => {
                      if (!isSelected) setSelected(mine);
                    }}
                  >
                    <Icon name={item.icon} size="sm" />
                    <span
                      className={item.mono ? "ah-mono" : undefined}
                      style={item.mono ? { fontSize: 13 } : undefined}
                    >
                      {item.label}
                    </span>
                    {item.sub && <span className="ah-subtle ah-small">{item.sub}</span>}
                    <span className="ah-palette-hint">
                      {isSelected ? "Enter to open" : item.hint}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <div className="ah-palette-foot">
          <span>
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> move
          </span>
          <span>
            <Kbd>↵</Kbd> open
          </span>
          <span style={{ marginLeft: "auto" }}>Esc to close</span>
        </div>
      </div>
    </div>
  );
}
