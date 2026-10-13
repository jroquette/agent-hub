import { useState } from "react";

import type { components } from "../../api/schema";
import { Icon, MenuItem, Popover, Tooltip, type Status } from "../../components";

type AcCounts = components["schemas"]["AcCounts"];
export type FeaturePhase = components["schemas"]["FeaturePhase"];
export type Verdict = components["schemas"]["Verdict"];

/** The golden path in its fixed order (spec 17). */
export const PHASES: readonly { id: FeaturePhase; label: string; file?: string }[] = [
  { id: "spec", label: "Spec", file: "spec.md" },
  { id: "research", label: "Research", file: "research.md" },
  { id: "plan", label: "Plan", file: "plan.md" },
  { id: "tickets", label: "Tickets", file: "issues.md" },
  { id: "implement", label: "Implement" },
  { id: "review", label: "Review" },
  { id: "evaluate", label: "Evaluate", file: "eval.md" },
  { id: "shipped", label: "Shipped" },
];

export const VERDICT_STATUS: Record<Verdict, Status> = {
  SHIP: "done",
  "SHIP-WITH-OWNER-STEPS": "waiting",
  "NO-SHIP": "failed",
};

export function phaseIndex(phase: FeaturePhase): number {
  return PHASES.findIndex((p) => p.id === phase);
}

/** "21/21 · 1 owner step": owner steps count in the numerator but are hatched (spec 17). */
export function acLabel(acs: AcCounts): string {
  const owner = acs.owner_steps;
  const head = `${String(acs.passing + owner)}/${String(acs.total)}`;
  return owner ? `${head} · ${String(owner)} owner step${owner === 1 ? "" : "s"}` : head;
}

export function AcBar({
  acs,
  width = 120,
  ownerIds,
}: {
  acs: AcCounts;
  width?: number;
  ownerIds?: string[] | undefined;
}) {
  const rest = Math.max(0, acs.total - acs.passing - acs.owner_steps);
  const owner = acs.owner_steps;
  const tip = `${String(acs.passing)} passing by command · ${String(owner)} owner step${owner === 1 ? "" : "s"}${
    ownerIds?.length ? ` (${ownerIds.join(", ")}, recorded passes:false)` : ""
  } · ${String(rest)} not passing yet`;
  const segment = (n: number, kind: string, background: string) =>
    n ? (
      <span
        data-segment={kind}
        data-hatched={kind === "owner" || undefined}
        style={{ flex: n, background }}
      />
    ) : null;
  return (
    <Tooltip label={tip}>
      <span className="ah-stack" style={{ gap: 3 }}>
        <span
          role="img"
          aria-label={tip}
          style={{
            display: "flex",
            width,
            height: 8,
            borderRadius: "var(--radius-full)",
            overflow: "hidden",
            background: "var(--surface-sunken)",
            gap: 1,
          }}
        >
          {segment(acs.passing, "passing", "var(--done)")}
          {segment(
            owner,
            "owner",
            "repeating-linear-gradient(135deg, var(--waiting) 0 3px, var(--waiting-soft) 3px 6px)",
          )}
          {segment(rest, "rest", "var(--gray-300)")}
        </span>
        <span className="ah-small">
          <b className="ah-num">
            {acs.passing + owner}/{acs.total}
          </b>
          {owner > 0 && (
            <span className="ah-subtle">
              {" "}
              · {owner} owner step{owner === 1 ? "" : "s"}
            </span>
          )}
        </span>
      </span>
    </Tooltip>
  );
}

/** A "Phase: All ▾" filter menu (spec 17); `value` null is All. */
export function FilterMenu({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | null;
  options: readonly { id: string; label: string }[];
  onChange: (id: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.id === value)?.label ?? "All";
  const choose = (id: string | null) => {
    onChange(id);
    setOpen(false);
  };
  return (
    <span style={{ position: "relative" }}>
      <button
        type="button"
        className="ah-scope"
        style={{ height: 28 }}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => {
          setOpen(!open);
        }}
      >
        {label}: {current}
        <Icon name="chevron-down" size="sm" />
      </button>
      <Popover open={open} label={`${label} filter`} style={{ top: 32, right: 0, minWidth: 180 }}>
        <MenuItem
          selected={value === null}
          onClick={() => {
            choose(null);
          }}
        >
          All
        </MenuItem>
        {options.map((o) => (
          <MenuItem
            key={o.id}
            selected={o.id === value}
            onClick={() => {
              choose(o.id);
            }}
          >
            {o.label}
          </MenuItem>
        ))}
      </Popover>
    </span>
  );
}
