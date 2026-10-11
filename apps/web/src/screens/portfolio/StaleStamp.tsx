import { AsOfStamp } from "../../components";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useCollectorState } from "../../shell/GlobalStream";

/** The header's stale stamp while the collector is offline: data as of its last message (AC-200.43). */
export function StaleStamp() {
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();
  if (state !== "offline") return null;
  return <AsOfStamp stale time={fmtClock(asOf, tz)} />;
}
