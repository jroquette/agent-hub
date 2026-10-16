import { useEffect, useMemo, useState, useSyncExternalStore } from "react";

/**
 * The screenshot sent with a session's first message, kept so the chat view can show it again.
 *
 * The server never stores image bytes (its record carries a marker only), so the copy lives in this
 * browser: in memory for the session just started, and in IndexedDB so a reload or a later visit
 * still shows it. IndexedDB keeps the latest `KEEP` screenshots; older ones are dropped. Without
 * IndexedDB (private mode, tests) the memory copy alone remains and a reload shows the marker label.
 */
const DB_NAME = "agent-hub-screenshots";
const STORE = "screenshots";
export const KEEP = 60;

const copies = new Map<string, string>();

interface StoredScreenshot {
  id: string;
  dataUrl: string;
  /** The images of one later message (`<session>#<seq>`), in order; `dataUrl` is the first. */
  dataUrls?: string[];
  savedAt: number;
}

function openDb(): Promise<IDBDatabase> | null {
  if (typeof indexedDB === "undefined") return null;
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(STORE, { keyPath: "id" });
    };
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(request.error ?? new Error("IndexedDB open failed"));
    };
  });
}

function done(request: IDBRequest): Promise<unknown> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(request.error ?? new Error("IndexedDB request failed"));
    };
  });
}

async function persist(id: string, dataUrl: string, dataUrls?: string[]): Promise<void> {
  const opening = openDb();
  if (!opening) return;
  const db = await opening;
  try {
    const store = db.transaction(STORE, "readwrite").objectStore(STORE);
    const record: StoredScreenshot = { id, dataUrl, savedAt: Date.now() };
    if (dataUrls) record.dataUrls = dataUrls;
    await done(store.put(record));
    const all = (await done(store.getAll())) as StoredScreenshot[];
    const stale = all.sort((a, b) => b.savedAt - a.savedAt).slice(KEEP);
    for (const old of stale) store.delete(old.id);
  } finally {
    db.close();
  }
}

/** The stored copy of a session's screenshot, or `undefined` (none kept, or no IndexedDB). */
export async function loadScreenshot(agentSessionId: string): Promise<string | undefined> {
  const memory = copies.get(agentSessionId);
  if (memory) return memory;
  const opening = openDb();
  if (!opening) return undefined;
  try {
    const db = await opening;
    try {
      const store = db.transaction(STORE, "readonly").objectStore(STORE);
      const found = (await done(store.get(agentSessionId))) as StoredScreenshot | undefined;
      return found?.dataUrl;
    } finally {
      db.close();
    }
  } catch {
    return undefined;
  }
}

export function rememberScreenshot(agentSessionId: string, dataUrl: string): void {
  copies.clear();
  copies.set(agentSessionId, dataUrl);
  persist(agentSessionId, dataUrl).catch(() => {
    // Storage unavailable or full: the memory copy lasts for this page only.
  });
}

export function screenshotFor(agentSessionId: string): string | undefined {
  return copies.get(agentSessionId);
}

/** The session's screenshot: the memory copy at once, else the stored one when it loads. */
export function useScreenshot(agentSessionId: string): string | undefined {
  const [loaded, setLoaded] = useState<{ id: string; url: string | undefined }>();
  const memory = screenshotFor(agentSessionId);
  useEffect(() => {
    if (memory) return;
    let live = true;
    void loadScreenshot(agentSessionId).then((url) => {
      if (live) setLoaded({ id: agentSessionId, url });
    });
    return () => {
      live = false;
    };
  }, [agentSessionId, memory]);
  return memory ?? (loaded?.id === agentSessionId ? loaded.url : undefined);
}

/* ---------- Images pasted in a later message ---------- */

/** The images of messages sent from this page, by `<session>#<seq>`; listeners re-render. */
const messageCopies = new Map<string, readonly string[]>();
const listeners = new Set<() => void>();
let version = 0;

const messageKey = (agentSessionId: string, seq: number) => `${agentSessionId}#${String(seq)}`;

function changed() {
  version += 1;
  for (const listener of listeners) listener();
}

/** Keeps the images sent with message `seq` of a session, in memory and in IndexedDB. */
export function rememberMessageScreenshots(
  agentSessionId: string,
  seq: number,
  dataUrls: readonly string[],
): void {
  const first = dataUrls[0];
  if (first === undefined) return;
  const key = messageKey(agentSessionId, seq);
  messageCopies.set(key, dataUrls);
  changed();
  persist(key, first, [...dataUrls]).catch(() => {
    // Storage unavailable or full: the memory copy lasts for this page only.
  });
}

/** The stored images of a session's later messages, by seq (none without IndexedDB). */
export async function loadMessageScreenshots(
  agentSessionId: string,
): Promise<Record<number, readonly string[]>> {
  const opening = openDb();
  if (!opening) return {};
  try {
    const db = await opening;
    try {
      const store = db.transaction(STORE, "readonly").objectStore(STORE);
      const all = (await done(store.getAll())) as StoredScreenshot[];
      const prefix = `${agentSessionId}#`;
      return Object.fromEntries(
        all.flatMap((record) =>
          record.id.startsWith(prefix) && record.dataUrls
            ? [[Number(record.id.slice(prefix.length)), record.dataUrls]]
            : [],
        ),
      );
    } finally {
      db.close();
    }
  } catch {
    return {};
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * The images sent with each of a session's messages, by the message's seq: the ones this page
 * sent at once (an image shows on its message as soon as the POST answers), the stored ones when
 * they load. The first prompt's screenshot stays with `useScreenshot`.
 */
export function useMessageScreenshots(agentSessionId: string): Record<number, readonly string[]> {
  const memoryVersion = useSyncExternalStore(subscribe, () => version);
  const [stored, setStored] = useState<{ id: string; bySeq: Record<number, readonly string[]> }>();
  useEffect(() => {
    let live = true;
    void loadMessageScreenshots(agentSessionId).then((bySeq) => {
      if (live) setStored({ id: agentSessionId, bySeq });
    });
    return () => {
      live = false;
    };
  }, [agentSessionId]);
  return useMemo(() => {
    const bySeq: Record<number, readonly string[]> = {
      ...(stored?.id === agentSessionId ? stored.bySeq : {}),
    };
    const prefix = `${agentSessionId}#`;
    for (const [id, urls] of messageCopies)
      if (id.startsWith(prefix)) bySeq[Number(id.slice(prefix.length))] = urls;
    return bySeq;
    // The memory map is read again whenever its version moves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentSessionId, stored, memoryVersion]);
}
