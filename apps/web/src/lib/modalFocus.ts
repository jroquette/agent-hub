import { useEffect, useRef, type RefObject } from "react";

/** The controls a modal dialog's Tab cycles through (disabled ones are skipped). */
export const MODAL_FOCUSABLE =
  "button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), a[href]";

export interface ModalFocusOptions {
  /** While true, Escape does nothing (a request runs). */
  locked: boolean;
  onEscape: () => void;
  /** The control focused on open (a selector inside the dialog); else its first control. */
  initial?: string | undefined;
}

/**
 * A modal dialog's keyboard: focus moves in on open and back to where it was on close, Escape
 * cancels unless locked, and Tab cycles inside. With every control off (a request runs), focus
 * stays on the dialog itself, which needs `tabIndex={-1}`.
 */
export function useModalFocus(
  dialog: RefObject<HTMLElement | null>,
  { locked, onEscape, initial }: ModalFocusOptions,
): void {
  // The initial control is chosen once, on open.
  const opening = useRef(initial);
  useEffect(() => {
    const before = document.activeElement;
    const node = dialog.current;
    const selector = opening.current;
    const first =
      (selector ? node?.querySelector<HTMLElement>(selector) : null) ??
      node?.querySelector<HTMLElement>(MODAL_FOCUSABLE);
    first?.focus();
    return () => {
      if (before instanceof HTMLElement) before.focus();
    };
  }, [dialog]);

  // A control disabled while focused (the clicked confirm) drops focus to the page: take it back,
  // so the Tab trap and the Escape lock still hold.
  useEffect(() => {
    const node = dialog.current;
    const active = document.activeElement;
    const lost =
      !node?.contains(active) || (active instanceof HTMLElement && active.matches(":disabled"));
    if (locked && node && lost) node.focus();
  }, [dialog, locked]);

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        if (!locked) onEscape();
        return;
      }
      if (event.key !== "Tab") return;
      const items = [...node.querySelectorAll<HTMLElement>(MODAL_FOCUSABLE)];
      const head = items[0];
      const tail = items[items.length - 1];
      if (!head || !tail) {
        event.preventDefault();
        node.focus();
        return;
      }
      if (event.shiftKey && document.activeElement === head) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && document.activeElement === tail) {
        event.preventDefault();
        head.focus();
      }
    };
    node.addEventListener("keydown", onKeyDown);
    return () => {
      node.removeEventListener("keydown", onKeyDown);
    };
  }, [dialog, locked, onEscape]);
}
