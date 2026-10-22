import { useId } from "react";

import { Money, Tooltip } from "../../components";
import { fmtInt, fmtMoney, fmtTokens } from "../../lib/format";
import type { MeterView } from "./model";

export interface CostMeterProps {
  meter: MeterView;
  /** Just the amount, for a tight row (the Discuss panel); the split stays in the tooltip. */
  compact?: boolean | undefined;
}

/** What the session's cost is made of: the precise amount, the tokens and the turns. */
export function costDetail(meter: MeterView): string[] {
  const usage = meter.usage;
  if (meter.costUsd === null && !usage) {
    return ["No turn has finished yet, so there is no cost to estimate."];
  }
  const lines = [`${fmtMoney(meter.costUsd, 4)} · Estimated from transcript`];
  if (usage) {
    const parts = [`${fmtTokens(usage.input)} in`, `${fmtTokens(usage.output)} out`];
    if (usage.cache_read + usage.cache_write > 0) {
      parts.push(
        `${fmtTokens(usage.cache_read)} cache read`,
        `${fmtTokens(usage.cache_write)} cache write`,
      );
    }
    lines.push(parts.join(" · "));
  }
  if (meter.turns > 0) lines.push(`${fmtInt(meter.turns)} turn${meter.turns === 1 ? "" : "s"}`);
  return lines;
}

/**
 * The session's running cost (the latest result's), labelled as the estimate it always is (L7):
 * "Cost $13.24 · estimated". The precise amount, the tokens and the turns are in its tooltip,
 * which keyboard users reach by focusing the field.
 */
export function CostMeter({ meter, compact = false }: CostMeterProps) {
  const detail = costDetail(meter);
  const tipId = useId();
  return (
    <Tooltip
      id={tipId}
      label={detail.map((line) => (
        <span key={line} style={{ display: "block" }}>
          {line}
        </span>
      ))}
    >
      <span
        className="as-meter ah-small"
        role="group"
        aria-label="Cost and tokens (estimate)"
        aria-describedby={tipId}
        // Focusable so keyboard users reach the split in its tooltip.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
      >
        {!compact && <span className="ah-subtle">Cost </span>}
        {meter.costUsd === null ? (
          <span className="ah-num">—</span>
        ) : (
          <Money value={meter.costUsd} />
        )}
        {!compact && <span className="ah-subtle"> · estimated</span>}
      </span>
    </Tooltip>
  );
}
