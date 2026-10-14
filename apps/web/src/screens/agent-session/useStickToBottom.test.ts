import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useStickToBottom } from "./useStickToBottom";

/** A scroll container jsdom cannot lay out: its sizes are set by the test, its writes recorded. */
function aScroller(scrollHeight = 1000, clientHeight = 400) {
  const element = document.createElement("div");
  const size = { scrollHeight, clientHeight };
  const writes: number[] = [];
  let top = 0;
  const clamp = (value: number) =>
    Math.max(0, Math.min(value, size.scrollHeight - size.clientHeight));
  Object.defineProperty(element, "scrollHeight", { get: () => size.scrollHeight });
  Object.defineProperty(element, "clientHeight", { get: () => size.clientHeight });
  Object.defineProperty(element, "scrollTop", {
    get: () => top,
    set: (value: number) => {
      top = clamp(value);
      writes.push(top);
    },
  });
  document.body.append(element);
  return {
    element,
    size,
    writes,
    /** The reader scrolls to `value` (no programmatic write). */
    userScroll(value: number) {
      top = clamp(value);
      act(() => {
        element.dispatchEvent(new Event("scroll"));
      });
    },
  };
}

let frames: FrameRequestCallback[] = [];
let resized: ResizeObserverCallback[] = [];

function flushFrames() {
  const pending = frames;
  frames = [];
  act(() => {
    for (const callback of pending) callback(0);
  });
}

/** The content grew: every ResizeObserver hears it. */
function grow(scroller: ReturnType<typeof aScroller>, by: number) {
  scroller.size.scrollHeight += by;
  act(() => {
    for (const callback of resized) callback([], {} as ResizeObserver);
  });
}

beforeEach(() => {
  frames = [];
  resized = [];
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: ResizeObserverCallback) {
        resized.push(callback);
      }
      observe() {
        return undefined;
      }
      disconnect() {
        return undefined;
      }
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("useStickToBottom (stick to bottom)", () => {
  it("opens pinned at the bottom and follows the content while within 24 px of it", () => {
    const scroller = aScroller();
    const { result } = renderHook(() => useStickToBottom(scroller.element));
    flushFrames();
    expect(scroller.element.scrollTop).toBe(600);

    scroller.userScroll(580);
    expect(result.current.atBottom).toBe(true);
    grow(scroller, 200);
    flushFrames();

    expect(scroller.element.scrollTop).toBe(800);
    expect(result.current.atBottom).toBe(true);
  });

  it("detaches after the reader scrolls up, and new content no longer moves it", () => {
    const scroller = aScroller();
    const { result } = renderHook(() => useStickToBottom(scroller.element));
    flushFrames();

    scroller.userScroll(300);
    expect(result.current.atBottom).toBe(false);
    grow(scroller, 200);
    flushFrames();

    expect(scroller.element.scrollTop).toBe(300);
    expect(result.current.atBottom).toBe(false);
  });

  it("re-attaches and scrolls to the bottom when pin() is called", () => {
    const scroller = aScroller();
    const { result } = renderHook(() => useStickToBottom(scroller.element));
    flushFrames();
    scroller.userScroll(100);

    act(() => {
      result.current.pin();
    });
    flushFrames();

    expect(result.current.atBottom).toBe(true);
    expect(scroller.element.scrollTop).toBe(600);
    grow(scroller, 50);
    flushFrames();
    expect(scroller.element.scrollTop).toBe(650);
  });

  it("writes the scroll position at most once per frame", () => {
    const scroller = aScroller();
    renderHook(() => useStickToBottom(scroller.element));
    flushFrames();
    scroller.writes.length = 0;

    grow(scroller, 10);
    grow(scroller, 10);
    grow(scroller, 10);
    flushFrames();

    expect(scroller.writes).toEqual([630]);
  });
});
