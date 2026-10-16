/* One status section of the Sessions grid: its tiles, sub-grouped `within`, then Load more (AC-234.5). */
import { memo, useCallback, useEffect, useRef, useState } from "react";

import { Button, SessionTile } from "../../components";
import { fmtInt } from "../../lib/format";
import type { Within } from "./filters";
import type { SectionRow } from "./sections";
import { groupWithin, tileOfRow, tileTimesOf } from "./tiles";

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

/**
 * One tile, rendered again only when its row changes: a running tile's times tick in their own
 * parts (`times`), an ended tile never reads the clock.
 */
const GridTile = memo(function GridTile({
  row,
  onOpen,
}: {
  row: SectionRow;
  onOpen: (row: SectionRow) => void;
}) {
  const [now] = useState(() => Date.now());
  return (
    <SessionTile
      s={tileOfRow(row, now)}
      times={tileTimesOf(row)}
      onOpen={() => {
        onOpen(row);
      }}
    />
  );
});

function Tiles({ rows, onOpen }: Pick<GridSectionProps, "rows" | "onOpen">) {
  return (
    <div className="sl-grid">
      {rows.map((row) => (
        <GridTile key={row.id} row={row} onOpen={onOpen} />
      ))}
    </div>
  );
}

export function GridSection({ title, rows, count, within, pages, onOpen }: GridSectionProps) {
  // A stable handler, so a screen render does not re-render every memoised tile.
  const latest = useRef(onOpen);
  useEffect(() => {
    latest.current = onOpen;
  });
  const open = useCallback((row: SectionRow) => {
    latest.current(row);
  }, []);
  return (
    <div className="ah-stack" style={{ gap: "var(--space-3)" }}>
      {within === null ? (
        <Tiles rows={rows} onOpen={open} />
      ) : (
        groupWithin(rows, within).map((group) => (
          <div key={group.key} role="group" aria-label={group.label} className="ah-stack">
            <h3 className="sl-group-head ah-caption ah-muted">
              {group.label} · {fmtInt(group.rows.length)}
            </h3>
            <Tiles rows={group.rows} onOpen={open} />
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
