import "./SidePanel.css";

import { useEffect, useId, useRef } from "react";
import type { ReactNode, RefObject } from "react";

import { IconButton } from "./core";
import { useMediaQuery } from "../lib/useMediaQuery";
import { usePanelDismiss } from "./usePanelDismiss";

/** Where side panels dock instead of overlaying the page (`31-responsive.md`, Wide). */
const WIDE = "(min-width: 1600px)";

function useWide(): boolean {
  return useMediaQuery(WIDE);
}

/**
 * A non-modal side panel (two-level-flows AC-1.10): an `aside` named by its heading, with no scrim
 * and no focus trap, so the page stays usable beside it. Opening moves focus to the heading; Esc
 * or the X closes it, and once closed focus returns to `openerRef`. It overlays the page (`panel` 480 px,
 * `shadow-overlay`) below 1600 px and docks beside it (640 px) from there. A `footer` is an action
 * row kept below the scrolling body; `initialFocus` names the control to focus instead of the heading.
 */
export function SidePanel({
  title,
  closeLabel,
  onClose,
  openerRef,
  children,
  footer,
  initialFocus,
  layout = "auto",
  focusOnOpen = true,
}: {
  title: ReactNode;
  /** The X's name ("Close ticket AGH-7"). */
  closeLabel: string;
  onClose: () => void;
  /** The element that opened the panel: focus goes back to it on close. */
  openerRef: RefObject<HTMLElement | null>;
  /** The body; as a function it gets the panel's close, which returns focus to the opener. */
  children?: ReactNode;
  /** An action row below the body (Cancel, Save), always in view. */
  footer?: ReactNode;
  /** A selector, inside the panel, of the control focused on open instead of the heading. */
  initialFocus?: string | undefined;
  /** "inline": in the parent's flow (a column of an editor), never over the page. */
  layout?: "auto" | "inline";
  /** False when a mouse click opened it beside what it edits: focus stays where it was. */
  focusOnOpen?: boolean;
}) {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLElement>(null);
  const wide = useWide();
  const opening = useRef(initialFocus);
  const focusing = useRef(focusOnOpen);
  // Opening focuses the heading (or the `initialFocus` control); closing, by any path (Esc, the X,
  // a Close button inside), gives focus back to the opener as it is at close (a panel switched in
  // place, or a toggled view, updates it), unless the reader already moved it elsewhere on the page.
  useEffect(() => {
    if (!focusing.current) return;
    const chosen = opening.current
      ? panel.current?.querySelector<HTMLElement>(opening.current)
      : null;
    (chosen ?? heading.current)?.focus({ preventScroll: true });
  }, []);
  usePanelDismiss(panel, onClose, { opener: () => openerRef.current });

  return (
    <aside
      ref={panel}
      className="ah-side-panel"
      aria-labelledby={headingId}
      data-layout={layout === "inline" ? "inline" : wide ? "docked" : "overlay"}
    >
      <div className="ah-side-panel-head">
        <h2 id={headingId} ref={heading} tabIndex={-1} className="ah-h3">
          {title}
        </h2>
        <IconButton icon="x" label={closeLabel} onClick={onClose} />
      </div>
      <div className="ah-side-panel-body">{children}</div>
      {footer !== undefined && <div className="ah-side-panel-foot">{footer}</div>}
    </aside>
  );
}
