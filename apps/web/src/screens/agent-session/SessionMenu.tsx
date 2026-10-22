import { useEffect, useRef, useState } from "react";

import { IconButton, MenuItem, Popover, type IconName } from "../../components";

/** A place the menu goes to; `narrowOnly` shows it only where the header has no room for it. */
export interface SessionMenuLink {
  icon: IconName;
  label: string;
  href: string;
  narrowOnly?: boolean | undefined;
}

export interface SessionMenuProps {
  links?: readonly SessionMenuLink[] | undefined;
  /** The ended background tasks, when none runs (the header shows only running ones). */
  onBackground?: { label: string; run: () => void } | undefined;
  onFork?: (() => void) | undefined;
  onClose?: (() => void) | undefined;
  onDelete?: (() => void) | undefined;
  busy?: boolean | undefined;
}

/**
 * The session's lifecycle actions (close, fork, delete), behind one "⋯" button
 * at the end of the header, so the header's visible actions are reviewing what Claude changed and its events.
 */
export function SessionMenu({
  links = [],
  onBackground,
  onFork,
  onClose,
  onDelete,
  busy,
}: SessionMenuProps) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: PointerEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      wrap.current?.querySelector<HTMLButtonElement>("button")?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const lifecycle = Boolean(onFork) || Boolean(onClose && !busy) || Boolean(onDelete && !busy);
  const places = links.length > 0 || onBackground !== undefined;
  if (!lifecycle && !places) return null;
  const run = (action: () => void) => () => {
    setOpen(false);
    action();
  };
  return (
    <span ref={wrap} style={{ position: "relative" }}>
      <IconButton
        icon="ellipsis"
        label="Session actions"
        size="sm"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      />
      <Popover open={open} label="Session actions" style={{ top: 30, right: 0, minWidth: 240 }}>
        {links.map((link) => (
          <MenuItem
            key={link.href}
            icon={link.icon}
            href={link.href}
            className={link.narrowOnly ? "as-narrow-only" : undefined}
          >
            {link.label}
          </MenuItem>
        ))}
        {onBackground && (
          <MenuItem icon="layers" onClick={run(onBackground.run)}>
            {onBackground.label}
          </MenuItem>
        )}
        {places && lifecycle && <div className="ah-menu-sep" role="separator" />}
        {onFork && (
          <MenuItem icon="git-branch" onClick={run(onFork)}>
            Fork…
          </MenuItem>
        )}
        {onClose && !busy && (
          <MenuItem icon="x" onClick={run(onClose)}>
            Close session
          </MenuItem>
        )}
        {onDelete && !busy && (
          <MenuItem icon="file-x" danger onClick={run(onDelete)}>
            Delete session
          </MenuItem>
        )}
      </Popover>
    </span>
  );
}
