import { Button } from "../../components";

/* A breakpoint toggle (a scenario written as blocks, ADR 0049), used where a scenario run's
 * pinned blocks are listed. The scenario page's blocks carry their own, on each row. */

/** A breakpoint before block `address` (a scenario written as blocks, ADR 0049): a toggle whose
 * name stays the same, its state in `aria-pressed`; Tab reaches it, Space or Enter presses it.
 * While `busy` (a change on its way) a press does nothing, and the toggle keeps focus
 * (`aria-disabled`, not `disabled`). */
export function BreakpointToggle({
  address,
  on,
  busy,
  onToggle,
}: {
  address: string;
  on: boolean;
  busy?: boolean | undefined;
  onToggle: () => void;
}) {
  return (
    <Button
      size="sm"
      variant="ghost"
      icon={on ? "circle-dot" : "circle"}
      className={on ? "sc-break sc-break-on" : "sc-break"}
      aria-pressed={on}
      aria-label={`Breakpoint before block ${address}`}
      title={
        on
          ? `The scenario run pauses before block ${address}. Press to remove the breakpoint.`
          : `Press to pause the scenario run before block ${address}.`
      }
      aria-disabled={busy === true || undefined}
      onClick={() => {
        if (!busy) onToggle();
      }}
    >
      Breakpoint
    </Button>
  );
}
