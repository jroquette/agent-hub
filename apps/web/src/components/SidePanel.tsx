import "./SidePanel.css";

import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";

import { IconButton } from "./core";

/** Where side panels dock instead of overlaying the page (`31-responsive.md`, Wide). */
const WIDE = "(min-width: 1600px)";

function useWide(): boolean {
  const query = () => typeof window.matchMedia === "function" && window.matchMedia(WIDE).matches;
  const [wide, setWide] = useState(query);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const list = window.matchMedia(WIDE);
    const onChange = () => {
      setWide(list.matches);
    };
    list.addEventListener("change", onChange);
    return () => {
      list.removeEventListener("change", onChange);
    };
  }, []);
  return wide;
}

/**
 * A non-modal side panel (two-level-flows AC-1.10): an `aside` named by its heading, with no scrim
 * and no focus trap, so the page stays usable beside it. Opening moves focus to the heading; Esc
 * or the X closes it, and once closed focus returns to `openerRef`. It overlays the page (`panel` 480 px,
 * `shadow-overlay`) below 1600 px and docks beside it (640 px) from there.
 */
export function SidePanel({
  title,
  closeLabel,
  onClose,
  openerRef,
  children,
}: {
  title: ReactNode;
  /** The X's name ("Close ticket AGH-7"). */
  closeLabel: string;
  onClose: () => void;
  /** The element that opened the panel: focus goes back to it on close. */
  openerRef: RefObject<HTMLElement | null>;
  /** The body; as a function it gets the panel's close, which returns focus to the opener. */
  children?: ReactNode;
}) {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLElement>(null);
  const wide = useWide();
  // Opening focuses the heading; closing, by any path (Esc, the X, a Close button inside), gives
  // focus back to the opener, unless the reader already moved it elsewhere on the page.
  useEffect(() => {
    const node = panel.current;
    heading.current?.focus({ preventScroll: true });
    return () => {
      const active = document.activeElement;
      const lost = active === null || active === document.body || node?.contains(active) === true;
      // The opener as it is at close: a panel switched in place, or a toggled view, updates it.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      const opener = openerRef.current;
      if (lost && opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [openerRef]);

  const closing = useRef(onClose);
  useEffect(() => {
    closing.current = onClose;
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      // A modal layer above the page (a dialog, the palette) answers its own Escape.
      if (document.querySelector('[aria-modal="true"]')) return;
      event.preventDefault();
      closing.current();
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
      aria-labelledby={headingId}
      data-layout={wide ? "docked" : "overlay"}
    >
      <div className="ah-side-panel-head">
        <h2 id={headingId} ref={heading} tabIndex={-1} className="ah-h3">
          {title}
        </h2>
        <IconButton icon="x" label={closeLabel} onClick={onClose} />
      </div>
      <div className="ah-side-panel-body">{children}</div>
    </aside>
  );
}
