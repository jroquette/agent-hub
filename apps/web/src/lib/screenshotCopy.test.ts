import { describe, expect, it, vi } from "vitest";

import { rememberScreenshot, screenshotFor } from "./screenshotCopy";

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
