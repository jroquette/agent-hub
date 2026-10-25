import { useState } from "react";

import { Button, CodeBlock, Icon } from "../../components";
import { isRunControlOff } from "./Investigation";
import { DEBUG_LOCKED, debugReasonWords } from "./parts";
import { blockWords, runBlock } from "./RunBlocks";
import { useDebugCommand, type DebugCommand, type ScenarioRunDetail } from "./queries";

/* A scenario run in a debug pause (ADR 0049, spec 23 § Debugging a run written as blocks): the
 * block it paused before and why, and, off production, Step and Continue. Neither answers a gate,
 * edits a value, re-runs or skips a block: each is a resume the CLI records with who sent it. */

const COMMAND_WORDS: Readonly<Record<DebugCommand, string>> = {
  step: "Step",
  continue: "Continue",
};

/** The debug pause of `run` (nothing when it is in none). `production` is the run environment's
 * flag as the hub reads it now (null while unknown): Step and Continue show only once it is
 * false. */
export function DebugBar({
  run,
  production,
}: {
  run: ScenarioRunDetail;
  production: boolean | null;
}) {
  const command = useDebugCommand(run.run_id);
  // The pause the last command was pressed in: its answer (sent, or refused) shows only there.
  const [pressed, setPressed] = useState<number | null>(null);
  const pause = run.debug ?? null;
  if (pause === null) return null;
  if (pressed !== null && pressed !== pause.number) {
    // The run moved on to another pause (state adjusted while rendering).
    setPressed(null);
  }
  const here = pressed === pause.number;
  const block = runBlock(run, pause.block);
  const words = blockWords(block);
  // Once sent, the bar waits until the run leaves this pause.
  const sent = here && command.isSuccess ? command.variables : null;
  const failed =
    here && command.isError ? { error: command.error, which: command.variables } : null;
  // Off, but focusable: the pressed button keeps focus (aria-disabled, not disabled).
  const busy = command.isPending || sent !== null;
  const send = (which: DebugCommand) => {
    if (busy) return;
    setPressed(pause.number);
    command.mutate(which);
  };
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
          {words && ` (${words})`}, {debugReasonWords(pause.reason)}.
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
        ) : production === false ? (
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
                aria-disabled={busy || undefined}
                onClick={() => {
                  send("step");
                }}
              >
                Step
              </Button>
              <Button
                icon="play"
                aria-disabled={busy || undefined}
                onClick={() => {
                  send("continue");
                }}
              >
                Continue
              </Button>
            </div>
            {sent !== null && (
              <span role="status" className="ah-small">
                {COMMAND_WORDS[sent]} sent: the scenario run goes on, and its events update this
                page.
              </span>
            )}
            {failed !== null && (
              <span role="alert" className="ah-stack" style={{ gap: 4 }}>
                <b>Could not send {COMMAND_WORDS[failed.which]}</b>
                {isRunControlOff(failed.error) ? (
                  <>
                    <span>
                      Step and Continue cannot be sent from the agent-hub container. Run hub web on
                      your machine, or from a terminal:
                    </span>
                    <CodeBlock code={`./hub scenario ${failed.which} ${run.run_id}`} />
                  </>
                ) : (
                  <span>
                    {failed.error.status === 401
                      ? DEBUG_LOCKED
                      : (failed.error.detail ?? failed.error.title)}
                  </span>
                )}
              </span>
            )}
          </>
        ) : null}
      </div>
    </section>
  );
}
