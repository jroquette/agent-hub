import { useEffect, useState } from "react";

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
export const KEEP = 20;

const copies = new Map<string, string>();

interface StoredScreenshot {
  id: string;
  dataUrl: string;
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

async function persist(id: string, dataUrl: string): Promise<void> {
  const opening = openDb();
  if (!opening) return;
  const db = await opening;
  try {
    const store = db.transaction(STORE, "readwrite").objectStore(STORE);
    await done(store.put({ id, dataUrl, savedAt: Date.now() } satisfies StoredScreenshot));
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
