import { useEffect, useId, useRef } from "react";
import type { MouseEvent, ReactNode } from "react";
import { createPortal } from "react-dom";

import { cx } from "../lib/cx";
import { MODAL_FOCUSABLE } from "../lib/modalFocus";
import { Button } from "./core";
import { Icon } from "./Icon";

/** The open dialogs, oldest first: only the last one answers Escape and Tab. */
const openDialogs: string[] = [];
/** How many open dialogs lock the page's scroll, and the body's overflow before the first. */
let scrollLocks = 0;
let overflowBefore = "";

export interface DialogProps {
  title: ReactNode;
  children?: ReactNode;
  /** The action row (Cancel, then the verb). */
  footer?: ReactNode;
  /** Escape, the X and a press on the scrim call it; without it there is no X. */
  onClose?: (() => void) | undefined;
  size?: "sm" | "md" | "lg";
  /** While true (a request runs), nothing closes the dialog. */
  pending?: boolean | undefined;
  role?: "dialog" | "alertdialog";
  /** A selector for the control focused on open; else the first control after the header. */
  initialFocus?: string | undefined;
  /** Renders in place (a gallery or a test), without the portal or the scroll lock. */
  inline?: boolean | undefined;
  className?: string | undefined;
}

/**
 * A modal dialog (AC-234.13): portal, title and X, footer, Tab kept inside, Escape for the
 * topmost only, scrim press that starts and ends on the scrim, body scroll locked while any is
 * open, and focus back on the opener on close.
 */
export function Dialog({
  title,
  children,
  footer,
  onClose,
  size = "md",
  pending = false,
  role = "dialog",
  initialFocus,
  inline,
  className,
}: DialogProps) {
  const id = useId();
  const titleId = `${id}-title`;
  const panel = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const pressedScrim = useRef(false);
  const latest = useRef({ onClose, pending });
  useEffect(() => {
    latest.current = { onClose, pending };
  });
  // The control focused on open is chosen once.
  const opening = useRef(initialFocus);

  useEffect(() => {
    const before = document.activeElement;
    const node = panel.current;
    const chosen = opening.current ? node?.querySelector<HTMLElement>(opening.current) : null;
    const controls = [...(node?.querySelectorAll<HTMLElement>(MODAL_FOCUSABLE) ?? [])];
    const first = chosen ?? controls.find((c) => !head.current?.contains(c)) ?? controls[0];
    (first ?? node)?.focus({ preventScroll: true });
    return () => {
      if (before instanceof HTMLElement && before.isConnected)
        before.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    openDialogs.push(id);
    const onKey = (event: KeyboardEvent) => {
      const node = panel.current;
      if (!node || openDialogs[openDialogs.length - 1] !== id) return;
      if (event.key === "Escape") {
        if (!latest.current.pending) latest.current.onClose?.();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = [...node.querySelectorAll<HTMLElement>(MODAL_FOCUSABLE)];
      const first = controls[0];
      const last = controls[controls.length - 1];
      const active = document.activeElement;
      if (!first || !last) {
        event.preventDefault();
        node.focus();
      } else if (!node.contains(active) || (!event.shiftKey && active === last)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && (active === first || active === node)) {
        event.preventDefault();
        last.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      openDialogs.splice(openDialogs.indexOf(id), 1);
    };
  }, [id]);

  useEffect(() => {
    if (inline) return undefined;
    if (scrollLocks++ === 0) {
      overflowBefore = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    return () => {
      if (--scrollLocks === 0) document.body.style.overflow = overflowBefore;
    };
  }, [inline]);

  // A control disabled while focused (the clicked verb) drops focus to the page: take it back.
  useEffect(() => {
    const node = panel.current;
    const active = document.activeElement;
    const lost =
      !node?.contains(active) || (active instanceof HTMLElement && active.matches(":disabled"));
    if (pending && node && lost) node.focus({ preventScroll: true });
  }, [pending]);

  const onScrimClick = (event: MouseEvent<HTMLDivElement>) => {
    const fromScrim = pressedScrim.current && event.target === event.currentTarget;
    pressedScrim.current = false;
    if (fromScrim && !pending) onClose?.();
  };

  const dialog = (
    <div
      className={cx("ah-scrim", inline && "ah-scrim-inline")}
      onMouseDown={(event) => {
        pressedScrim.current = event.target === event.currentTarget;
      }}
      onClick={onScrimClick}
      role="presentation"
    >
      <div
        ref={panel}
        className={cx("ah-dialog", "ah-dialog-frame", `ah-dialog-${size}`, className)}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={pending || undefined}
        tabIndex={-1}
      >
        <div ref={head} className="ah-dialog-head">
          <h2 id={titleId} className="ah-h3 ah-grow">
            {title}
          </h2>
          {onClose && (
            <Button
              size="sm"
              variant="ghost"
              aria-label="Close"
              disabled={pending}
              onClick={onClose}
            >
              <Icon name="x" size="sm" />
            </Button>
          )}
        </div>
        <div className="ah-dialog-body">{children}</div>
        {footer && <div className="ah-dialog-foot">{footer}</div>}
      </div>
    </div>
  );
  return inline ? dialog : createPortal(dialog, document.body);
}
