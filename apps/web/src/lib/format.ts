/* Formatting rules of the design (brief §9): money, integers, tokens, durations, ages, clock times, paths. */

/** A number from a number or an API `Money` string ("2.1400"); null when there is none. */
export function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function fmtMoney(value: number | string | null | undefined, digits = 2): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return (
    "$" +
    n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })
  );
}

export function fmtInt(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-US");
}

export function fmtTokens(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)} M`;
  if (value >= 1e4) return `${String(Math.round(value / 1e3))} k`;
  return fmtInt(value);
}

/** "42 s", "3 min 12 s" (seconds shown under 10 min), "12 min", "1 h 30 min". */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${String(Math.round(seconds))} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return s && m < 10 ? `${String(m)} min ${String(s)} s` : `${String(m)} min`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return mm ? `${String(h)} h ${String(mm)} min` : `${String(h)} h`;
}

/** "3 s ago", "2 min ago", "2 h ago", "2 d ago" from an age in seconds. */
export function fmtAgo(seconds: number): string {
  if (seconds < 45) return `${String(Math.max(1, Math.round(seconds)))} s ago`;
  if (seconds < 3600) return `${String(Math.round(seconds / 60))} min ago`;
  if (seconds < 86400) return `${String(Math.round(seconds / 3600))} h ago`;
  return `${String(Math.round(seconds / 86400))} d ago`;
}

/** "just now" under a minute (a minute's clock cannot say more), else as `fmtAgo`. */
export function fmtRelative(seconds: number): string {
  return seconds < 60 ? "just now" : fmtAgo(seconds);
}

export type TimeZoneMode = "local" | "utc";

const DATE_TIME: Partial<Record<TimeZoneMode, Intl.DateTimeFormat>> = {};

/** "11 Oct 2026, 14:00:05 UTC": a date and time with its zone, local or UTC (formatter cached). */
export function fmtDateTime(value: Date | string, tz: TimeZoneMode): string {
  const format = (DATE_TIME[tz] ??= new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
    ...(tz === "utc" ? { timeZone: "UTC" } : {}),
  }));
  return format.format(typeof value === "string" ? new Date(value) : value);
}

/** "14:02" (or "14:02:11") in local time or UTC. */
export function fmtClock(value: Date | string, tz: TimeZoneMode, seconds = false): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
    hour12: false,
    ...(tz === "utc" ? { timeZone: "UTC" } : {}),
  });
}

/** Shortens a path in the middle, keeping its first folder and the longest tail that fits. */
export function middleTruncate(path: string, max = 48): string {
  if (path.length <= max) return path;
  const parts = path.split("/");
  if (parts.length > 2) {
    const head = parts[0] ?? "";
    let out = `${head}/…/${parts[parts.length - 1] ?? ""}`;
    for (let i = parts.length - 2; i > 0; i--) {
      const candidate = `${head}/…/${parts.slice(i).join("/")}`;
      if (candidate.length <= max) out = candidate;
      else break;
    }
    if (out.length <= max + 8) return out;
  }
  const keep = Math.floor((max - 1) / 2);
  return `${path.slice(0, keep)}…${path.slice(-keep)}`;
}
