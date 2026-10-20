import { useEffect, useRef, type RefObject } from "react";

export interface PanelDismissOptions {
  /**
   * Whether Escape pressed outside the panel closes it too: true for a panel over the page, false
   * for one docked beside it (the page's own Escape keeps working there).
   */
  fromAnywhere?: () => boolean;
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

/**
 * A side panel's ways out, shared by the panels that are not modal: Escape closes it (after any
 * layer above it, which spends Escape first), and focus goes back to the control that had it
 * when the panel opened, else to `fallbackFocus`.
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
    return () => {
      const back =
        before instanceof HTMLElement && before.isConnected && before !== document.body
          ? before
          : latest.current.options.fallbackFocus?.();
      // Only take focus back from the panel (or from nowhere): never from where the reader went.
      const active = document.activeElement;
      if (active && active !== document.body && active.isConnected) return;
      back?.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
      // A dialog or a menu above the panel owns Escape.
      if (document.querySelector("[data-ah-dialog], [role='menu']")) return;
      if (latest.current.options.keepTypedEscape && typedIn(event.target)) return;
      const inside = event.target instanceof Node && panel.current?.contains(event.target);
      if (!inside && !(latest.current.options.fromAnywhere?.() ?? true)) return;
      latest.current.onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [panel]);
}
