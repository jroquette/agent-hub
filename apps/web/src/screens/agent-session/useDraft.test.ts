import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DRAFT_MAX_BYTES, draftKey, useDraft } from "./useDraft";

const KEY = draftKey("s-1");
const stored = () => window.localStorage.getItem(KEY);

function typeDraft(text: string) {
  const view = renderHook(() => useDraft("s-1"));
  act(() => {
    view.result.current.setText(text);
  });
  return view;
}

describe("useDraft", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("saves the draft 500 ms after the last change, not before", () => {
    typeDraft("Fix the build");

    act(() => {
      vi.advanceTimersByTime(499);
    });
    expect(stored()).toBeNull();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(stored()).toBe(JSON.stringify("Fix the build"));
  });

  it("restores the saved draft on open", () => {
    window.localStorage.setItem(KEY, JSON.stringify("Half a thought"));

    const { result } = renderHook(() => useDraft("s-1"));

    expect(result.current.text).toBe("Half a thought");
  });

  it.each([
    ["a stored value that is not JSON", "{oops"],
    ["a stored value that is not a string", "42"],
  ])("opens empty on %s", (_, value) => {
    window.localStorage.setItem(KEY, value);

    expect(renderHook(() => useDraft("s-1")).result.current.text).toBe("");
  });

  it("saves a draft of exactly 64 KiB of UTF-8", () => {
    // "é" is two bytes: the draft is exactly the limit.
    typeDraft("é".repeat(DRAFT_MAX_BYTES / 2));

    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(stored()).not.toBeNull();
  });

  it("does not save a draft above 64 KiB and removes the stale saved one", () => {
    window.localStorage.setItem(KEY, JSON.stringify("older"));
    typeDraft(`${"é".repeat(DRAFT_MAX_BYTES / 2)}a`);

    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(stored()).toBeNull();
  });

  it("clears the draft at once when its send is accepted", () => {
    const { result } = typeDraft("Ship it");

    act(() => {
      result.current.accepted("Ship it");
    });
    expect(result.current.text).toBe("");
    expect(stored()).toBeNull();
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(stored()).toBeNull();
  });

  it("keeps what was typed after the send went out", () => {
    const { result } = typeDraft("Ship it");
    act(() => {
      result.current.setText("Ship it now");
    });

    act(() => {
      result.current.accepted("Ship it");
      vi.advanceTimersByTime(500);
    });
    expect(result.current.text).toBe("Ship it now");
    expect(stored()).toBe(JSON.stringify("Ship it now"));
  });

  it("saves a pending draft when the chat closes before 500 ms", () => {
    const { unmount } = typeDraft("Leaving");

    unmount();

    expect(stored()).toBe(JSON.stringify("Leaving"));
  });

  it("saves a pending draft when the page goes away before 500 ms (reload, tab close)", () => {
    typeDraft("Reloading");

    act(() => {
      window.dispatchEvent(new Event("pagehide"));
    });

    expect(stored()).toBe(JSON.stringify("Reloading"));
  });

  it("saves a pending draft when the page is hidden, not when it shows again", () => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    typeDraft("Switching tabs");

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(stored()).toBeNull();

    visibility.mockReturnValue("hidden");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(stored()).toBe(JSON.stringify("Switching tabs"));
  });

  it("swallows a quota error and a blocked storage (quota)", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    const { result } = typeDraft("Too much");

    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(result.current.text).toBe("Too much");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(renderHook(() => useDraft("s-2")).result.current.text).toBe("");
  });

  it("keeps nothing when there is no session id", () => {
    const { result } = renderHook(() => useDraft(null));
    act(() => {
      result.current.setText("Anywhere");
      vi.advanceTimersByTime(500);
    });

    expect(window.localStorage.length).toBe(0);
  });
});
