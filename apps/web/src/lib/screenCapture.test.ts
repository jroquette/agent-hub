import { afterEach, describe, expect, it, vi } from "vitest";
import { toPng } from "html-to-image";

import { MAX_CAPTURE_BYTES, captureScreen, decodedBytes, onScreen } from "./screenCapture";

vi.mock("html-to-image", () => ({ toPng: vi.fn() }));

const png = vi.mocked(toPng);

/** A data URL whose base64 decodes to exactly `bytes` bytes. */
function dataUrlOf(bytes: number): string {
  return `data:image/png;base64,${btoa("x".repeat(bytes))}`;
}

afterEach(() => {
  png.mockReset();
  vi.useRealTimers();
});

describe("captureScreen", () => {
  it("caps the decoded PNG at the API image limit (spec amendment A1)", () => {
    expect(MAX_CAPTURE_BYTES).toBe(3_932_160);
  });

  it("measures the decoded size from the base64 length", () => {
    for (const bytes of [0, 1, 2, 3, 4, 5, 100]) {
      expect(decodedBytes(dataUrlOf(bytes))).toBe(bytes);
    }
  });

  it("resolves the PNG and its decoded size when the render succeeds", async () => {
    const url = dataUrlOf(10);
    png.mockResolvedValueOnce(url);

    await expect(captureScreen(document.body)).resolves.toEqual({
      ok: true,
      dataUrl: url,
      bytes: 10,
    });
    expect(png).toHaveBeenCalledTimes(1);
    expect(png).toHaveBeenCalledWith(document.body, expect.objectContaining({ cacheBust: false }));
  });

  it("resolves failed when the render rejects", async () => {
    png.mockRejectedValueOnce(new Error("tainted canvas"));

    await expect(captureScreen()).resolves.toEqual({ ok: false, reason: "failed" });
  });

  it("resolves timeout when the render outlasts the timeout", async () => {
    vi.useFakeTimers();
    png.mockReturnValueOnce(new Promise<string>(() => undefined));

    const result = captureScreen(document.body, { timeoutMs: 1500 });
    await vi.advanceTimersByTimeAsync(1500);

    await expect(result).resolves.toEqual({ ok: false, reason: "timeout" });
  });

  it("resolves too-large when the render stays over the cap at pixel ratio 1", async () => {
    png.mockResolvedValueOnce(dataUrlOf(101)).mockResolvedValueOnce(dataUrlOf(101));

    await expect(captureScreen(document.body, { maxBytes: 100 })).resolves.toEqual({
      ok: false,
      reason: "too-large",
    });
    expect(png).toHaveBeenCalledTimes(2);
    expect(png).toHaveBeenLastCalledWith(document.body, expect.objectContaining({ pixelRatio: 1 }));
  });

  it("keeps the smaller render when the retry fits the cap", async () => {
    const small = dataUrlOf(100);
    png.mockResolvedValueOnce(dataUrlOf(101)).mockResolvedValueOnce(small);

    await expect(captureScreen(document.body, { maxBytes: 100 })).resolves.toEqual({
      ok: true,
      dataUrl: small,
      bytes: 100,
    });
  });
});

describe("onScreen", () => {
  function at(box: Partial<DOMRect>): HTMLElement {
    const element = document.createElement("div");
    vi.spyOn(element, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      bottom: 0,
      right: 0,
      width: 0,
      height: 0,
      toJSON: () => ({}),
      ...box,
    });
    return element;
  }

  it("keeps an element in the viewport and drops one entirely above or below it", () => {
    const height = window.innerHeight;
    expect(onScreen(at({ top: 10, bottom: 60, left: 0, right: 100, width: 100, height: 50 }))).toBe(
      true,
    );
    expect(onScreen(at({ top: -500, bottom: -10, right: 100, width: 100, height: 490 }))).toBe(
      false,
    );
    expect(
      onScreen(at({ top: height + 10, bottom: height + 60, right: 100, width: 100, height: 50 })),
    ).toBe(false);
  });

  it("keeps text, zero-size wrappers and elements only partly on screen", () => {
    expect(onScreen(document.createTextNode("hello"))).toBe(true);
    expect(onScreen(at({}))).toBe(true);
    expect(onScreen(at({ top: -40, bottom: 20, right: 100, width: 100, height: 60 }))).toBe(true);
  });

  it("is the capture's filter", async () => {
    png.mockResolvedValue(dataUrlOf(100));
    await captureScreen();
    expect(png).toHaveBeenCalledWith(document.body, expect.objectContaining({ filter: onScreen }));
  });
});
