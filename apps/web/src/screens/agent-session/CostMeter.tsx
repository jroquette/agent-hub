import { Icon } from "../../components";
import { fmtMoney, fmtTokens } from "../../lib/format";
import type { MeterView } from "./model";

export interface CostMeterProps {
  meter: MeterView;
}

/** The session's cost and tokens, added up from the turns' results; always labelled an estimate (L7). */
export function CostMeter({ meter }: CostMeterProps) {
  const usage = meter.usage;
  return (
    <div className="as-meter ah-small" role="group" aria-label="Cost and tokens (estimate)">
      <Icon name="coins" size="sm" />
      <span className="ah-num">{fmtMoney(meter.costUsd, 4)}</span>
      <span className="ah-muted ah-num" title="Input tokens">
        {fmtTokens(usage?.input)} in
      </span>
      <span className="ah-muted ah-num" title="Output tokens">
        {fmtTokens(usage?.output)} out
      </span>
      {usage && usage.cache_read + usage.cache_write > 0 && (
        <span className="ah-muted ah-num" title="Cache read / cache write tokens">
          cache {fmtTokens(usage.cache_read)} / {fmtTokens(usage.cache_write)}
        </span>
      )}
      <span className="as-estimate">estimate</span>
    </div>
  );
}
