import { useMemo } from "react";

import { Banner, CodeBlock, StatusBadge } from "../../components";
import { isRunControlOff } from "./Investigation";
import { DEBUG_LOCKED } from "./parts";
import { BreakpointToggle } from "./StepCard";
import { useSetBreakpoints, type RunBlock, type ScenarioRunDetail } from "./queries";

/* The blocks a scenario run written as blocks pinned when it started (ADR 0049, spec 23): each
 * one's address, kind and label, its state in this run and, off production, its breakpoint. The
 * blocks come from the run, never from the scenario file as it reads now, so an edit in the
 * builder changes none of them. */

const KIND_WORDS: Readonly<Record<string, string>> = {
  stage: "Stage",
  do: "Do",
  wait_until: "Wait until",
  you: "You",
  wait: "Wait",
  include: "Include",
  repeat: "Repeat",
  if: "If",
  together: "At the same time",
};

// The blocks that run a node of their own: their lines in the run give their state.
const OWN_NODES = new Set(["do", "wait_until", "you", "wait", "include", "repeat"]);
const GATE_SUFFIXES = ["__ask", "__investigation"];

/** A block in words: its kind, then its label (`Do: queue-send`). */
export function blockWords(block: RunBlock | undefined): string {
  if (block === undefined) return "";
  return `${KIND_WORDS[block.kind] ?? block.kind}: ${block.label}`;
}

/** The pinned block at `address`, if the run holds one. */
export function runBlock(run: ScenarioRunDetail, address: string): RunBlock | undefined {
  return run.blocks.find((block) => block.address === address);
}

/** How deep a block sits: a stage is 0, its blocks 1, and each container's blocks one more. */
function depthOf(address: string): number {
  return address.split(".").filter((part) => /^[0-9]+$/.test(part)).length - 1;
}

type BlockState = "paused" | "running" | "done" | "failed" | "skipped" | "waiting" | null;
type TimelineLine = ScenarioRunDetail["timeline"][number];

/** Each block's last start or end line of its own, in one pass over the timeline (a gate's
 * lines are its step's, but neither starts nor ends the step). */
function lastLines(timeline: readonly TimelineLine[]): ReadonlyMap<string, TimelineLine> {
  const last = new Map<string, TimelineLine>();
  for (const entry of timeline) {
    if (entry.block === null || entry.block === undefined) continue;
    if (entry.event !== "step_start" && entry.event !== "step_end") continue;
    if (GATE_SUFFIXES.some((suffix) => (entry.node ?? "").endsWith(suffix))) continue;
    last.set(entry.block, entry);
  }
  return last;
}

/** A block's state in the run, from its last line of its own; `waiting` for a block of its own
 * nodes not started yet. */
function stateOf(
  run: ScenarioRunDetail,
  block: RunBlock,
  lines: ReadonlyMap<string, TimelineLine>,
): BlockState {
  if (run.debug?.block === block.address) return "paused";
  if (!OWN_NODES.has(block.kind)) return null;
  const last = lines.get(block.address);
  if (last === undefined) return run.status === null ? "waiting" : null;
  if (last.event === "step_start") return "running";
  if (last.status === "failed") return "failed";
  if (last.status === "skipped") return "skipped";
  return "done";
}

function State({ state }: { state: BlockState }) {
  if (state === "paused") return <StatusBadge status="waiting" label="Paused before it" />;
  if (state === "running") return <StatusBadge status="running" />;
  if (state === "done") return <StatusBadge status="done" />;
  if (state === "failed") return <StatusBadge status="failed" />;
  if (state === "skipped") return <span className="ah-small ah-subtle">Skipped</span>;
  if (state === "waiting") return <span className="ah-small ah-subtle">Not started</span>;
  return null;
}

/** The run's blocks. `production` is the run environment's flag as the hub reads it now (null
 * while unknown): breakpoints are set only off production, and never once the run ended done
 * or cancelled. */
export function RunBlocks({
  run,
  production,
}: {
  run: ScenarioRunDetail;
  production: boolean | null;
}) {
  const set = useSetBreakpoints(run.run_id);
  // Once per read of the record, not on every tick of the page's clock.
  const lines = useMemo(() => lastLines(run.timeline), [run.timeline]);
  const ended = run.status === "done" || run.status === "cancelled";
  const settable = !ended && production === false;
  // While a change is on its way, its set shows; then the one the server wrote.
  const shown = (set.isPending ? set.variables : undefined) ?? run.breakpoints;
  const toggle = (address: string) => {
    const wanted = new Set(shown);
    if (wanted.has(address)) wanted.delete(address);
    else wanted.add(address);
    // In the pinned tree's order, as the server writes them.
    set.mutate(run.blocks.map((block) => block.address).filter((each) => wanted.has(each)));
  };
  const error = set.error;
  return (
    <section aria-label="Blocks" className="ah-stack" style={{ gap: 8, minWidth: 0 }}>
      <h2 className="ah-h3" style={{ margin: 0 }}>
        Blocks
      </h2>
      <span className="ah-small ah-muted">
        As this scenario run pinned them when it started: editing the scenario changes none of them.
        {settable &&
          " A breakpoint pauses the scenario run before its block, from the next block it starts."}
        {!ended &&
          production === true &&
          ` Breakpoints are off: ${run.environment ?? "this"} is a production environment.`}
      </span>
      <ol className="sc-blocks">
        {run.blocks.map((block) => (
          <li
            key={block.address}
            className="sc-block"
            style={{ paddingLeft: 8 + 20 * depthOf(block.address) }}
          >
            <span className="ah-mono ah-small sc-block-address">{block.address}</span>
            <span
              className={
                block.kind === "stage" ? "sc-block-label sc-block-stage" : "sc-block-label"
              }
            >
              {blockWords(block)}
            </span>
            <span className="ah-grow" />
            <State state={stateOf(run, block, lines)} />
            {settable && (
              <BreakpointToggle
                address={block.address}
                on={shown.includes(block.address)}
                busy={set.isPending}
                onToggle={() => {
                  toggle(block.address);
                }}
              />
            )}
          </li>
        ))}
      </ol>
      {error !== null && (
        <Banner tone="error" boxed>
          <span className="ah-stack" style={{ gap: 4 }}>
            <b>Could not set the breakpoints</b>
            {isRunControlOff(error) ? (
              <>
                <span>
                  Breakpoints cannot be set from the agent-hub container. Set them from a terminal:
                </span>
                <CodeBlock
                  code={`./hub scenario break ${run.run_id} --set ${set.variables.join(" ")}`.trimEnd()}
                />
              </>
            ) : (
              <span>{error.status === 401 ? DEBUG_LOCKED : (error.detail ?? error.title)}</span>
            )}
          </span>
        </Banner>
      )}
    </section>
  );
}
