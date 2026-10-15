/* One status section of the Sessions grid: its tiles, sub-grouped `within`, then Load more (AC-234.5). */
import { Button, SessionTile } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtInt } from "../../lib/format";
import type { Within } from "./filters";
import type { SectionRow } from "./sections";
import { groupWithin, tileOfRow } from "./tiles";

export interface GridSectionProps {
  title: string;
  /** The loaded rows: 50 per page, plus the section's driven sessions without a twin. */
  rows: SectionRow[];
  count: number;
  within: Within | null;
  pages: {
    hasNextPage: boolean;
    isPlaceholderData: boolean;
    isFetchingNextPage: boolean;
    fetchNextPage: () => unknown;
  };
  onOpen: (row: SectionRow) => void;
}

function Tiles({ rows, onOpen }: Pick<GridSectionProps, "rows" | "onOpen">) {
  const now = useNow(1000);
  return (
    <div className="sl-grid">
      {rows.map((row) => (
        <SessionTile
          key={row.id}
          s={tileOfRow(row, now)}
          onOpen={() => {
            onOpen(row);
          }}
        />
      ))}
    </div>
  );
}

export function GridSection({ title, rows, count, within, pages, onOpen }: GridSectionProps) {
  return (
    <div className="ah-stack" style={{ gap: "var(--space-3)" }}>
      {within === null ? (
        <Tiles rows={rows} onOpen={onOpen} />
      ) : (
        groupWithin(rows, within).map((group) => (
          <div key={group.key} role="group" aria-label={group.label} className="ah-stack">
            <h3 className="sl-group-head ah-caption ah-muted">
              {group.label} · {fmtInt(group.rows.length)}
            </h3>
            <Tiles rows={group.rows} onOpen={onOpen} />
          </div>
        ))
      )}
      <div className="ah-row ah-small ah-muted" style={{ gap: 12 }}>
        <span>
          {pages.hasNextPage
            ? `Showing ${fmtInt(rows.length)} of ~${fmtInt(count)} ${title.toLowerCase()} sessions`
            : `Showing all ${fmtInt(rows.length)}`}
        </span>
        {/* On placeholder pages TanStack would refetch page 1, not the next one. */}
        {pages.hasNextPage && !pages.isPlaceholderData && (
          <Button
            size="sm"
            disabled={pages.isFetchingNextPage}
            onClick={() => {
              void pages.fetchNextPage();
            }}
          >
            Load more
          </Button>
        )}
      </div>
    </div>
  );
}
