import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakeEventSource, stubEventSource } from "../testing/builders";
import { openStream, useEventStream } from "./sse";

const START = new Date("2026-10-11T14:00:00Z").getTime();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(START);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("openStream", () => {
  it("parses named messages and reports health when they arrive", () => {
    const find = stubEventSource();
    const counts = vi.fn();
    const health = vi.fn();
    openStream("/api/v1/events/stream", { counts }, health);
    const source = find("/api/v1/events/stream");

    source.open();
    vi.setSystemTime(START + 5_000);
    source.emit("counts", { approvals_open: 2 }, "id-1");

    expect(counts).toHaveBeenCalledWith({ approvals_open: 2 }, "id-1");
    expect(health).toHaveBeenLastCalledWith({
      open: true,
      lastMessageAt: START + 5_000,
      closedSince: null,
    });
  });

  it("counts heartbeats as messages when no handler asks for them", () => {
    const find = stubEventSource();
    const health = vi.fn();
    openStream("/s", {}, health);

    vi.setSystemTime(START + 15_000);
    find("/s").emit("heartbeat", { at: "x" });

    expect(health).toHaveBeenLastCalledWith(
      expect.objectContaining({ lastMessageAt: START + 15_000 }),
    );
  });

  it("ignores a message whose body is not JSON", () => {
    const find = stubEventSource();
    const handler = vi.fn();
    openStream("/s", { tick: handler }, vi.fn());
    const source = find("/s");

    source.addEventListener("tick", () => undefined);
    const bad = new MessageEvent<string>("tick", { data: "{not json" });
    (
      source as unknown as { listeners: Map<string, Set<(e: MessageEvent<string>) => void>> }
    ).listeners
      .get("tick")
      ?.forEach((listener) => {
        listener(bad);
      });

    expect(handler).not.toHaveBeenCalled();
  });

  it("marks the stream closed when it errors, and reopens a final close after 3 s", () => {
    const find = stubEventSource();
    const health = vi.fn();
    openStream("/s", {}, health);

    vi.setSystemTime(START + 1_000);
    find("/s").fail(true);
    expect(health).toHaveBeenLastCalledWith({
      open: false,
      lastMessageAt: START,
      closedSince: START + 1_000,
    });

    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    expect(FakeEventSource.instances).toHaveLength(2);
  });

  it("stops and never reconnects when closed by the caller", () => {
    const find = stubEventSource();
    const close = openStream("/s", {}, vi.fn());
    find("/s").fail(true);

    close();
    vi.advanceTimersByTime(60_000);

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(find("/s").readyState).toBe(FakeEventSource.CLOSED);
  });

  it("reports a closed stream when the browser has no EventSource", () => {
    vi.stubGlobal("EventSource", undefined);
    const health = vi.fn();

    openStream("/s", {}, health);

    expect(health).toHaveBeenCalledWith({ open: false, lastMessageAt: START, closedSince: START });
    vi.unstubAllGlobals();
  });
});

describe("useEventStream", () => {
  it("returns the stream health and closes the stream on unmount", () => {
    const find = stubEventSource();
    const { result, unmount } = renderHook(() => useEventStream("/s", {}));

    act(() => {
      find("/s").open();
    });
    expect(result.current.open).toBe(true);

    unmount();
    expect(find("/s").readyState).toBe(FakeEventSource.CLOSED);
  });

  it("calls the latest handler when a message arrives after a re-render", () => {
    const find = stubEventSource();
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = renderHook(({ handler }) => useEventStream("/s", { counts: handler }), {
      initialProps: { handler: first },
    });

    rerender({ handler: second });
    act(() => {
      find("/s").emit("counts", { n: 1 });
    });

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledWith({ n: 1 }, "");
  });

  it("opens nothing when the url is null", () => {
    stubEventSource();
    renderHook(() => useEventStream(null, {}));

    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
