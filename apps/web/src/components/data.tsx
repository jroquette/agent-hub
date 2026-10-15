import { observeElementRect, useVirtualizer } from "@tanstack/react-virtual";
import { useRef, useState } from "react";
import type { ReactNode } from "react";

import { Button, MenuItem, Popover, Tooltip } from "./core";
import { Skeleton } from "./feedback";
import { Icon, type IconName } from "./Icon";
import type { Phase } from "./core";

/* ---------- Data table: virtualised past VIRTUAL_THRESHOLD rows; sticky header; right-aligned numbers ---------- */

/** Tables with more rows than this render only the rows in view (TanStack Virtual). */
export const VIRTUAL_THRESHOLD = 100;
const ROW_HEIGHT = { comfortable: 40, compact: 32 } as const;

export interface DataTableColumn<Row> {
  id: string;
  label: ReactNode;
  width?: number | string | undefined;
  align?: "right" | undefined;
  sortable?: boolean | undefined;
  hint?: string | undefined;
  render?: ((row: Row) => ReactNode) | undefined;
}

export interface DataTableProps<Row> {
  columns: DataTableColumn<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  sort?: { id: string; dir: "asc" | "desc" } | undefined;
  onSort?: ((columnId: string) => void) | undefined;
  selectable?: boolean | undefined;
  selected?: string[] | undefined;
  onSelect?: ((key: string) => void) | undefined;
  onSelectAll?: ((checked: boolean) => void) | undefined;
  onRowClick?: ((row: Row) => void) | undefined;
  loading?: boolean | undefined;
  empty?: ReactNode;
  footer?: ReactNode;
  maxHeight?: number | undefined;
  density?: "compact" | undefined;
  caption?: string | undefined;
}

function cellValue<Row>(row: Row, column: DataTableColumn<Row>): ReactNode {
  if (column.render) return column.render(row);
  const value: unknown = (row as Record<string, unknown>)[column.id];
  return typeof value === "string" || typeof value === "number" ? value : null;
}

