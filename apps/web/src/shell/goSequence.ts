/** How long after `g` its second key still counts (spec 01 keyboard map). */
export const SEQUENCE_MS = 1000;

let armedAt = 0;

/** `g` was pressed: the next plain key within SEQUENCE_MS belongs to the shell. */
export function armGoSequence(now = Date.now()): void {
  armedAt = now;
}

export function clearGoSequence(): void {
  armedAt = 0;
}

/**
 * Whether a `g` sequence waits for its second key. A screen's own single-key shortcut (a card's
 * `a`) leaves such a key to the shell, so `g a` never answers the card.
 */
export function goSequencePending(now = Date.now()): boolean {
  return armedAt !== 0 && now - armedAt < SEQUENCE_MS;
}

/** `g` then a key goes to a destination (spec 01 keyboard map). */
export const GO: Readonly<Record<string, string>> = {
  p: "/",
  // Kept from the retired Live sessions (O-6).
  l: "/sessions?view=grid",
  s: "/sessions",
  r: "/runs",
  k: "/knowledge/learnings",
  f: "/features",
  h: "/health",
  c: "/config",
  ",": "/settings",
};

/**
 * The second keys of the other `g` sequences in spec 01's keyboard map, kept as the map lists
 * them: `g w`, `g m`, `g b` and `g t` (destinations not built yet), `g o` (project switcher), `g u`
 * (up one crumb) and Session detail's `g g`. The shell acts on none of them yet; a screen that
 * leaves them to a `g` sequence needs no change once it does.
 */
const OTHER_SEQUENCE_KEYS: ReadonlySet<string> = new Set(["w", "m", "b", "t", "o", "u", "g"]);

/**
 * Whether `key` is the second key of a `g` sequence that waits for it. A screen whose keys are
 * also arrows or other letters (a tree's `↓`, `j`) leaves only these to the shell.
 */
export function goSequenceTakes(key: string, now = Date.now()): boolean {
  return goSequencePending(now) && (Object.hasOwn(GO, key) || OTHER_SEQUENCE_KEYS.has(key));
}

/** A key typed into a field or a dialog is not a shortcut, the shell's or a screen's. */
export function typingIn(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.closest("[role=dialog]") !== null
  );
}
