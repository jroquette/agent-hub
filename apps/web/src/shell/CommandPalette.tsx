import { useEffect, useId, useMemo, useState } from "react";
import type { KeyboardEvent } from "react";
import { useMatch, useNavigate } from "react-router";

import type { components } from "../api/schema";
import { Kbd, PathText } from "../components/core";
import { Icon, type IconName } from "../components/Icon";
import { SKELETON_DELAY_MS, Skeleton, useDelayed } from "../components/feedback";
import { useApi } from "../lib/api";
import { BRAIN_PREFIX, brainRoute } from "../lib/brainLinks";
import { isInAppPath } from "../lib/safeHref";
import { SEARCH_DEBOUNCE_MS } from "../lib/search";
import { hasWord, useKnowledgeSearch } from "../screens/brain/queries";
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

/** The palette asks the knowledge route for this many notes: one group's visible rows (Q-10). */
export const BRAIN_NOTES_LIMIT = 8;
const BRAIN_NOTES = "Brain notes";
const PLACEHOLDER = "Search sessions, runs, issues, files, agents, screens…";
const PLACEHOLDER_WITH_NOTES = "Search sessions, runs, issues, files, agents, notes, screens…";

interface PaletteItem {
  key: string;
  icon: IconName;
  label: string;
  sub?: string | undefined;
  /** The sub line is a path: mono, cut in the middle, the whole path on hover. */
  subPath?: boolean | undefined;
  /** The option's accessible name, when its text alone does not say it. */
  name?: string | undefined;
  hint?: string | undefined;
  mono?: boolean | undefined;
  href: string;
}

interface PaletteGroup {
  title: string;
  /** The visual header, when it says more than the group's name. */
  heading?: string | undefined;
  items: PaletteItem[];
  /** Its request is pending: a skeleton row holds its place. */
  pending?: boolean | undefined;
}

const SHORTCUT: Record<string, string> = {
  "/": "g p",
  "/sessions": "g s",
  "/runs": "g r",
  "/knowledge/learnings": "g k",
  "/features": "g f",
  "/health": "g h",
  "/settings": "g ,",
};

const SCREENS: PaletteItem[] = NAV.flatMap((group) =>
  group.items.map((item) => ({
    key: `screen:${item.id}`,
    icon: item.icon,
    label: item.label,
    hint: SHORTCUT[item.to],
    href: item.to,
  })),
);

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

/** The Brain notes group while its request is pending: its header and one skeleton row, shown
 * only after the skeleton delay, so a fast answer never flashes it. */
function PendingNotes({ heading }: { heading: string }) {
  const shown = useDelayed(SKELETON_DELAY_MS);
  if (!shown) return null;
  return (
    <div role="group" aria-label={BRAIN_NOTES} aria-busy="true">
      <div className="ah-palette-group" aria-hidden="true">
        {heading}
      </div>
      <div className="ah-palette-item" aria-hidden="true">
        <Skeleton width="60%" delay={0} />
      </div>
    </div>
  );
}

/** The brain notes among the knowledge results, as palette rows; repo docs are not opened. */
function noteItems(
  project: string,
  results: readonly components["schemas"]["KnowledgeResult"][],
): PaletteItem[] {
  return results
    .filter((result) => result.path.startsWith(BRAIN_PREFIX))
    .slice(0, BRAIN_NOTES_LIMIT)
    .map((result) => ({
      key: `note:${result.path}`,
      icon: "file-text",
      label: result.title,
      sub: result.path,
      subPath: true,
      name: `${result.title}, ${result.path}`,
      href: brainRoute(project, result.path.slice(BRAIN_PREFIX.length)),
    }));
}

/** The element id of an option: by item, so a group arriving late never moves it. */
function optionId(listId: string, item: PaletteItem): string {
  return `${listId}-${encodeURIComponent(item.key)}`;
}

/**
 * Jump to a session, run, approval, file, note or screen by id, key or name (spec 01). With a
 * project in scope, or on a project's route, its brain notes are searched too (AGH-393).
 */
