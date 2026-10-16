/* Live refetches never move the reader's scroll or drop their focus (AC-234.9, spec 14 "Stable scroll"). */
import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

import type { SectionId } from "./sections";

/** A table row or a grid tile, keyed by its session. */
const ROW = "tr[data-key], article[data-key]";
/** A section past 100 rows scrolls in its own bounded region. */
const REGION = ".ah-table-wrap > div[tabindex]";
/** Visible rows remembered per scroller: the first one still in place among its neighbours wins. */
const CANDIDATES = 5;

interface Anchor {
  key: string;
  section: string | undefined;
  /** The key of the next candidate in the same section: a row that moved within it is not used. */
  next: string | undefined;
  top: number;
}

/** The nearest scrolling ancestor, else the document's scroller. */
function scrollerOf(element: Element): Element {
  for (let node = element.parentElement; node; node = node.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(node).overflowY)) return node;
  }
  return document.scrollingElement ?? document.documentElement;
}

/** An element's section, by the id of the section's header button. */
const sectionOf = (element: Element) =>
  element.closest("section")?.getAttribute("aria-labelledby") ?? undefined;
const keyOf = (element: HTMLElement) => element.dataset.key ?? `region:${sectionOf(element) ?? ""}`;
const topOf = (scroller: Element) =>
  scroller === document.scrollingElement ? 0 : scroller.getBoundingClientRect().top;

/**
 * Each scroller and what it can anchor on, in order: the page (rows outside bounded regions, and
 * the regions), then each bounded region (its rows), keyed "page" or by the region's key.
 */
function scopes(root: HTMLElement): Map<string, { scroller: Element; items: HTMLElement[] }> {
  const all = [...root.querySelectorAll<HTMLElement>(`${ROW}, ${REGION}`)];
  const map = new Map([
    [
      "page",
      {
        scroller: scrollerOf(root),
        items: all.filter((el) => el.matches(REGION) || !el.closest(REGION)),
      },
    ],
  ]);
  for (const region of all.filter((el) => el.matches(REGION))) {
    map.set(keyOf(region), {
      scroller: region,
      items: [...region.querySelectorAll<HTMLElement>(ROW)],
    });
  }
  return map;
}

/** The key of the item after `element` when it is in the same section. */
function nextKey(items: HTMLElement[], element: HTMLElement): string | undefined {
  const next = items[items.indexOf(element) + 1];
  return next && sectionOf(next) === sectionOf(element) ? keyOf(next) : undefined;
}

/** The first visible items of one scroller. */
function measure(scroller: Element, items: HTMLElement[]): Anchor[] {
  const top = topOf(scroller);
  const anchors: Anchor[] = [];
  for (const element of items) {
    const rect = element.getBoundingClientRect();
    if (rect.bottom <= top) continue;
    const next = nextKey(items, element);
    anchors.push({ key: keyOf(element), section: sectionOf(element), next, top: rect.top });
    if (anchors.length === CANDIDATES) break;
  }
  return anchors;
}

/** Scrolls `scroller` so the first anchor still in place keeps its offset (not at the very top). */
function restore(scroller: Element, items: HTMLElement[], anchors: Anchor[]): void {
  if (scroller.scrollTop <= 0) return;
  for (const anchor of anchors) {
    const element = items.find((item) => keyOf(item) === anchor.key);
    if (
      !element ||
      sectionOf(element) !== anchor.section ||
      nextKey(items, element) !== anchor.next
    ) {
      continue;
    }
    scroller.scrollTop += element.getBoundingClientRect().top - anchor.top;
    return;
  }
}

/** Within a viewport's height of the page's visible area. */
function nearView(element: Element, scroller: Element): boolean {
  const top = topOf(scroller);
  const height = scroller.clientHeight || window.innerHeight;
  const rect = element.getBoundingClientRect();
  return rect.bottom >= top - height && rect.top <= top + 2 * height;
}

