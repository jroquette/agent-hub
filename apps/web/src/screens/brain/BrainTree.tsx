import { defaultRangeExtractor, observeElementRect, useVirtualizer } from "@tanstack/react-virtual";
import { useCallback, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, RefObject } from "react";
import { flushSync } from "react-dom";

import { AppLink, Icon } from "../../components";
import { goSequencePending, typingIn } from "../../shell/goSequence";
import { NoteLink } from "./NoteLink";
import { buildTree, foldersOf, treeRows, type TreeRow } from "./tree";

// The Brain's tree renders only the rows in its box's view (AGH-617): a flat list of rows built
// from the listing and the open folders, one Tab stop, and keys to move, open and close.

/** Each part's fixed height in px, as Brain.css draws it, so the box never jumps as it scrolls. */
const SIZE = {
  note: 26,
  folder: 28,
  /** A group's sticky heading: its 20 px line, then 4 px where the focus ring of a row fits. */
  heading: 24,
  /** Between two groups. */
  gap: 24,
  /** "Triage in Learnings" at the end of the inbox group: 2 px above its 26 px row. */
  link: 28,
  /** Under the last row, where its focus ring fits. */
  end: 4,
} as const;
/** How far a row moves in per folder level (`space-3`). */
const INDENT = 12;
/** jsdom, or a box not laid out yet, measures 0: the virtualizer keeps this window then. */
const FALLBACK_RECT = { width: 1024, height: 640 };

const GROUPS = [
  { group: "start", id: "brain-start", label: "Start here" },
  { group: "folders", id: "brain-folders", label: "Folders" },
  { group: "inbox", id: "brain-inbox", label: "Inbox · unreviewed" },
] as const;

type Group = (typeof GROUPS)[number];

/** One part of the box, top to bottom: a group's heading, a row, or the inbox's last link. */
interface Part {
  key: string;
  size: number;
  row?: TreeRow | undefined;
}

/** A group, and the parts of its first and last rows. */
type GroupSpan = Group & { first: number; last: number };

/** The rows the box lists, and where each one sits. */
interface TreeLayout {
  rows: TreeRow[];
  parts: Part[];
  /** Each part's top, in px from the top of the box's content. */
  tops: number[];
  groups: GroupSpan[];
  /** Each row's place among the rows, by its path. */
  place: Map<string, number>;
  /** Each row's part, by its path. */
  partOf: Map<string, number>;
}

function layOut(rows: TreeRow[]): TreeLayout {
  const parts: Part[] = [];
  const groups: GroupSpan[] = [];
  for (const group of GROUPS) {
    const own = rows.filter((row) => row.group === group.group);
    if (own.length === 0) continue;
    parts.push({ key: `#${group.id}`, size: SIZE.heading + (parts.length > 0 ? SIZE.gap : 0) });
    groups.push({ ...group, first: parts.length, last: parts.length + own.length - 1 });
    for (const row of own) parts.push({ key: row.path, size: SIZE[row.kind], row });
    if (group.group === "inbox") parts.push({ key: "#triage", size: SIZE.link });
  }
  const tops: number[] = [];
  let top = 0;
  for (const part of parts) {
    tops.push(top);
    top += part.size;
  }
  const place = new Map(rows.map((row, at) => [row.path, at]));
  const partOf = new Map(parts.flatMap((part, index) => (part.row ? [[part.key, index]] : [])));
  return { rows, parts, tops, groups, place, partOf };
}

/** The folder a row sits in, as its path with the trailing `/`; "" at the top of a group. */
function parentOf(path: string): string {
  const own = path.endsWith("/") ? path.slice(0, -1) : path;
  return own.slice(0, own.lastIndexOf("/") + 1);
}

/** The tree's current row: the last row used, else the selected note, else the first row. */
function rovingRow(layout: TreeLayout, current: string | null, selected: string): string | null {
  if (current !== null) {
    if (layout.place.has(current)) return current;
    // Its row left the list (its folder closed, or a new listing dropped it): its nearest folder.
    const folder = foldersOf(current)
      .reverse()
      .find((path) => layout.place.has(path));
    if (folder !== undefined) return folder;
  }
  if (layout.place.has(selected)) return selected;
  return layout.rows[0]?.path ?? null;
}

/** What a key does on a row: go to a row, open or close it, open its note, or nothing more. */
type TreeMove =
  { to: number } | { toggle: true } | { open: true } | { field: true } | { still: true };

