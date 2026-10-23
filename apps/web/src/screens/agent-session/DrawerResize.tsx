import {
  useCallback,
  useEffect,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

import { readStored, removeStored, writeStored } from "../../lib/storage";

/** The side drawer's width, kept in this browser for every session's drawers. */
export const DRAWER_WIDTH_KEY = "ah.chat.drawer.width";
export const DRAWER_MIN = 320;
/** The chat keeps at least this much beside a drawer the user widened. */
const CHAT_MIN = 280;
const KEY_STEP = 40;

function readWidth(key: string, min: number): number | null {
  const value = Number(readStored(key));
  return Number.isFinite(value) && value >= min ? value : null;
}

/** The widest a drawer may be on a page `pageWidth` wide. */
export function drawerMax(pageWidth: number): number {
  return Math.max(DRAWER_MIN, pageWidth - CHAT_MIN);
}

/** Where a resizable panel's right edge is, and the widest it may be, measured from its handle. */
export interface PanelBounds {
  right: number;
  max: number;
}

export interface DrawerWidthOptions {
  /** Where the chosen width is kept in this browser. */
  storageKey?: string;
  /** The CSS custom property the style sets. */
  cssVar?: string;
  /** The handle's accessible name. */
  label?: string;
  /** The panel's width before the user sets one, for the separator before it is measured. */
  defaultWidth?: number;
  /** The panel's right edge and its widest width; by default the session page's. */
  bounds?: (handle: Element) => PanelBounds | null;
}

const pageBounds = (handle: Element): PanelBounds | null => {
  const page = handle.closest(".as-page")?.getBoundingClientRect();
  return page ? { right: page.right, max: drawerMax(page.width) } : null;
};

export interface DrawerWidth {
  /** The panel's inline style: its width when the user set one, else the page's default. */
  style: CSSProperties | undefined;
  /** Props of the drag handle on the panel's left edge. */
  handle: {
    ref: (element: HTMLElement | null) => void;
    role: "separator";
    "aria-orientation": "vertical";
    "aria-label": string;
    "aria-valuemin": number;
    "aria-valuemax": number;
    "aria-valuenow": number;
    "aria-valuetext": string;
    tabIndex: 0;
    className: string;
    onPointerDown: (event: PointerEvent<HTMLElement>) => void;
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
    onDoubleClick: () => void;
  };
  /** Fills the page beside a narrow chat, or goes back to the width it had. */
  toggleWide: () => void;
  wide: boolean;
}

/**
 * A panel you can resize: drag its left edge, or focus the edge and press the arrows (Home
 * resets, End goes to the widest); a double click goes back to the default. The width is kept in
 * local storage. The handle always tells assistive tech the width shown and the widest it may be.
 */
export function useDrawerWidth(options: DrawerWidthOptions = {}): DrawerWidth {
  const {
    storageKey = DRAWER_WIDTH_KEY,
    cssVar = "--as-panel-w",
    label = "Resize the panel",
    bounds = pageBounds,
    defaultWidth = DRAWER_MIN,
  } = options;
  const [width, setWidth] = useState<number | null>(() => readWidth(storageKey, DRAWER_MIN));
  const [before, setBefore] = useState<number | null>(null);
  const [handleEl, setHandleEl] = useState<HTMLElement | null>(null);
  const [measured, setMeasured] = useState<{ now: number; max: number } | null>(null);

  // The width shown (CSS may clamp it) and the widest one, for the separator's values.
  useEffect(() => {
    const panel = handleEl?.parentElement;
    if (!handleEl || !panel) return undefined;
    const measure = () => {
      const shown = Math.round(panel.getBoundingClientRect().width);
      const edge = bounds(handleEl);
      setMeasured({ now: shown, max: Math.round(edge?.max ?? shown) });
    };
    measure();
    window.addEventListener("resize", measure);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(panel);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
    // `bounds` is fixed per caller; the handle is what changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handleEl]);

  const save = useCallback(
    (next: number | null) => {
      setWidth(next);
      if (next === null) removeStored(storageKey);
      else writeStored(storageKey, String(Math.round(next)));
    },
    [storageKey],
  );

  const clamp = (value: number, max: number) => Math.min(max, Math.max(DRAWER_MIN, value));

  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const edge = bounds(event.currentTarget);
    if (!edge) return;
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("as-resizing");
    const move = (moved: globalThis.PointerEvent) => {
      setWidth(clamp(edge.right - moved.clientX, edge.max));
    };
    const up = (ended: globalThis.PointerEvent) => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      document.body.classList.remove("as-resizing");
      save(clamp(edge.right - ended.clientX, edge.max));
      setBefore(null);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const edge = bounds(event.currentTarget);
    if (!edge) return;
    const now = width ?? event.currentTarget.parentElement?.getBoundingClientRect().width ?? 0;
    const pressed = event.key;
    if (pressed === "ArrowLeft") save(clamp(now + KEY_STEP, edge.max));
    else if (pressed === "ArrowRight") save(clamp(now - KEY_STEP, edge.max));
    else if (pressed === "Home") save(null);
    else if (pressed === "End") save(edge.max);
    else return;
    setBefore(null);
    event.preventDefault();
  };

  const wide = before !== null;
  const toggleWide = () => {
    if (wide) {
      save(before === 0 ? null : before);
      setBefore(null);
      return;
    }
    setBefore(width ?? 0);
    // Wider than any page: the clamp in CSS keeps the page's minimum beside it.
    setWidth(100_000);
  };

  // Without layout (no width measured), the width chosen is the best answer.
  const chosen = width === null || wide ? undefined : Math.round(width);
  const now = measured && measured.now > 0 ? measured.now : (chosen ?? defaultWidth);
  const max =
    measured && measured.max > 0 ? Math.max(measured.max, now) : Math.max(now, DRAWER_MIN);
  return {
    style: width === null ? undefined : { [cssVar]: `${String(Math.round(width))}px` },
    handle: {
      ref: setHandleEl,
      role: "separator",
      "aria-orientation": "vertical",
      "aria-label": label,
      "aria-valuemin": DRAWER_MIN,
      "aria-valuemax": max,
      "aria-valuenow": now,
      "aria-valuetext": `${String(now)} pixels wide`,
      tabIndex: 0,
      className: "as-drawer-handle",
      onPointerDown,
      onKeyDown,
      onDoubleClick: () => {
        save(null);
        setBefore(null);
      },
    },
    toggleWide,
    wide,
  };
}

/** The file list's width beside the open file, kept in this browser for every session. */
export const LIST_WIDTH_KEY = "ah.chat.files.list.width";
export const LIST_MIN = 200;
const LIST_DEFAULT = 280;
/** The open file keeps at least this much beside the list. */
const DETAIL_MIN = 360;

/** The widest the list may be in a drawer body `bodyWidth` wide. */
export function listMax(bodyWidth: number): number {
  return Math.max(LIST_MIN, Math.min(bodyWidth * 0.6, bodyWidth - DETAIL_MIN));
}

/** How wide `element` is, followed as it resizes (0 without a ResizeObserver). */
export function useWidth(element: HTMLElement | null): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!element || typeof ResizeObserver !== "function") return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [element]);
  return width;
}

