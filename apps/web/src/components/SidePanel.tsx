import "./SidePanel.css";

import { useEffect, useId, useRef, type ReactNode } from "react";

import { IconButton } from "./core";

export interface SidePanelProps {
  /** The panel's heading; also its accessible name. */
  title: ReactNode;
  /** The close button's accessible name, e.g. "Close Demo_API › api". */
  closeLabel: string;
  /** Actions beside the title (a Rename button). */
  actions?: ReactNode;
  children?: ReactNode;
  /** The action row at the bottom. */
  footer?: ReactNode;
  onClose: () => void;
  /** A selector for the control focused on open; else the first control of the body. */
  initialFocus?: string | undefined;
}

/**
 * A record's detail over the page, from the right edge: `panel` wide, no scrim, the page stays
 * readable and scrollable. Not modal (a Dialog is): Escape and the close button close it, focus
 * returns to the control that opened it. A Dialog opened above it keeps its own Escape.
 */
export function SidePanel({
  title,
  closeLabel,
  actions,
  children,
  footer,
  onClose,
  initialFocus,
}: SidePanelProps) {
  const id = useId();
  const panel = useRef<HTMLElement>(null);
  const latest = useRef(onClose);
  useEffect(() => {
    latest.current = onClose;
  });
  const opening = useRef(initialFocus);

  useEffect(() => {
    const before = document.activeElement;
    const node = panel.current;
    const chosen = opening.current ? node?.querySelector<HTMLElement>(opening.current) : null;
    const first =
      chosen ??
      node?.querySelector<HTMLElement>(
        ".ah-side-panel-body input, .ah-side-panel-body select, .ah-side-panel-body textarea, .ah-side-panel-body button",
      );
    (first ?? node)?.focus({ preventScroll: true });
    return () => {
      if (before instanceof HTMLElement && before.isConnected)
        before.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
      // A dialog above the panel (a confirmation) owns Escape.
      if (document.querySelector("[data-ah-dialog]")) return;
      latest.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <aside
      ref={panel}
      className="ah-side-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby={`${id}-title`}
      tabIndex={-1}
    >
      <header className="ah-side-panel-head">
        <h2 className="ah-h3 ah-side-panel-title" id={`${id}-title`}>
          {title}
        </h2>
        {actions}
        <IconButton icon="x" variant="ghost" size="sm" label={closeLabel} onClick={onClose} />
      </header>
      <div className="ah-side-panel-body">{children}</div>
      {footer && <footer className="ah-side-panel-foot">{footer}</footer>}
    </aside>
  );
}
