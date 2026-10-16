/* The catalog's Create button: pick a kind, then build it with Claude in the Studio. */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { Button, MenuItem, Popover } from "../../components";
import { KINDS, KIND_HELP } from "./filters";
import { KIND_ICON, KIND_NAME } from "./SkillCard";
import { newDraftRoute } from "./Studio";

export function CreateMenu({ project }: { project: string }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div className="ah-create-menu" ref={root}>
      <Button
        variant="primary"
        icon="plus"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          setOpen(!open);
        }}
      >
        Create with Claude
      </Button>
      <Popover open={open} label="Create with Claude" className="ah-create-pop">
        {KINDS.map((kind) => (
          <MenuItem
            key={kind}
            icon={KIND_ICON[kind]}
            onClick={() => {
              setOpen(false);
              void navigate(newDraftRoute(project, kind));
            }}
          >
            <span className="ah-create-item">
              <b>{KIND_NAME[kind]}</b>
              <span>{KIND_HELP[kind]}</span>
            </span>
          </MenuItem>
        ))}
      </Popover>
    </div>
  );
}
