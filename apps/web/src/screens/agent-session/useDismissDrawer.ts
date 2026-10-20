import { useEffect, useRef } from "react";

// A click on one of these does its own thing (a toggle, a link, the composer): it never also closes the drawer.
const OWN_ACTION =
  "a, button, input, textarea, select, label, summary, [role='button'], [role='link'], [role='tab'], " +
  "[role='menuitem'], [role='option'], [contenteditable='true']";
// Inside a drawer, a dialog or a lightbox opened over the page, a click is not "outside".
const INSIDE = ".as-drawer, .as-drawer-handle, [role='dialog'], [role='alertdialog'], [role='menu']";

/** True when a click on `target` should close an open drawer. */
export function dismissesDrawer(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (target.closest(INSIDE) || target.closest(OWN_ACTION)) return false;
  // Ending a text selection is not a dismissal.
  return (window.getSelection()?.toString() ?? "") === "";
}

/**
 * Closes an open side drawer when the user clicks outside it, on space that has no action of its own.
 * Escape and the drawers' close buttons stay the other ways out.
 */
export function useDismissDrawer(open: boolean, onClose: () => void): void {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    if (!open) return undefined;
    const onClick = (event: MouseEvent) => {
      if (event.button === 0 && dismissesDrawer(event.target)) close.current();
    };
    document.addEventListener("click", onClick);
    return () => {
      document.removeEventListener("click", onClick);
    };
  }, [open]);
}
