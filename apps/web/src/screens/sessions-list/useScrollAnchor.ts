/* Live refetches never move the reader's scroll or drop their focus (AC-234.9, spec 14 "Stable scroll"). */
import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

const ROW = "tr[data-key]";
/** Visible rows remembered as anchors: the first one still in its section wins. */
const CANDIDATES = 5;

interface Anchor {
  key: string;
  section: string | undefined;
  top: number;
}

/** The nearest scrolling ancestor, else the document's scroller. */
function scrollerOf(element: Element): Element {
  for (let node = element.parentElement; node; node = node.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(node).overflowY)) return node;
  }
  return document.scrollingElement ?? document.documentElement;
}

/** A row's section, by the id of the section's header button. */
const sectionOf = (row: Element) =>
  row.closest("section")?.getAttribute("aria-labelledby") ?? undefined;

function rowByKey(container: Element, key: string) {
  return [...container.querySelectorAll<HTMLElement>(ROW)].find((row) => row.dataset.key === key);
}

/** The first visible rows (by key, section and offset from the scroller's top). */
function measure(container: Element, scroller: Element): Anchor[] {
  const top = scroller === document.scrollingElement ? 0 : scroller.getBoundingClientRect().top;
  const anchors: Anchor[] = [];
  for (const row of container.querySelectorAll<HTMLElement>(ROW)) {
    const rect = row.getBoundingClientRect();
    if (rect.bottom <= top) continue;
    anchors.push({ key: row.dataset.key ?? "", section: sectionOf(row), top: rect.top });
    if (anchors.length === CANDIDATES) break;
  }
  return anchors;
}

/**
 * On every commit inside `container`: scrolls back so the first visible row that stayed in its
 * section keeps its offset (not at the very top, where new rows should show), and puts back focus
 * that a re-rendered row took with it, on the row by key, else on its section's header.
 */
export function useScrollAnchor(container: RefObject<HTMLElement | null>): void {
  const anchors = useRef<Anchor[]>([]);
  /** The row focus is on (set on focusin, cleared when the reader moves focus out). */
  const focused = useRef<Omit<Anchor, "top"> | null>(null);

  useLayoutEffect(() => {
    const root = container.current;
    if (!root) return;
    const scroller = scrollerOf(root);
    const kept = anchors.current
      .map((anchor) => ({ anchor, row: rowByKey(root, anchor.key) }))
      .find(({ anchor, row }) => row && sectionOf(row) === anchor.section);
    if (kept?.row && scroller.scrollTop > 0) {
      scroller.scrollTop += kept.row.getBoundingClientRect().top - kept.anchor.top;
    }
    // Focusing the element that has focus is a no-op; a row that moved gets it back on its copy.
    if (focused.current) {
      const { key, section } = focused.current;
      const header = section ? document.getElementById(section) : null;
      const target = rowByKey(root, key) ?? header ?? root.querySelector("section button");
      if (target instanceof HTMLElement) target.focus({ preventScroll: true });
    }
    anchors.current = measure(root, scroller);
  });

  useEffect(() => {
    const root = container.current;
    if (!root) return undefined;
    const scroller = scrollerOf(root);
    const listener = scroller === document.scrollingElement ? window : scroller;
    const onScroll = () => {
      anchors.current = measure(root, scroller);
    };
    const onFocusIn = (event: FocusEvent) => {
      // Only the row itself: focus on a control inside it stays where the reader put it.
      const row = event.target as Element;
      focused.current =
        row instanceof HTMLElement && row.matches(ROW) && row.dataset.key
          ? { key: row.dataset.key, section: sectionOf(row) }
          : null;
    };
    // Focus the reader moved out (the row is still there) is theirs: forget the row.
    const onFocusOut = (event: FocusEvent) => {
      if ((event.target as Element).isConnected) focused.current = null;
    };
    listener.addEventListener("scroll", onScroll, { passive: true });
    root.addEventListener("focusin", onFocusIn);
    root.addEventListener("focusout", onFocusOut);
    return () => {
      listener.removeEventListener("scroll", onScroll);
      root.removeEventListener("focusin", onFocusIn);
      root.removeEventListener("focusout", onFocusOut);
    };
  }, [container]);
}
