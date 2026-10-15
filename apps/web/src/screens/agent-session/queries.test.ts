import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { aDeltaFrame, aLogRecord } from "../../testing/builders";
import { frameBatcher } from "./queries";
import type { StreamItem } from "./transcript";

const delta = (index: number): StreamItem => ({
  type: "delta",
  delta: aDeltaFrame({ after_seq: 0, block: 0, index, text: `d${String(index)}` }),
});
const record = (seq: number): StreamItem => ({
  type: "record",
  record: aLogRecord("text", { seq }),
});

/** Animation frames the test runs by hand; a cancelled frame never runs. */
let frames: Map<number, FrameRequestCallback>;
let cancel: ReturnType<typeof vi.fn>;

function runFrames() {
  const pending = [...frames.values()];
  frames.clear();
  for (const callback of pending) callback(0);
}

beforeEach(() => {
  frames = new Map();
  let next = 41;
  cancel = vi.fn((id: number) => frames.delete(id));
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    next += 1;
    frames.set(next, callback);
    return next;
  });
  vi.stubGlobal("cancelAnimationFrame", cancel);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("frameBatcher (queries)", () => {
  it("sends the deltas of one frame together", () => {
    const dispatch = vi.fn();
    const batcher = frameBatcher(dispatch);

    batcher.push(delta(0));
    batcher.push(delta(1));
    expect(dispatch).not.toHaveBeenCalled();
    runFrames();

    expect(dispatch).toHaveBeenCalledExactlyOnceWith([delta(0), delta(1)]);
  });

  it("drops the queued deltas and cancels their pending frame", () => {
    const dispatch = vi.fn();
    const batcher = frameBatcher(dispatch);

    batcher.push(delta(0));
    batcher.push(delta(1));
    batcher.drop();
    runFrames();

    expect(cancel).toHaveBeenCalledExactlyOnceWith(42);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("never sends an item twice across two flushes", () => {
    const dispatch = vi.fn();
    const batcher = frameBatcher(dispatch);

    batcher.push(delta(0));
    batcher.push(record(1));
    batcher.push(delta(2));
    runFrames();

    expect(dispatch.mock.calls).toEqual([[[delta(0), record(1)]], [[delta(2)]]]);
  });
});
