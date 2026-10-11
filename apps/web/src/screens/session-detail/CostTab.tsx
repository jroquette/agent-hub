import {
  BarChart,
  DataTable,
  DerivedLabel,
  EmptyState,
  KpiStat,
  ProblemError,
  Skeleton,
} from "../../components";
import { fmtInt, fmtMoney, toNumber } from "../../lib/format";
import { useSessionCost } from "./queries";

/** The label every cost carries in Phase 2 (D15, AC-200.48). */
export const ESTIMATED = "Estimated from transcript";
const HIGH_FACTOR = 3;

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? (sorted[mid] ?? 0) : ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2;
}

/** Tokens and estimated cost per turn, and the share of the run (spec 10, "Cost tab"). */
export function CostTab({ sessionId }: { sessionId: string }) {
  const cost = useSessionCost(sessionId, true);
  if (cost.isPending) return <Skeleton lines={5} height={16} />;
  if (cost.error) {
    return (
      <ProblemError
        title="Could not load the cost"
        detail={cost.error.detail}
        status={cost.error.status}
        onRetry={() => {
          void cost.refetch();
        }}
      />
    );
  }
  const data = cost.data;
  const label = (
    <DerivedLabel
      how={`Tokens from the transcript times the price table${data.prices_as_of ? ` of ${data.prices_as_of}` : ""}.`}
    >
      {ESTIMATED}
    </DerivedLabel>
  );
  if (data.series.length === 0) {
    return (
      <div className="ah-stack">
        {label}
        <EmptyState icon="coins" title="No token or cost data">
          Cost is estimated from transcripts. OpenTelemetry is not connected in this version.
        </EmptyState>
      </div>
    );
  }
  const totals = data.series.reduce(
    (sum, turn) => ({
      input: sum.input + turn.input,
      output: sum.output + turn.output,
      cacheRead: sum.cacheRead + turn.cache_read,
      cacheWrite: sum.cacheWrite + turn.cache_write,
    }),
    { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  );
  const costs = data.series.map((turn) => toNumber(turn.cost_usd) ?? 0);
  const typical = median(costs);
  const total = toNumber(data.total_usd);
  const run = toNumber(data.run_total_usd);
  const share = total !== null && run ? Math.round((total / run) * 100) : null;
  return (
    <div className="ah-stack" style={{ gap: 16 }}>
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        {label}
        {data.model && <span className="ah-small ah-subtle">Model {data.model}</span>}
        {data.prices_as_of && (
          <span className="ah-small ah-subtle">· prices as of {data.prices_as_of}</span>
        )}
      </div>
      {data.unknown_reason && (
        <div className="ah-small" style={{ color: "var(--waiting)" }}>
          {data.unknown_reason}
        </div>
      )}
      <div className="sd-kpis">
        <KpiStat label="Total" value={fmtMoney(data.total_usd, 4)} period={ESTIMATED} small />
        <KpiStat label="Input" value={fmtInt(totals.input)} period="tokens" small />
        <KpiStat label="Output" value={fmtInt(totals.output)} period="tokens" small />
        <KpiStat label="Cache read" value={fmtInt(totals.cacheRead)} period="tokens" small />
        <KpiStat label="Cache write" value={fmtInt(totals.cacheWrite)} period="tokens" small />
        {run !== null && (
          <KpiStat
            label="Run total"
            value={fmtMoney(run, 4)}
            period={share === null ? "run" : `this session is ${String(share)} % of the run`}
            small
          />
        )}
      </div>
      <div className="sd-cost">
        <div className="ah-chart-card">
          <h3 className="ah-chart-q">Which turns cost the most?</h3>
          <div className="ah-chart-meta">
            <span>Estimated USD per turn</span>
            <span className="ah-mono">total {fmtMoney(data.total_usd, 4)}</span>
          </div>
          <BarChart
            label="Estimated cost per turn"
            bars={data.series.slice(-24).map((turn) => ({
              label: `T${String(turn.turn)}`,
              value: toNumber(turn.cost_usd) ?? 0,
            }))}
            fmt={(v) => fmtMoney(v, 4)}
            rowH={22}
            labelW={60}
          />
        </div>
        <DataTable
          caption="Cost per turn"
          density="compact"
          rowKey={(turn) => String(turn.turn)}
          rows={data.series}
          maxHeight={420}
          columns={[
            { id: "turn", label: "Turn", render: (turn) => `T${String(turn.turn)}` },
            { id: "input", label: "Input", align: "right", render: (turn) => fmtInt(turn.input) },
            {
              id: "output",
              label: "Output",
              align: "right",
              render: (turn) => fmtInt(turn.output),
            },
            {
              id: "cache",
              label: "Cache",
              align: "right",
              render: (turn) => fmtInt(turn.cache_read + turn.cache_write),
            },
            {
              id: "cost",
              label: "Cost",
              align: "right",
              render: (turn) => {
                const value = toNumber(turn.cost_usd) ?? 0;
                return (
                  <span className="ah-row" style={{ gap: 6, justifyContent: "flex-end" }}>
                    {typical > 0 && value > typical * HIGH_FACTOR && (
                      <span className="ah-chip ah-small">high</span>
                    )}
                    {fmtMoney(turn.cost_usd, 4)}
                  </span>
                );
              },
            },
          ]}
        />
      </div>
    </div>
  );
}
