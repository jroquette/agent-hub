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

/** A key typed into a field or a dialog is not a shortcut, the shell's or a screen's. */
export function typingIn(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.closest("[role=dialog]") !== null
  );
}