/** What `key` does on the row at `at` (spec 01, Brain tree); null when the key is not the tree's. */
function keyMove(
  key: string,
  at: number,
  layout: TreeLayout,
  open: ReadonlySet<string>,
): TreeMove | null {
  const row = layout.rows[at];
  if (row === undefined) return null;
  const folder = row.kind === "folder";
  const opened = folder && open.has(row.path);
  const last = layout.rows.length - 1;
  if (key === "ArrowDown" || key === "j") return { to: Math.min(at + 1, last) };
  if (key === "ArrowUp" || key === "k") return at === 0 ? { field: true } : { to: at - 1 };
  if (key === "Home") return { to: 0 };
  if (key === "End") return { to: last };
  if (key === "ArrowRight") {
    if (!folder) return { still: true };
    return opened ? { to: at + 1 } : { toggle: true };
  }
  if (key === "ArrowLeft") {
    if (opened) return { toggle: true };
    const parent = layout.place.get(parentOf(row.path));
    return parent === undefined ? { still: true } : { to: parent };
  }
  if (key === "o") return folder ? { toggle: true } : { open: true };
  // A folder's Space is its button's own click; on a note it does nothing, the box included.
  if (key === " " && !folder) return { still: true };
  return null;
}

/** The rendered row element of `path` in the box, if it is rendered. */
function rowElement(box: HTMLElement | null, path: string): HTMLElement | undefined {
  return [...(box?.querySelectorAll<HTMLElement>("[data-tree-row]") ?? [])].find(
    (element) => element.dataset.treeRow === path,
  );
}

/** A group's rendered rows, each with the space the unrendered rows above it take. */
function placeRows(layout: TreeLayout, shown: readonly number[], span: GroupSpan) {
  const top = layout.tops[span.first] ?? 0;
  const end = (layout.tops[span.last] ?? 0) + (layout.parts[span.last]?.size ?? 0);
  let cursor = top;
  const rows: { row: TreeRow; space: number }[] = [];
  for (const index of shown) {
    const row = layout.parts[index]?.row;
    if (index < span.first || index > span.last || row === undefined) continue;
    const at = layout.tops[index] ?? 0;
    rows.push({ row, space: at - cursor });
    cursor = at + SIZE[row.kind];
  }
  return { rows, below: end - cursor };
}

/** The open folders and the current row, which the tree keeps while it is shown. */
function useTreeState(selected: string) {
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set(foldersOf(selected)));
  const [seeded, setSeeded] = useState(selected);
  if (seeded !== selected) {
    // A new selection opens its folders; nothing closes by itself (state adjusted while
    // rendering, not in an effect).
    setSeeded(selected);
    setOpen((was) => {
      const closed = foldersOf(selected).filter((folder) => !was.has(folder));
      return closed.length === 0 ? was : new Set([...was, ...closed]);
    });
  }
  const [current, setCurrent] = useState<string | null>(null);
  const toggle = useCallback((folder: string) => {
    setOpen((was) => {
      const next = new Set(was);
      if (!next.delete(folder)) next.add(folder);
      return next;
    });
  }, []);
  return { open, toggle, current, setCurrent };
}

interface TreeItemProps {
  row: TreeRow;
  /** The space of the unrendered rows between it and the row rendered above it. */
  space: number;
  project: string;
  selected: string;
  opened: boolean;
  /** It is the tree's one Tab stop. */
  current: boolean;
  /** The row takes focus or is picked: it becomes the tree's current row. */
  onUse: (path: string) => void;
  onToggle: (path: string) => void;
  onKey: (event: KeyboardEvent<HTMLElement>, row: TreeRow) => void;
}

/** A row: a folder's button, which opens and closes it, or a note's link. */
function TreeItem({
  row,
  space,
  project,
  selected,
  opened,
  current,
  onUse,
  onToggle,
  onKey,
}: TreeItemProps) {
  const own = {
    tabIndex: current ? 0 : -1,
    onFocus: () => {
      onUse(row.path);
    },
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
      onKey(event, row);
    },
  };
  return (
    <li
      data-kind={row.kind}
      aria-level={row.depth + 1}
      aria-setsize={row.setSize}
      aria-posinset={row.posInSet}
      style={{ marginTop: space || undefined, paddingLeft: row.depth * INDENT || undefined }}
    >
      {row.kind === "folder" ? (
        <button
          type="button"
          className="ah-brain-folder"
          aria-expanded={opened}
          aria-label={`${row.name}, ${String(row.count)} ${row.count === 1 ? "note" : "notes"}`}
          data-tree-row={row.path}
          onClick={() => {
            onUse(row.path);
            onToggle(row.path);
          }}
          {...own}
        >
          <Icon name={opened ? "chevron-down" : "chevron-right"} size="sm" />
          <span className="ah-mono">{row.name}/</span>
          <span className="ah-count">{row.count}</span>
        </button>
      ) : (
        <NoteLink
          project={project}
          path={row.path}
          selected={selected}
          label={row.name}
          treeRow={row.path}
          onOpen={() => {
            onUse(row.path);
          }}
          {...own}
        />
      )}
    </li>
  );
}

