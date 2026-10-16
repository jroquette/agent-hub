import {
  useCallback,
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

function readWidth(): number | null {
  const value = Number(readStored(DRAWER_WIDTH_KEY));
  return Number.isFinite(value) && value >= DRAWER_MIN ? value : null;
}

/** The widest a drawer may be on a page `pageWidth` wide. */
export function drawerMax(pageWidth: number): number {
  return Math.max(DRAWER_MIN, pageWidth - CHAT_MIN);
}

export interface DrawerWidth {
  /** The drawer's inline style: its width when the user set one, else the page's default. */
  style: CSSProperties | undefined;
  /** Props of the drag handle on the drawer's left edge. */
  handle: {
    role: "separator";
    "aria-orientation": "vertical";
    "aria-label": string;
    "aria-valuemin": number;
    "aria-valuenow": number | undefined;
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
 * A drawer you can resize: drag its left edge, or focus the edge and press ←/→ (Home resets);
 * a double click goes back to the default. The width is kept in local storage.
 */
export function useDrawerWidth(): DrawerWidth {
  const [width, setWidth] = useState<number | null>(readWidth);
  const [before, setBefore] = useState<number | null>(null);

  const save = useCallback((next: number | null) => {
    setWidth(next);
    if (next === null) removeStored(DRAWER_WIDTH_KEY);
    else writeStored(DRAWER_WIDTH_KEY, String(Math.round(next)));
  }, []);

  const pageOf = (element: Element) => element.closest(".as-page")?.getBoundingClientRect();

  const clamp = (value: number, pageWidth: number) =>
    Math.min(drawerMax(pageWidth), Math.max(DRAWER_MIN, value));

  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const page = pageOf(event.currentTarget);
    if (!page) return;
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("as-resizing");
    const move = (moved: globalThis.PointerEvent) => {
      setWidth(clamp(page.right - moved.clientX, page.width));
    };
    const up = (ended: globalThis.PointerEvent) => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      document.body.classList.remove("as-resizing");
      save(clamp(page.right - ended.clientX, page.width));
      setBefore(null);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const page = pageOf(event.currentTarget);
    if (!page) return;
    const now = width ?? event.currentTarget.parentElement?.getBoundingClientRect().width ?? 0;
    if (event.key === "ArrowLeft") save(clamp(now + KEY_STEP, page.width));
    else if (event.key === "ArrowRight") save(clamp(now - KEY_STEP, page.width));
    else if (event.key === "Home") save(null);
    else return;
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
    // Wider than any page: the clamp in CSS (max-width) keeps the chat's minimum beside it.
    setWidth(100_000);
  };

  return {
    style:
      width === null
        ? undefined
        : ({ "--as-panel-w": `${String(Math.round(width))}px` } as CSSProperties),
    handle: {
      role: "separator",
      "aria-orientation": "vertical",
      "aria-label": "Resize the panel",
      "aria-valuemin": DRAWER_MIN,
      "aria-valuenow": width === null || wide ? undefined : Math.round(width),
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