export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  sort,
  onSort,
  selectable,
  selected = [],
  onSelect,
  onSelectAll,
  onRowClick,
  loading,
  empty,
  footer,
  maxHeight,
  density,
  caption,
}: DataTableProps<Row>) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const chosen = new Set(selected);
  const virtual = !loading && rows.length > VIRTUAL_THRESHOLD;
  const rowHeight = ROW_HEIGHT[density ?? "comfortable"];
  const fallbackRect = { width: 1024, height: maxHeight ?? 640 };
  // The virtualizer is read during render only; nothing memoizes its functions.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
    enabled: virtual,
    initialRect: fallbackRect,
    // An element not laid out yet (or jsdom) measures 0: keep the fallback window then.
    observeElementRect: (instance, report) =>
      observeElementRect(instance, (rect) => {
        report(rect.height > 0 ? rect : fallbackRect);
      }),
  });
  const span = columns.length + (selectable ? 1 : 0);
  const items = virtual ? virtualizer.getVirtualItems() : [];
  const shown: { row: Row; index: number }[] = virtual
    ? items.flatMap((item) => {
        const row = rows[item.index];
        return row === undefined ? [] : [{ row, index: item.index }];
      })
    : rows.map((row, index) => ({ row, index }));
  const padTop = virtual ? (items[0]?.start ?? 0) : 0;
  const padBottom = virtual ? virtualizer.getTotalSize() - (items[items.length - 1]?.end ?? 0) : 0;

  return (
    <div className="ah-table-wrap" data-density={density}>
      <div
        ref={scrollRef}
        style={{ maxHeight, overflow: "auto" }}
        // A bounded scroll region is focusable so keyboard users can scroll it.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={maxHeight ? 0 : undefined}
      >
        <table className="ah-table" aria-rowcount={virtual ? rows.length + 1 : undefined}>
          {caption && <caption className="ah-sr">{caption}</caption>}
          <thead>
            <tr aria-rowindex={virtual ? 1 : undefined}>
              {selectable && (
                <th style={{ width: 36 }}>
                  <input
                    type="checkbox"
                    className="ah-check"
                    aria-label="Select all"
                    checked={rows.length > 0 && chosen.size === rows.length}
                    onChange={(e) => onSelectAll?.(e.target.checked)}
                  />
                </th>
              )}
              {columns.map((column) => {
                const dir = sort?.id === column.id ? sort.dir : null;
                const label = (
                  <span
                    className="ah-row"
                    style={{
                      gap: 4,
                      justifyContent: column.align === "right" ? "flex-end" : undefined,
                    }}
                  >
                    {column.label}
                    {dir && <Icon name={dir === "asc" ? "arrow-up" : "arrow-down"} size="sm" />}
                    {column.hint && (
                      <Tooltip label={column.hint}>
                        <Icon name="info" size="sm" />
                      </Tooltip>
                    )}
                  </span>
                );
                return (
                  <th
                    key={column.id}
                    scope="col"
                    style={{
                      width: column.width,
                      textAlign: column.align === "right" ? "right" : undefined,
                    }}
                    data-sort={column.sortable ? "" : undefined}
                    aria-sort={dir ? (dir === "asc" ? "ascending" : "descending") : undefined}
                  >
                    {column.sortable && onSort ? (
                      <button
                        type="button"
                        className="ah-th-sort"
                        onClick={() => {
                          onSort(column.id);
                        }}
                      >
                        {label}
                      </button>
                    ) : (
                      label
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading &&
              Array.from({ length: 6 }, (_, i) => (
                <tr key={`skeleton-${String(i)}`}>
                  {selectable && <td />}
                  {columns.map((column) => (
                    <td key={column.id} style={{ textAlign: column.align }}>
                      <Skeleton width={column.align === "right" ? 48 : "70%"} />
                    </td>
                  ))}
                </tr>
              ))}
            {padTop > 0 && (
              <tr aria-hidden="true" style={{ height: padTop }}>
                <td colSpan={span} style={{ padding: 0, border: 0 }} />
              </tr>
            )}
            {!loading &&
              shown.map(({ row, index }) => {
                const key = rowKey(row);
                return (
                  <tr
                    key={key}
                    data-index={index}
                    data-key={key}
                    aria-rowindex={virtual ? index + 2 : undefined}
                    aria-selected={chosen.has(key) || undefined}
                    onClick={() => onRowClick?.(row)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && e.target === e.currentTarget) onRowClick?.(row);
                    }}
                    tabIndex={0}
                  >
                    {selectable && (
                      <td
                        onClick={(e) => {
                          e.stopPropagation();
                        }}
                      >
                        <input
                          type="checkbox"
                          className="ah-check"
                          checked={chosen.has(key)}
                          onChange={() => onSelect?.(key)}
                          aria-label="Select row"
                        />
                      </td>
                    )}
                    {columns.map((column) => (
                      <td key={column.id} className={column.align === "right" ? "ah-r" : undefined}>
                        {cellValue(row, column)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            {padBottom > 0 && (
              <tr aria-hidden="true" style={{ height: padBottom }}>
                <td colSpan={span} style={{ padding: 0, border: 0 }} />
              </tr>
            )}
          </tbody>
        </table>
        {!loading && rows.length === 0 && empty}
      </div>
      {footer && <div className="ah-table-foot">{footer}</div>}
    </div>
  );
}

/* ---------- Filters ---------- */
export interface FilterChipProps {
  k?: string | undefined;
  value?: string | undefined;
  active?: boolean;
  onRemove?: (() => void) | undefined;
  onClick?: (() => void) | undefined;
  /** Renders the "add filter" chip with this label instead. */
  add?: string | undefined;
}
export function FilterChip({ k, value, active = true, onRemove, onClick, add }: FilterChipProps) {
  if (add) {
    return (
      <button type="button" className="ah-chip ah-chip-add" onClick={onClick}>
        <Icon name="plus" />
        {add}
      </button>
    );
  }
  return (
    <span className="ah-chip" data-pressed={active}>
      <button type="button" className="ah-chip-part" aria-pressed={active} onClick={onClick}>
        {k && <span className="ah-chip-k">{k}</span>}
        <span>{value}</span>
      </button>
      {onRemove && (
        <button
          type="button"
          className="ah-chip-part"
          aria-label={`Remove filter ${k ?? ""} ${value ?? ""}`.replace(/\s+/g, " ").trim()}
          onClick={onRemove}
        >
          <Icon name="x" />
        </button>
      )}
    </span>
  );
}

export interface FacetOption {
  id: string;
  label: string;
  count?: number | undefined;
  checked?: boolean | undefined;
  icon?: ReactNode;
  mono?: boolean | undefined;
}
export interface Facet {
  id: string;
  title: string;
  phase?: Phase | undefined;
  input?: ReactNode;
  options?: FacetOption[] | undefined;
}
export interface FilterRailProps {
  facets: Facet[];
  onToggle?: ((facetId: string, optionId: string) => void) | undefined;
  footer?: ReactNode;
}
export function FilterRail({ facets, onToggle, footer }: FilterRailProps) {
  return (
    <aside className="ah-rail" aria-label="Filters">
      {facets.map((facet) => (
        <fieldset key={facet.id} style={{ border: 0, margin: 0, padding: 0 }}>
          <legend className="ah-facet-title" style={{ width: "100%" }}>
            <span>{facet.title}</span>
            {facet.phase && <span className="ah-phase">{facet.phase}</span>}
          </legend>
          {facet.input}
          {(facet.options ?? []).map((option) => (
            <label key={option.id} className="ah-facet-opt">
              <input
                type="checkbox"
                className="ah-check"
                checked={Boolean(option.checked)}
                onChange={() => onToggle?.(facet.id, option.id)}
              />
              {option.icon}
              <span
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                className={option.mono ? "ah-mono" : undefined}
              >
                {option.label}
              </span>
              <span className="ah-count">{option.count}</span>
            </label>
          ))}
        </fieldset>
      ))}
      {footer}
    </aside>
  );
}

export interface SavedView {
  name: string;
  count?: number | undefined;
  shared?: boolean | undefined;
}
export interface SavedViewMenuProps {
  views?: SavedView[];
  current?: string | undefined;
  open?: boolean | undefined;
  onPick?: ((name: string) => void) | undefined;
  onSave?: (() => void) | undefined;
}
export function SavedViewMenu({
  views = [],
  current,
  open: openProp,
  onPick,
  onSave,
}: SavedViewMenuProps) {
  const [open, setOpen] = useState(Boolean(openProp));
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <Button
        size="sm"
        icon="bookmark"
        iconRight="chevron-down"
        onClick={() => {
          setOpen(!open);
        }}
        aria-expanded={open}
      >
        {current ?? "Saved views"}
      </Button>
      <Popover open={open} style={{ top: 30, left: 0 }} label="Saved views">
        {views.map((view) => (
          <MenuItem
            key={view.name}
            icon={view.shared ? "link" : "bookmark"}
            selected={view.name === current}
            hint={<span className="ah-subtle ah-small ah-mono">{view.count}</span>}
            onClick={() => {
              setOpen(false);
              onPick?.(view.name);
            }}
          >
            {view.name}
          </MenuItem>
        ))}
        <div className="ah-menu-sep" />
        <MenuItem icon="plus" onClick={onSave}>
          Save current filters as a view
        </MenuItem>
      </Popover>
    </div>
  );
}

/* ---------- Sparkline: line (with optional previous period) or bars ---------- */
export interface SparklineProps {
  data: number[];
  prev?: number[] | undefined;
  width?: number;
  height?: number;
  bars?: boolean | undefined;
  area?: boolean | undefined;
  label: string;
}
export function Sparkline({
  data,
  prev,
  width = 96,
  height = 24,
  bars,
  area,
  label,
}: SparklineProps) {
  const all = data.concat(prev ?? []);
  const max = Math.max(1e-9, ...all);
  const min = bars ? 0 : Math.min(0, ...all);
  const x = (i: number, n: number) => (n <= 1 ? 0 : (i / (n - 1)) * width);
  const y = (v: number) => height - 1 - ((v - min) / (max - min || 1)) * (height - 2);
  const path = (values: number[]) =>
    values
      .map((v, i) => `${i ? "L" : "M"}${x(i, values.length).toFixed(1)},${y(v).toFixed(1)}`)
      .join("");
  if (bars) {
    const barWidth = width / Math.max(1, data.length);
    return (
      <svg className="ah-spark" width={width} height={height} role="img" aria-label={label}>
        {data.map((v, i) => (
          <rect
            key={i}
            className={v === 0 ? "ah-spark-zero" : undefined}
            x={i * barWidth + 0.5}
            width={Math.max(1, barWidth - 1.5)}
            y={v === 0 ? height - 1 : y(v)}
            height={v === 0 ? 1 : height - y(v)}
            rx="0.5"
          />
        ))}
      </svg>
    );
  }
  const last = data[data.length - 1];
  return (
    <svg className="ah-spark" width={width} height={height} role="img" aria-label={label}>
      {area && (
        <path
          className="ah-spark-area"
          d={`${path(data)}L${String(width)},${String(height)}L0,${String(height)}Z`}
        />
      )}
      {prev && <path className="ah-spark-prev" d={path(prev)} />}
      <path d={path(data)} />
      {last !== undefined && (
        <circle
          cx={x(data.length - 1, data.length)}
          cy={y(last)}
          r="2"
          style={{ fill: "var(--chart-1)" }}
        />
      )}
    </svg>
  );
}

/* ---------- KPI stat with delta: tone says whether the change is good or bad for the process ---------- */
export interface KpiStatProps {
  label: string;
  value: ReactNode;
  unit?: string | undefined;
  delta?: string | undefined;
  deltaTone?: "good" | "bad" | "neutral";
  period?: string | undefined;
  spark?: number[] | undefined;
  prev?: number[] | undefined;
  hint?: string | undefined;
  small?: boolean | undefined;
}
export function KpiStat({
  label,
  value,
  unit,
  delta,
  deltaTone = "neutral",
  period = "vs last 7 d",
  spark,
  prev,
  hint,
  small,
}: KpiStatProps) {
  const down = delta !== undefined && (delta.startsWith("−") || delta.startsWith("-"));
  const trend: IconName = down ? "trending-down" : "trending-up";
  return (
    <div className="ah-kpi">
      <div className="ah-kpi-label">
        {label}
        {hint && (
          <Tooltip label={hint}>
            <Icon name="info" size="sm" />
          </Tooltip>
        )}
      </div>
      <div className="ah-row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div
          className="ah-kpi-value"
          style={small ? { fontSize: 20, lineHeight: "28px" } : undefined}
        >
          {value}
          {unit && (
            <span className="ah-subtle" style={{ fontSize: 13, marginLeft: 4 }}>
              {unit}
            </span>
          )}
        </div>
        {spark && <Sparkline data={spark} prev={prev} label={`${label} trend`} />}
      </div>
      {(delta ?? period) && (
        <div className="ah-kpi-foot">
          {delta && (
            <span className="ah-delta" data-tone={deltaTone}>
              <Icon name={trend} size="sm" />
              {delta}
            </span>
          )}
          <span>{period}</span>
        </div>
      )}
    </div>
  );
}
