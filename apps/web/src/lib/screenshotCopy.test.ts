import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  KEEP,
  loadScreenshot,
  rememberMessageScreenshots,
  rememberScreenshot,
  screenshotFor,
  useMessageScreenshots,
  useScreenshot,
} from "./screenshotCopy";

/** An in-memory IndexedDB with the calls screenshotCopy makes; each request answers on a microtask. */
function fakeIndexedDb() {
  const rows = new Map<string, { id: string; savedAt: number }>();
  const request = <T>(result: () => T) => {
    const req: { result?: T; onsuccess?: () => void; onerror?: () => void } = {};
    queueMicrotask(() => {
      req.result = result();
      req.onsuccess?.();
    });
    return req;
  };
  const store = {
    put: (row: { id: string; savedAt: number }) => request(() => rows.set(row.id, row)),
    get: (id: string) => request(() => rows.get(id)),
    getAll: () => request(() => [...rows.values()]),
    delete: (id: string) => request(() => rows.delete(id)),
  };
  const db = {
    createObjectStore: () => store,
    transaction: () => ({ objectStore: () => store }),
    close: () => undefined,
  };
  const open = () => {
    const req: {
      result: typeof db;
      onupgradeneeded?: () => void;
      onsuccess?: () => void;
    } = { result: db };
    queueMicrotask(() => {
      req.onupgradeneeded?.();
      req.onsuccess?.();
    });
    return req;
  };
  return { rows, factory: { open } };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("screenshotCopy", () => {
  it("returns the remembered screenshot for its session", () => {
    rememberScreenshot("as-1", "data:image/png;base64,AAAA");

    expect(screenshotFor("as-1")).toBe("data:image/png;base64,AAAA");
    expect(screenshotFor("as-other")).toBeUndefined();
  });

  it("keeps only the latest screenshot when another one is remembered", () => {
    rememberScreenshot("as-1", "data:image/png;base64,AAAA");
    rememberScreenshot("as-2", "data:image/png;base64,BBBB");

    expect(screenshotFor("as-1")).toBeUndefined();
    expect(screenshotFor("as-2")).toBe("data:image/png;base64,BBBB");
  });

  it("writes nothing to browser storage when a screenshot is remembered", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    window.localStorage.clear();
    window.sessionStorage.clear();

    rememberScreenshot("as-3", "data:image/png;base64,CCCC");

    expect(setItem).not.toHaveBeenCalled();
    expect(window.localStorage).toHaveLength(0);
    expect(window.sessionStorage).toHaveLength(0);
    setItem.mockRestore();
  });
});

describe("useScreenshot", () => {
  it("returns the memory copy at once, and nothing for a session without a kept copy", async () => {
    rememberScreenshot("as-4", "data:image/png;base64,DDDD");

    expect(renderHook(() => useScreenshot("as-4")).result.current).toBe(
      "data:image/png;base64,DDDD",
    );
    const other = renderHook(() => useScreenshot("as-none"));
    await waitFor(() => {
      expect(other.result.current).toBeUndefined();
    });
  });
});

describe("screenshotCopy with IndexedDB (AC-266.2)", () => {
  it("finds a session's screenshot after a reload, from IndexedDB", async () => {
    const idb = fakeIndexedDb();
    vi.stubGlobal("indexedDB", idb.factory);
    rememberScreenshot("as-10", "data:image/png;base64,KEPT");
    await vi.waitFor(() => {
      expect(idb.rows.has("as-10")).toBe(true);
    });
    rememberScreenshot("as-11", "data:image/png;base64,NEXT"); // the memory copy moves on

    expect(screenshotFor("as-10")).toBeUndefined();
    await expect(loadScreenshot("as-10")).resolves.toBe("data:image/png;base64,KEPT");
    await expect(loadScreenshot("as-unknown")).resolves.toBeUndefined();
  });

  it("keeps only the latest KEEP screenshots", async () => {
    const idb = fakeIndexedDb();
    vi.stubGlobal("indexedDB", idb.factory);
    vi.useFakeTimers({ toFake: ["Date"] });
    for (let n = 0; n < KEEP + 2; n++) {
      vi.setSystemTime(1_000 + n);
      rememberScreenshot(`as-k${String(n)}`, "data:image/png;base64,AAAA");
      await vi.waitFor(() => {
        expect(idb.rows.has(`as-k${String(n)}`)).toBe(true);
      });
    }
    await vi.waitFor(() => {
      expect(idb.rows.size).toBe(KEEP);
    });

    expect(idb.rows.has("as-k0")).toBe(false);
    expect(idb.rows.has("as-k1")).toBe(false);
    expect(idb.rows.has(`as-k${String(KEEP + 1)}`)).toBe(true);
  });
});

describe("useMessageScreenshots (AC-266.8)", () => {
  it("shows a later message's images by its seq as soon as they are remembered", async () => {
    const { result } = renderHook(() => useMessageScreenshots("as-9"));
    expect(result.current).toEqual({});

    act(() => {
      rememberMessageScreenshots("as-9", 7, [
        "data:image/png;base64,AA",
        "data:image/png;base64,BB",
      ]);
      rememberMessageScreenshots("as-other", 7, ["data:image/png;base64,CC"]);
    });

    await waitFor(() => {
      expect(result.current).toEqual({
        7: ["data:image/png;base64,AA", "data:image/png;base64,BB"],
      });
    });
    // The first prompt's screenshot keeps its own copy.
    expect(screenshotFor("as-9")).toBeUndefined();
  });

  it("keeps nothing for a message without images", () => {
    rememberMessageScreenshots("as-10", 3, []);

    expect(renderHook(() => useMessageScreenshots("as-10")).result.current).toEqual({});
  });
});
