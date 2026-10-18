/* The Sessions summary strip: one count per status group, each a quick filter, and the day's estimated cost. */
import { DerivedLabel, Icon, Money, Skeleton, type IconName } from "../../components";
import { fmtInt } from "../../lib/format";
import type { SectionId } from "./sections";

export interface SummaryTile {
  id: SectionId;
  label: string;
  /** Null while its group loads. */
  count: number | null;
  /** Its group could not load. */
  error: boolean;
  /** The period the Finished count covers ("last 7 days"), else null. */
  scope?: string | null | undefined;
}

export interface SessionsSummaryProps {
  tiles: SummaryTile[];
  /** The status filter on, or null for every group. */
  pressed: SectionId | null;
  /** The estimated cost of the last 24 h: null while it loads, `usd` null when none was recorded. */
  cost: { usd: string | null } | null;
  onPick: (id: SectionId | null) => void;
}

const LOOK: Record<SectionId, { icon: IconName | "pulse"; hint: string; zero: string }> = {
  waiting: { icon: "hand", hint: "Answer to let them continue", zero: "Nothing needs you" },
  live: { icon: "pulse", hint: "Claude is on it", zero: "No session is working" },
  idle: { icon: "moon", hint: "Check the work or reply", zero: "No session waits for a reply" },
  ended: { icon: "circle-check", hint: "", zero: "" },
};

const sessions = (n: number) => `${fmtInt(n)} ${n === 1 ? "session" : "sessions"}`;

export function SessionsSummary({ tiles, pressed, cost, onPick }: SessionsSummaryProps) {
  return (
    <div className="sl-summary" role="group" aria-label="Sessions summary">
      {tiles.map((tile) => {
        const look = LOOK[tile.id];
        const on = pressed === tile.id;
        const zero = tile.count === 0;
        const hint =
          tile.id === "ended" ? (tile.scope ?? "all time") : zero ? look.zero : look.hint;
        const name =
          tile.count === null
            ? tile.label
            : `${tile.label}, ${sessions(tile.count)}. ${on ? "Showing only these. Press to show all." : "Show only these."}`;
        return (
          <button
            key={tile.id}
            type="button"
            className="sl-summary-tile"
            data-tile={tile.id}
            data-zero={zero || undefined}
            aria-pressed={on}
            aria-label={name}
            onClick={() => {
              onPick(on ? null : tile.id);
            }}
          >
            <span className="ah-kpi-label">
              {look.icon === "pulse" ? (
                <span
                  className={zero ? "ah-dot" : "ah-dot ah-pulse"}
                  aria-hidden="true"
                  style={{ background: zero ? "var(--text-subtle)" : "var(--live)" }}
                />
              ) : (
                <Icon name={tile.id === "waiting" && zero ? "circle-check" : look.icon} size="sm" />
              )}
              {tile.label}
            </span>
            <span className="sl-summary-value">
              {tile.error ? (
                <span title="Could not load these sessions.">—</span>
              ) : tile.count === null ? (
                <Skeleton width={32} />
              ) : (
                fmtInt(tile.count)
              )}
            </span>
            <span className="sl-summary-hint">{hint}</span>
          </button>
        );
      })}
      <div className="sl-summary-tile sl-summary-cost" data-tile="cost">
        <span className="ah-kpi-label">
          <Icon name="coins" size="sm" />
          Est. cost
        </span>
        <span className="sl-summary-value">
          {cost === null ? (
            <Skeleton width={56} />
          ) : cost.usd === null ? (
            <span title="No cost recorded in the last 24 hours.">—</span>
          ) : (
            <Money value={cost.usd} />
          )}
        </span>
        <span className="sl-summary-hint">
          last 24 h ·{" "}
          <DerivedLabel how="Estimated from transcript usage and a dated price table.">
            estimated
          </DerivedLabel>
        </span>
      </div>
    </div>
  );
}
