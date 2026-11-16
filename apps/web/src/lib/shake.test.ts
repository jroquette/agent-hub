import { describe, expect, it } from "vitest";

import { SHAKE, createShakeDetector } from "./shake";

interface Sample {
  x: number;
  t: number;
  pointerType: string;
  buttons: number;
}

const mouse = (x: number, t: number, buttons = 0): Sample => ({
  x,
  t,
  pointerType: "mouse",
  buttons,
});

/** A zigzag of `legs` legs of `amplitude` px, each leg sampled every `step` ms over `legMs`. */
function zigzag(legs: number, amplitude: number, legMs: number, start = 0, step = 10): Sample[] {
  const samples: Sample[] = [mouse(0, start)];
  for (let leg = 0; leg < legs; leg += 1) {
    const from = leg % 2 === 0 ? 0 : amplitude;
    const to = leg % 2 === 0 ? amplitude : 0;
    for (let ms = step; ms <= legMs; ms += step) {
      samples.push(mouse(from + ((to - from) * ms) / legMs, start + leg * legMs + ms));
    }
  }
  return samples;
}

function feed(samples: readonly Sample[], detector = createShakeDetector()): boolean[] {
  return samples.map((sample) => detector(sample));
}

describe("createShakeDetector", () => {
  it("detects 6 reversals of 80 px within 400 ms", () => {
    // 7 legs of 57 ms: 6 reversals in 400 ms.
    const hits = feed(zigzag(7, 80, 57));

    expect(hits.filter(Boolean)).toHaveLength(1);
  });

  it("detects a light shake: 3 reversals of 30 px within 300 ms", () => {
    expect(feed(zigzag(4, 30, 75)).filter(Boolean)).toHaveLength(1);
  });

  it("uses the proposed thresholds by default", () => {
    expect(SHAKE).toEqual({ reversals: 3, minLeg: 25, windowMs: 700, cooldownMs: 1500 });
  });

  it.each([
    ["a straight line", Array.from({ length: 60 }, (_, i) => mouse(i * 20, i * 10))],
    ["a slow zigzag", zigzag(8, 200, 400)],
    [
      "a circle",
      Array.from({ length: 200 }, (_, i) => mouse(100 * Math.cos((i * Math.PI) / 50), i * 10)),
    ],
    ["2 reversals", zigzag(3, 80, 50)],
    ["legs under 25 px", zigzag(12, 24, 30)],
    ["a button held", zigzag(8, 80, 50).map((s) => ({ ...s, buttons: 1 }))],
    ["a touch pointer", zigzag(8, 80, 50).map((s) => ({ ...s, pointerType: "touch" }))],
    ["a pen pointer", zigzag(8, 80, 50).map((s) => ({ ...s, pointerType: "pen" }))],
  ])("ordinary-movement: no shake for %s", (_name, samples) => {
    expect(feed(samples).some(Boolean)).toBe(false);
  });

  it("ordinary-movement: reversals spread over more than the window do not add up", () => {
    const detector = createShakeDetector();
    const early = zigzag(3, 80, 50); // 2 reversals
    const late = zigzag(2, 80, 50, 2000); // 1 more, long after

    expect(feed([...early, ...late], detector).some(Boolean)).toBe(false);
  });

  it("cooldown: a second shake inside the cooldown is ignored, one after it is detected", () => {
    const detector = createShakeDetector();
    const first = zigzag(6, 80, 50, 0);
    const during = zigzag(6, 80, 50, 400);
    const after = zigzag(6, 80, 50, 2500);

    expect(feed(first, detector).filter(Boolean)).toHaveLength(1);
    expect(feed(during, detector).some(Boolean)).toBe(false);
    expect(feed(after, detector).filter(Boolean)).toHaveLength(1);
  });

  it("cooldown: takes custom thresholds", () => {
    const detector = createShakeDetector({
      reversals: 2,
      minLeg: 10,
      windowMs: 600,
      cooldownMs: 0,
    });

    expect(feed(zigzag(3, 20, 50), detector).filter(Boolean)).toHaveLength(1);
  });
});