export function CommandPalette({ onClose, initialQuery = "", project }: CommandPaletteProps) {
  const navigate = useNavigate();
  const listId = useId();
  const [query, setQuery] = useState(initialQuery);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const term = useDebounced(query.trim(), SEARCH_DEBOUNCE_MS);
  const search = useApi(
    "/api/v1/search",
    { query: { q: term, project: project ?? null, limit: 40 } },
    { enabled: term.length > 0 },
  );
  const routeProject = useMatch("/projects/:project/*")?.params.project ?? null;
  const notesProject = routeProject ?? project ?? null;
  const notesAsked = notesProject !== null && hasWord(term);
  const notes = useKnowledgeSearch(notesProject ?? "", term, {
    limit: BRAIN_NOTES_LIMIT,
    enabled: notesAsked,
  });
  const notesPending = notesAsked && notes.isPending;
  const notesHeading = `${BRAIN_NOTES} · ${notesProject ?? ""}`;

  const groups = useMemo((): PaletteGroup[] => {
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
    // A scenario run is never called "run" alone (glossary): it gets its own group and words.
    const split = found.flatMap((group) => {
      if (group.title !== "Workflow runs") return [group];
      const scenario = group.items.filter((item) => item.href.startsWith("/scenarios/"));
      return [
        { ...group, items: group.items.filter((item) => !scenario.includes(item)) },
        {
          title: "Scenario runs",
          items: scenario.map((item) => ({
            ...item,
            icon: "clipboard-list" as const,
            label: `Scenario run ${item.label}`,
          })),
        },
      ];
    });
    const brain: PaletteGroup = {
      title: BRAIN_NOTES,
      heading: notesHeading,
      items: notesAsked && notes.data ? noteItems(notesProject, notes.data.results) : [],
      pending: notesPending,
    };
    const all: PaletteGroup[] = [...split, brain, { title: "Screens", items: screens }];
    return all.filter((g) => g.items.length > 0 || g.pending);
  }, [query, term, search.data, notesAsked, notesProject, notesHeading, notes.data, notesPending]);

  const flat = groups.flatMap((g) => g.items);
  const kept = flat.findIndex((item) => item.key === selectedKey);
  const active = kept >= 0 ? kept : 0;

  const open = (item: PaletteItem | undefined) => {
    if (!item) return;
    onClose();
    void navigate(item.href);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next = flat[(active + step + flat.length) % Math.max(1, flat.length)];
      setSelectedKey(next?.key ?? null);
    } else if (event.key === "Enter") {
      event.preventDefault();
      open(flat[active]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  };

  const loading = term.length > 0 && search.isPending;
  const noMatch = term.length > 0 && !search.isPending && !notesPending && flat.length === 0;
  const notesFailed = notesAsked && notes.isError ? notes.error.title : null;
  const activeItem = flat[active];
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
            aria-activedescendant={activeItem ? optionId(listId, activeItem) : undefined}
            aria-autocomplete="list"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedKey(null);
            }}
            onKeyDown={onKeyDown}
            placeholder={notesProject === null ? PLACEHOLDER : PLACEHOLDER_WITH_NOTES}
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
          {groups.map((group) =>
            group.pending ? (
              <PendingNotes key={`pending:${term}`} heading={notesHeading} />
            ) : (
              <div key={group.title} role="group" aria-label={group.title}>
                <div className="ah-palette-group" aria-hidden="true">
                  {group.heading ?? group.title}
                </div>
                {group.items.map((item) => {
                  index += 1;
                  const isSelected = index === active;
                  return (
                    // Options are chosen with the arrows and Enter in the combobox above.
                    // eslint-disable-next-line jsx-a11y/click-events-have-key-events
                    <div
                      key={item.key}
                      id={optionId(listId, item)}
                      role="option"
                      tabIndex={-1}
                      aria-selected={isSelected}
                      aria-label={item.name}
                      className="ah-palette-item"
                      onClick={() => {
                        open(item);
                      }}
                      onMouseMove={() => {
                        if (!isSelected) setSelectedKey(item.key);
                      }}
                    >
                      <Icon name={item.icon} size="sm" />
                      <span
                        className={item.mono ? "ah-mono" : undefined}
                        style={item.mono ? { fontSize: 13 } : undefined}
                      >
                        {item.label}
                      </span>
                      {item.sub &&
                        (item.subPath ? (
                          <PathText path={item.sub} max={56} />
                        ) : (
                          <span className="ah-subtle ah-small">{item.sub}</span>
                        ))}
                      <span className="ah-palette-hint">
                        {isSelected ? "Enter to open" : item.hint}
                      </span>
                    </div>
                  );
                })}
              </div>
            ),
          )}
        </div>
        <div className="ah-palette-foot">
          <span>
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> move
          </span>
          <span>
            <Kbd>↵</Kbd> open
          </span>
          {notesProject === null && (
            <span>Brain notes are searched when a project is in scope.</span>
          )}
          <span role="status">
            {notesFailed !== null && `Brain notes not searched: ${notesFailed}.`}
          </span>
          <span style={{ marginLeft: "auto" }}>Esc to close</span>
        </div>
      </div>
    </div>
  );
}