export interface ListWidthOptions {
  /** Where the chosen width is kept in this browser. */
  storageKey?: string;
  min?: number;
  defaultWidth?: number;
  /** The widest the panel may be in a body `bodyWidth` wide. */
  max?: (bodyWidth: number) => number;
  /** The CSS custom property the style sets. */
  cssVar?: string;
  /** The handle's accessible name. */
  label?: string;
  /** The handle's class, after `as-drawer-handle`. */
  className?: string;
}

/**
 * A panel on the left of its body, resized from its right edge like the drawer: drag it, or
 * focus it and press →/← (Home or a double click resets). Kept in local storage; the panel never
 * grows past `max` of its body, however the body is resized. The handle's parent is the body.
 * By default, the split between the file list and the open file.
 */
export function useListWidth(bodyWidth: number, options: ListWidthOptions = {}) {
  const {
    storageKey = LIST_WIDTH_KEY,
    min = LIST_MIN,
    defaultWidth = LIST_DEFAULT,
    max: maxOf = listMax,
    cssVar = "--as-files-list-w",
    label = "Resize the file list",
    className = "as-files-split-handle",
  } = options;
  const [width, setWidth] = useState<number | null>(() => readWidth(storageKey, min));
  const max = maxOf(bodyWidth);
  const shown = Math.min(max, width ?? defaultWidth);

  const save = useCallback(
    (next: number | null) => {
      setWidth(next);
      if (next === null) removeStored(storageKey);
      else writeStored(storageKey, String(Math.round(next)));
    },
    [storageKey],
  );
  const clamp = (value: number, body: number) => Math.min(maxOf(body), Math.max(min, value));

  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const body = event.currentTarget.parentElement?.getBoundingClientRect();
    if (!body) return;
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("as-resizing");
    const move = (moved: globalThis.PointerEvent) => {
      setWidth(clamp(moved.clientX - body.left, body.width));
    };
    const up = (ended: globalThis.PointerEvent) => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      document.body.classList.remove("as-resizing");
      save(clamp(ended.clientX - body.left, body.width));
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    // The handle is on the panel's right edge: → widens it, ← narrows it.
    if (event.key === "ArrowRight") save(clamp(shown + KEY_STEP, bodyWidth));
    else if (event.key === "ArrowLeft") save(clamp(shown - KEY_STEP, bodyWidth));
    else if (event.key === "Home") save(null);
    else return;
    event.preventDefault();
  };

  return {
    style: { [cssVar]: `${String(Math.round(shown))}px` } as CSSProperties,
    handle: {
      role: "separator" as const,
      "aria-orientation": "vertical" as const,
      "aria-label": label,
      "aria-valuemin": min,
      "aria-valuemax": Math.round(max),
      "aria-valuenow": Math.round(shown),
      tabIndex: 0,
      className: `as-drawer-handle ${className}`,
      onPointerDown,
      onKeyDown,
      onDoubleClick: () => {
        save(null);
      },
    },
  };
}
