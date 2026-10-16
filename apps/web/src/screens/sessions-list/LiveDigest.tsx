/* Sessions' polite live digest, kept from the retired Live sessions (ADR 0033 D8, AC-234.10, spec 14). */
import { useEffect, useRef, useState } from "react";

import { sessionIdentity } from "../../components";
import { isDriven, type SectionId, type SectionRow } from "./sections";

/** At most one announcement per DIGEST_MS; a change inside it waits for its end. */
export const DIGEST_MS = 15_000;

export interface DigestSection {
  id: SectionId;
  rows: readonly SectionRow[];
}

interface Known {
  waiting: Set<string>;
  running: Set<string>;
  ended: Set<string>;
}

function knownOf(sections: readonly DigestSection[]): Known {
  const ids = (pick: (id: SectionId) => boolean) =>
    new Set(sections.filter(({ id }) => pick(id)).flatMap(({ rows }) => rows.map((row) => row.id)));
  return {
    waiting: ids((id) => id === "waiting"),
    running: ids((id) => id !== "ended"),
    ended: ids((id) => id === "ended"),
  };
}

const titleOf = (row: SectionRow) =>
  isDriven(row) ? (row.title ?? "Untitled session") : sessionIdentity(row).title;
const outcomeOf = (row: SectionRow) =>
  isDriven(row) ? (row.status === "failed" ? "failed" : "ended") : (row.outcome ?? "ended");

/** A session new in Waiting, and one seen running that is now in Ended; rows that only loaded say nothing. */
function newsOf(before: Known, sections: readonly DigestSection[]): string[] {
  return sections.flatMap(({ id, rows }) => {
    if (id === "waiting") {
      return rows
        .filter((row) => !before.waiting.has(row.id))
        .map((row) => `1 session waiting for approval: ${titleOf(row)}.`);
    }
    if (id === "ended") {
      return rows
        .filter((row) => before.running.has(row.id) && !before.ended.has(row.id))
        .map((row) => `Session ended: ${titleOf(row)}, ${outcomeOf(row)}.`);
    }
    return [];
  });
}

/**
 * Announces new waiting and ended sessions, never routine changes. While `settled` is false (a
 * section loading, showing a placeholder or loading more) the next settled rows become the baseline.
 */
export function LiveDigest({
  sections,
  settled,
}: {
  sections: readonly DigestSection[];
  settled: boolean;
}) {
  const [message, setMessage] = useState("");
  const [tick, wake] = useState(0);
  const known = useRef<Known | null>(null);
  const last = useRef(Number.NEGATIVE_INFINITY);
  useEffect(() => {
    if (!settled) {
      known.current = null;
      return undefined;
    }
    const before = known.current;
    const now = knownOf(sections);
    const news = before ? newsOf(before, sections) : [];
    if (news.length === 0) {
      known.current = now;
      return undefined;
    }
    // Inside the window the baseline stays, so the change is said at its end unless undone.
    const wait = last.current + DIGEST_MS - Date.now();
    if (wait > 0) {
      const timer = setTimeout(() => {
        wake((n) => n + 1);
      }, wait);
      return () => {
        clearTimeout(timer);
      };
    }
    known.current = now;
    last.current = Date.now();
    setMessage(news.join(" "));
    return undefined;
  }, [sections, settled, tick]);
  return (
    <div className="ah-sr" aria-live="polite" aria-atomic="true" data-testid="live-digest">
      {message}
    </div>
  );
}
