import { Icon } from "../../components";

export interface JumpToLatestProps {
  /** Entries that arrived since the reader left the bottom. */
  unseen: number;
  onJump: () => void;
}

/**
 * The way back to the bottom of a detached transcript (AC-234.19): a round button above the
 * composer, "Jump to latest · N new" on screen and "Jump to latest, N new" to assistive tech.
 */
export function JumpToLatest({ unseen, onJump }: JumpToLatestProps) {
  const count = unseen > 0 ? String(unseen) : null;
  return (
    <button
      type="button"
      className="as-jump"
      aria-label={count ? `Jump to latest, ${count} new` : "Jump to latest"}
      onClick={onJump}
    >
      <Icon name="arrow-down" size="sm" />
      <span aria-hidden="true">{count ? `Jump to latest · ${count} new` : "Jump to latest"}</span>
    </button>
  );
}
