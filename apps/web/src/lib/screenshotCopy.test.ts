import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  rememberMessageScreenshots,
  rememberScreenshot,
  screenshotFor,
  useMessageScreenshots,
  useScreenshot,
} from "./screenshotCopy";

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

describe("useMessageScreenshots", () => {
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
