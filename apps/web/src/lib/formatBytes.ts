const UNITS = ["B", "KiB", "MiB", "GiB", "TiB"] as const;

/** A byte count as a short label in binary units: `1536` → `1.5 KiB`. Not a size → `—`. */
export function formatBytes(bytes: number, decimals = 1): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  // Whole bytes never get decimals: "512 B", not "512.0 B".
  const shown = unit === 0 ? String(Math.round(value)) : value.toFixed(decimals);
  return `${shown} ${UNITS[unit]}`;
}