/**
 * Keeps the reader's place across the refetches it is armed for (`arm(ids)`, before they run):
 * on the commit that brings a section's new data (`updatedAt` changes), every scroller (page and
 * bounded regions) scrolls back so its first visible row or tile keeps its offset. Commits the reader
 * causes (sort, collapse, filters) are left alone. When such a commit removes the focused row
 * and focus fell to the page, focus moves to its copy, else to its section's header, when near.
 */
export function useScrollAnchor(
  container: RefObject<HTMLElement | null>,
  sections: Partial<Record<SectionId, { at: number; fetching: boolean }>>,
): (ids: SectionId[]) => void {
  const anchors = useRef(new Map<string, Anchor[]>());
  const armed = useRef(new Set<SectionId>());
  const seen = useRef(sections);
  const frame = useRef(0);
  /** The focused row; `header` holds focus for it while the row is between sections. */
  const focused = useRef<{
    row: HTMLElement;
    key: string;
    section: string | undefined;
    header?: HTMLElement;
  } | null>(null);

  const remember = () => {
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    const root = container.current;
    if (!root) return;
    const next = new Map<string, Anchor[]>();
    for (const [key, { scroller, items }] of scopes(root)) next.set(key, measure(scroller, items));
    anchors.current = next;
  };

  useLayoutEffect(() => {
    const root = container.current;
    if (!root) return;
    const changed = Object.entries(sections)
      .filter(([id, now]) => seen.current[id as SectionId]?.at !== now.at)
      .map(([id]) => id as SectionId);
    seen.current = sections;
    const act = changed.filter((id) => armed.current.has(id)).length > 0;
    // A flag ends with its refetch, answered (this commit) or not (failed, no new data).
    for (const id of armed.current) if (!sections[id]?.fetching) armed.current.delete(id);
    if (act) {
      for (const [key, { scroller, items }] of scopes(root)) {
        restore(scroller, items, anchors.current.get(key) ?? []);
      }
    }
    const lost = focused.current;
    if (lost && !lost.row.isConnected) {
      const active = document.activeElement;
      const fell = active === null || active === document.body || active === lost.header;
      const copy = [...root.querySelectorAll<HTMLElement>(ROW)].find(
        (row) => row.dataset.key === lost.key,
      );
      const header = lost.section ? document.getElementById(lost.section) : null;
      const target = copy ?? (lost.header ? null : header);
      focused.current = null;
      if (fell && target && nearView(target, scrollerOf(root))) {
        if (!copy) focused.current = { ...lost, header: target };
        target.focus({ preventScroll: true });
      }
    }
    remember();
  });

  useEffect(() => {
    const root = container.current;
    if (!root) return undefined;
    const scroller = scrollerOf(root);
    const listener = scroller === document.scrollingElement ? window : scroller;
    // One measurement per frame, for the page and the regions (scroll does not bubble: capture).
    const onScroll = () => {
      if (frame.current === 0) frame.current = requestAnimationFrame(remember);
    };
    const onFocusIn = (event: FocusEvent) => {
      // Only the row itself: focus on a control inside it stays where the reader put it.
      const row = event.target as HTMLElement;
      if (row === focused.current?.header) return;
      focused.current =
        row.matches(ROW) && row.dataset.key
          ? { row, key: row.dataset.key, section: sectionOf(row) }
          : null;
    };
    // Focus the reader moved out (the row is still there) is theirs: forget the row.
    const onFocusOut = (event: FocusEvent) => {
      if ((event.target as Element).isConnected) focused.current = null;
    };
    listener.addEventListener("scroll", onScroll, { passive: true, capture: true });
    root.addEventListener("focusin", onFocusIn);
    root.addEventListener("focusout", onFocusOut);
    return () => {
      cancelAnimationFrame(frame.current);
      listener.removeEventListener("scroll", onScroll, { capture: true });
      root.removeEventListener("focusin", onFocusIn);
      root.removeEventListener("focusout", onFocusOut);
    };
    // `remember` reads refs only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [container]);

  return (ids) => {
    // Measure now: the refetches may answer before the next frame.
    remember();
    for (const id of ids) armed.current.add(id);
  };
}
