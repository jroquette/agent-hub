/* Charts the Phase 2 screens use (BarChart here; Sparkline and KpiStat in data.tsx; BudgetBar in status.tsx). */

/** A linear scale from [d0, d1] to [r0, r1]. */
export function scale(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  return (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);
}

/** The next "nice" axis maximum (1, 2, 5 × 10ⁿ) at or above `v`. */
export function niceMax(v: number): number {
  if (v <= 0) return 1;
  const power = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / power;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * power;
}

export interface Bar {
  label: string;
  value: number;
  /** A colour token name, e.g. "failed"; default "chart-1". */
  tone?: string | undefined;
  note?: string | undefined;
}
export interface BarChartProps {
  bars: Bar[];
  width?: number;
  fmt?: (v: number) => string | number;
  rowH?: number;
  labelW?: number;
  highlight?: string | undefined;
  /** The chart's accessible name: the question it answers. */
  label: string;
}

/** Horizontal bars from zero with direct labels. */
export function BarChart({
  bars,
  width = 520,
  fmt = (v) => v,
  rowH = 28,
  labelW = 150,
  highlight,
  label,
}: BarChartProps) {
  const max = niceMax(Math.max(0, ...bars.map((b) => b.value)));
  const height = bars.length * rowH + 8;
  const x = scale(0, max, labelW, width - 64);
  return (
    <svg
      className="ah-chart"
      width="100%"
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      role="img"
      aria-label={label}
    >
      {bars.map((bar, i) => (
        <g key={bar.label} transform={`translate(0 ${String(i * rowH + 4)})`}>
          <text className="ah-label" x={labelW - 8} y={rowH / 2 + 1} textAnchor="end">
            {bar.label}
          </text>
          <rect
            x={labelW}
            y={5}
            width={Math.max(1, x(bar.value) - labelW)}
            height={rowH - 10}
            rx="2"
            style={{
              fill: `var(--${bar.tone ?? (highlight === bar.label ? "failed" : "chart-1")})`,
            }}
          />
          <text
            x={x(bar.value) + 6}
            y={rowH / 2 + 4}
            style={{ fill: "var(--text)", fontWeight: 500 }}
          >
            {fmt(bar.value)}
            {bar.note ? `  ${bar.note}` : ""}
          </text>
        </g>
      ))}
      <line className="ah-axis" x1={labelW} x2={labelW} y1={0} y2={height} />
    </svg>
  );
}
