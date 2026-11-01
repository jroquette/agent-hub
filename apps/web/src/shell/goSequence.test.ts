import { afterEach, describe, expect, it } from "vitest";

import { GO, armGoSequence, clearGoSequence, goSequenceTakes } from "./goSequence";

describe("goSequenceTakes", () => {
  afterEach(() => {
    clearGoSequence();
  });

  it("takes the second key of every g sequence while one waits, and no other key", () => {
    armGoSequence(10_000);

    for (const key of [...Object.keys(GO), "w", "m", "b", "t", "o", "u", "g"]) {
      expect(goSequenceTakes(key, 10_500)).toBe(true);
    }
    for (const key of ["j", "x", "ArrowDown", "ArrowUp", "Home", "End", " ", "Enter"]) {
      expect(goSequenceTakes(key, 10_500)).toBe(false);
    }
  });

  it("takes no key once the sequence is over", () => {
    expect(goSequenceTakes("k", 10_500)).toBe(false);

    armGoSequence(10_000);

    expect(goSequenceTakes("k", 11_000)).toBe(false);
  });
});
