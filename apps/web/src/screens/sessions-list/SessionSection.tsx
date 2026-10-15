/* One status section of Sessions: a header button that collapses it, then its body (spec 14). */
import { useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "../../components";
import { fmtInt } from "../../lib/format";
import { readStored, writeStored } from "../../lib/storage";
import { SECTIONS, type SectionId } from "./sections";

const COLLAPSED_KEY = "ah.sessions.collapsed";

/** The stored collapsed sections; bad JSON or unknown keys read as the default (none collapsed). */
function readCollapsed(): Set<SectionId> {
  try {
    const value: unknown = JSON.parse(readStored(COLLAPSED_KEY) ?? "[]");
    const stored: unknown[] = Array.isArray(value) ? value : [];
    return new Set(SECTIONS.map((section) => section.id).filter((id) => stored.includes(id)));
  } catch {
    return new Set();
  }
}

/** The collapsed sections, kept in `ah.sessions.collapsed`, and a toggle for one of them. */
export function useCollapsed(): [Set<SectionId>, (id: SectionId) => void] {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const toggle = (id: SectionId) => {
    const next = new Set(collapsed);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    writeStored(COLLAPSED_KEY, JSON.stringify([...next]));
    setCollapsed(next);
  };
  return [collapsed, toggle];
}

export function SessionSection({
  id,
  title,
  count,
  approximate,
  updating = false,
  collapsed,
  onToggle,
  children,
}: {
  id: SectionId;
  title: string;
  /** Null while the section loads. */
  count: number | null;
  approximate: boolean;
  /** Showing the previous filters' pages while the new ones load. */
  updating?: boolean;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const bodyId = `sl-section-${id}`;
  const shown = count === null ? "…" : `${approximate ? "~" : ""}${fmtInt(count)}`;
  return (
    <section
      className="sl-section"
      aria-labelledby={`${bodyId}-head`}
      aria-busy={updating || undefined}
      data-updating={updating || undefined}
    >
      <h2 className="sl-section-head">
        <button
          type="button"
          id={`${bodyId}-head`}
          className="sl-section-toggle"
          aria-expanded={!collapsed}
          aria-controls={bodyId}
          onClick={onToggle}
        >
          <Icon name={collapsed ? "chevron-right" : "chevron-down"} size="sm" />
          {`${title} · ${shown}`}
        </button>
        {updating && <span className="sl-section-updating ah-muted">Updating…</span>}
      </h2>
      <div id={bodyId} hidden={collapsed}>
        {!collapsed && children}
      </div>
    </section>
  );
}
