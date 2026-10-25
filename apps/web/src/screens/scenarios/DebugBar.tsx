import { useState } from "react";

import { Button, CodeBlock, Icon } from "../../components";
import { isRunControlOff } from "./Investigation";
import { blockWords, DEBUG_LOCKED, runBlock } from "./RunBlocks";
import { useDebugCommand, type DebugCommand, type ScenarioRunDetail } from "./queries";

/* A scenario run in a debug pause (AGH-507, ADR 0049, spec 23): the block it paused before and
 * why, and, off production, Step and Continue. Neither answers a gate, edits a value, re-runs or
 * skips a block: each is a resume the CLI records with who sent it. */

const COMMAND_WORDS: Readonly<Record<DebugCommand, string>> = {
  step: "Step",
  continue: "Continue",
};

/** Why the run paused there, in words. */
function reasonWords(reason: string): string {
  return reason === "step" ? "after a Step" : "at its breakpoint";
}

/** The debug pause of `run` (nothing when it is in none). `production` is the run environment's flag as the
 * hub reads it now (null while unknown): Step and Continue only off production. */
export function DebugBar({
  run,
  production,
}: {
  run: ScenarioRunDetail;
  production: boolean | null;
}) {
  const command = useDebugCommand(run.run_id);
  // The command sent from this pause: the bar waits until the run leaves it.
  const [sent, setSent] = useState<{ command: DebugCommand; number: number } | null>(null);
  const pause = run.debug ?? null;
  if (pause === null) return null;
  if (sent !== null && sent.number !== pause.number) {
    // The run moved on to another pause (state adjusted while rendering).
    setSent(null);
  }
  const block = runBlock(run, pause.block);
  const words = blockWords(block);
  const send = (which: DebugCommand) => {
    command.mutate(which, {
      onSuccess: () => {
        setSent({ command: which, number: pause.number });
      },
    });
  };
  const error = command.error;
  return (
    <section
      aria-label={`Paused before block ${pause.block}`}
      className="sc-debug-bar"
      style={{
        background: "var(--waiting-soft)",
        borderLeft: "4px solid var(--waiting)",
        borderRadius: "var(--radius-lg)",
        padding: "12px 16px",
        display: "grid",
        gridTemplateColumns: "24px 1fr",
        gap: 10,
      }}
    >
      <Icon name="circle-pause" style={{ color: "var(--waiting)", marginTop: 2 }} />
      <div className="ah-stack" style={{ gap: 6 }}>
        <b>
          Paused before block {pause.block}
          {words && ` (${words})`}, {reasonWords(pause.reason)}.
        </b>
        <span>Nothing of this block has run yet.</span>
        {production === true ? (
          <>
            <span>
              Step and Continue are off: {run.environment ?? "this"} is a production environment. To
              go on without stopping at breakpoints, resume it from a terminal:
            </span>
            <CodeBlock code={`./hub workflow run --resume ${run.run_id}`} />
          </>
        ) : (
          <>
            <span>
              Step runs the next block and pauses before the one after it; Continue runs to the next
              breakpoint or the end. Neither answers a gate, edits a value, or re-runs or skips a
              block.
            </span>
            <div className="ah-row ah-wrap" style={{ gap: 8 }}>
              <Button
                variant="primary"
                icon="corner-down-right"
                disabled={production === null || command.isPending || sent !== null}
                onClick={() => {
                  send("step");
                }}
              >
                Step
              </Button>
              <Button
                icon="play"
                disabled={production === null || command.isPending || sent !== null}
                onClick={() => {
                  send("continue");
                }}
              >
                Continue
              </Button>
            </div>
            {sent !== null && (
              <span role="status" className="ah-small">
                {COMMAND_WORDS[sent.command]} sent: the scenario run goes on, and its events update
                this page.
              </span>
            )}
            {error !== null && (
              <span role="alert" className="ah-stack" style={{ gap: 4 }}>
                <b>Could not send {COMMAND_WORDS[command.variables]}</b>
                {isRunControlOff(error) ? (
                  <>
                    <span>
                      Step and Continue cannot be sent from the agent-hub container. Run hub web on
                      your machine, or from a terminal:
                    </span>
                    <CodeBlock code={`./hub scenario ${command.variables} ${run.run_id}`} />
                  </>
                ) : (
                  <span>{error.status === 401 ? DEBUG_LOCKED : (error.detail ?? error.title)}</span>
                )}
              </span>
            )}
          </>
        )}
      </div>
    </section>
  );
}