export interface BrainTreeProps {
  project: string;
  entries: readonly { path: string; size: number }[];
  /** The open note's path. */
  selected: string;
  /** The search field above the tree: `↑` on the first row goes back to it. */
  field: RefObject<HTMLInputElement | null>;
}

/**
 * The Brain's note tree (spec 19, AGH-617): start notes, folders and the inbox as rows, only the
 * ones in view rendered. Folders open and close in place, notes are links, and the tree is one
 * Tab stop whose rows the arrows, `j`/`k`, `Home`/`End`, `Enter`/`o` and `Space` work.
 */
export function BrainTree({ project, entries, selected, field }: BrainTreeProps) {
  const { open, toggle, current, setCurrent } = useTreeState(selected);
  const root = useMemo(() => buildTree(entries), [entries]);
  const layout = useMemo(() => layOut(treeRows(root, open)), [root, open]);
  const roving = rovingRow(layout, current, selected);
  const rovingPart = roving === null ? undefined : layout.partOf.get(roving);
  const boxRef = useRef<HTMLDivElement>(null);
  const getItemKey = useCallback((index: number) => layout.parts[index]?.key ?? index, [layout]);
  const estimateSize = useCallback(
    (index: number) => layout.parts[index]?.size ?? SIZE.note,
    [layout],
  );
  // The virtualizer is read during render only; nothing memoizes its functions.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: layout.parts.length,
    getScrollElement: () => boxRef.current,
    estimateSize,
    getItemKey,
    overscan: 12,
    paddingEnd: SIZE.end,
    // A row the box scrolls to stays below its group's sticky heading, its focus ring in view.
    scrollPaddingStart: SIZE.heading,
    scrollPaddingEnd: SIZE.end,
    initialRect: FALLBACK_RECT,
    observeElementRect: (instance, report) =>
      observeElementRect(instance, (rect) => {
        report(rect.height > 0 ? rect : FALLBACK_RECT);
      }),
    // The current row is always rendered, so focus never falls to the page when it scrolls away.
    rangeExtractor: (range) => {
      const indexes = defaultRangeExtractor(range);
      if (rovingPart === undefined || indexes.includes(rovingPart)) return indexes;
      return [...indexes, rovingPart].sort((a, b) => a - b);
    },
  });
  const shown = virtualizer.getVirtualItems().map((item) => item.index);

  /** Goes to the row at `at`: it renders as the current row, the box scrolls, then it takes focus. */
  const goTo = (at: number) => {
    const row = layout.rows[at];
    const part = row === undefined ? undefined : layout.partOf.get(row.path);
    if (row === undefined || part === undefined) return;
    flushSync(() => {
      setCurrent(row.path);
    });
    virtualizer.scrollToIndex(part);
    rowElement(boxRef.current, row.path)?.focus({ preventScroll: true });
  };

  const onKey = (event: KeyboardEvent<HTMLElement>, row: TreeRow) => {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
    // A key typed into a field, or the second key of a `g` sequence, is not the tree's.
    if (typingIn(event.target) || goSequencePending()) return;
    const at = layout.place.get(row.path);
    const move = at === undefined ? null : keyMove(event.key, at, layout, open);
    if (move === null) return;
    event.preventDefault();
    if ("to" in move) goTo(move.to);
    else if ("toggle" in move) toggle(row.path);
    else if ("open" in move) event.currentTarget.click();
    else if ("field" in move) field.current?.focus();
  };

  return (
    <div ref={boxRef} className="ah-brain-scroll">
      {layout.groups.map((span) => {
        const { rows, below } = placeRows(layout, shown, span);
        return (
          <section key={span.id} className="ah-brain-group" aria-labelledby={span.id}>
            <h2 id={span.id} className="ah-brain-group-label">
              {span.label}
            </h2>
            <ul
              className="ah-brain-rows"
              style={{ paddingTop: rows[0]?.space ?? 0, paddingBottom: below }}
            >
              {rows.map(({ row, space }, at) => (
                <TreeItem
                  key={row.path}
                  row={row}
                  space={at === 0 ? 0 : space}
                  project={project}
                  selected={selected}
                  opened={open.has(row.path)}
                  current={row.path === roving}
                  onUse={setCurrent}
                  onToggle={toggle}
                  onKey={onKey}
                />
              ))}
            </ul>
            {span.group === "inbox" && (
              <AppLink
                href={`/knowledge/learnings?scope=${encodeURIComponent(project)}`}
                className="ah-brain-link"
              >
                <Icon name="lightbulb" size="sm" />
                <span>Triage in Learnings</span>
              </AppLink>
            )}
          </section>
        );
      })}
    </div>
  );
}
