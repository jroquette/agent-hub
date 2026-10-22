import { useEffect, useRef, type RefObject } from "react";

export interface PanelDismissOptions {
  /**
   * Whether Escape pressed outside the panel closes it too: true for a panel over the page, false
   * for one docked beside it (the page's own Escape keeps working there).
   */
  fromAnywhere?: () => boolean;
  /**
   * The control focus goes back to on close, read at close time. Without it, focus goes back to
   * the element that had it when the panel opened, else to `fallbackFocus`.
   */
  opener?: () => HTMLElement | null;
  /** Where focus goes on close when the control that opened the panel is gone. */
  fallbackFocus?: () => HTMLElement | null;
  /** Escape in a box with text in it stays the box's (a chat's composer). */
  keepTypedEscape?: boolean;
}

/** Text typed in a box keeps its Escape: closing the panel would throw the reader out of it. */
function typedIn(target: EventTarget | null): boolean {
  return (
    (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement) &&
    target.value !== ""
  );
}

/** A modal layer (a dialog, the palette, the lightbox) or an open menu answers its own Escape. */
const LAYER_ABOVE = "[aria-modal='true'], [role='menu']";

/**
 * A side panel's ways out, shared by the panels that are not modal (`SidePanel` and the Discuss
 * panel): Escape closes it (after any layer above it, which spends Escape first), and once closed,
 * by any path, focus goes back to its opener, unless the reader already moved it elsewhere on the
 * page.
 */
export function usePanelDismiss(
  panel: RefObject<HTMLElement | null>,
  onClose: () => void,
  options: PanelDismissOptions = {},
): void {
  const latest = useRef({ onClose, options });
  useEffect(() => {
    latest.current = { onClose, options };
  });

  useEffect(() => {
    const before = document.activeElement;
    const node = panel.current;
    return () => {
      const active = document.activeElement;
      const lost =
        active === null ||
        active === document.body ||
        !active.isConnected ||
        node?.contains(active) === true;
      if (!lost) return;
      const { opener, fallbackFocus } = latest.current.options;
      const back = opener
        ? opener()
        : before instanceof HTMLElement && before.isConnected && before !== document.body
          ? before
          : (fallbackFocus?.() ?? null);
      if (back?.isConnected) back.focus({ preventScroll: true });
    };
  }, [panel]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
      if (document.querySelector(LAYER_ABOVE)) return;
      if (latest.current.options.keepTypedEscape && typedIn(event.target)) return;
      const inside = event.target instanceof Node && panel.current?.contains(event.target) === true;
      if (!inside && !(latest.current.options.fromAnywhere?.() ?? true)) return;
      event.preventDefault();
      latest.current.onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [panel]);
}
