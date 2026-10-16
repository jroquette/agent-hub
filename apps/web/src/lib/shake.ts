/** A shake: `reversals` horizontal direction changes, legs of at least `minLeg` px, within `windowMs`. */
export interface ShakeOptions {
  reversals: number;
  minLeg: number;
  windowMs: number;
  cooldownMs: number;
}

export interface ShakeSample {
  x: number;
  t: number;
  pointerType: string;
  buttons: number;
}

export const SHAKE: ShakeOptions = { reversals: 4, minLeg: 40, windowMs: 600, cooldownMs: 1500 };

/** At most this many reversal times are kept, whatever the options. */
const MAX_KEPT = 64;

/**
 * A pure detector over `pointermove` samples: it returns true on the sample that completes a shake.
 * It ignores pointers other than the mouse and any movement with a button held (drag, selection),
 * keeps only the reversals inside the window, and stays quiet for `cooldownMs` after a detection.
 */
export function createShakeDetector(
  options: ShakeOptions = SHAKE,
): (sample: ShakeSample) => boolean {
  let direction = 0;
  let extreme: number | null = null;
  /** When the pointer reached `extreme`: a reversal happens there. */
  let extremeAt = 0;
  let turns: number[] = [];
  let quietUntil = -Infinity;

  const reset = () => {
    direction = 0;
    extreme = null;
    turns = [];
  };

  return (sample) => {
    if (sample.pointerType !== "mouse" || sample.buttons !== 0 || sample.t < quietUntil) {
      reset();
      return false;
    }
    if (extreme === null) {
      extreme = sample.x;
      extremeAt = sample.t;
      return false;
    }
    const delta = sample.x - extreme;
    const sign = Math.sign(delta);
    if (direction === 0) {
      if (Math.abs(delta) >= options.minLeg) {
        direction = sign;
        extreme = sample.x;
        extremeAt = sample.t;
      }
      return false;
    }
    if (sign === direction) {
      extreme = sample.x;
      extremeAt = sample.t;
      return false;
    }
    if (Math.abs(delta) < options.minLeg) return false;

    const turnedAt = extremeAt;
    direction = sign;
    extreme = sample.x;
    extremeAt = sample.t;
    turns = [...turns, turnedAt].filter((t) => sample.t - t <= options.windowMs).slice(-MAX_KEPT);
    if (turns.length < options.reversals) return false;
    reset();
    quietUntil = sample.t + options.cooldownMs;
    return true;
  };
}
