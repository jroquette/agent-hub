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
 * or the X closes it and returns focus to `openerRef`. It overlays the page (`panel` 480 px,
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
  children?: ReactNode;
}) {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const wide = useWide();
  const latest = useRef({ onClose, openerRef });
  useEffect(() => {
    latest.current = { onClose, openerRef };
  });

  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);

  const close = () => {
    latest.current.onClose();
    const opener = latest.current.openerRef.current;
    if (opener?.isConnected) opener.focus({ preventScroll: true });
  };
  const closing = useRef(close);
  useEffect(() => {
    closing.current = close;
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
      className="ah-side-panel"
      aria-labelledby={headingId}
      data-layout={wide ? "docked" : "overlay"}
    >
      <div className="ah-side-panel-head">
        <h2 id={headingId} ref={heading} tabIndex={-1} className="ah-h3">
          {title}
        </h2>
        <IconButton icon="x" label={closeLabel} onClick={close} />
      </div>
      <div className="ah-side-panel-body">{children}</div>
    </aside>
  );
}
