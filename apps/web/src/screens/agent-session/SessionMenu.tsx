import { useEffect, useRef, useState } from "react";

import { IconButton, MenuItem, Popover } from "../../components";

export interface SessionMenuProps {
  onFork?: (() => void) | undefined;
  onClose?: (() => void) | undefined;
  onDelete?: (() => void) | undefined;
  busy?: boolean | undefined;
}

/**
 * The session's lifecycle actions (close, fork, delete), behind one "⋯" button
 * at the end of the header, so the header's visible actions are reviewing what Claude changed and its events.
 */
export function SessionMenu({ onFork, onClose, onDelete, busy }: SessionMenuProps) {
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

  if (!onFork && !onClose && !onDelete) return null;
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
        variant="default"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      />
      <Popover open={open} label="Session actions" style={{ top: 34, right: 0, minWidth: 220 }}>
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
