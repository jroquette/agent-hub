import { useId, type ReactNode } from "react";

import { Skeleton } from "../../components";
import { isRunControlOff } from "./Investigation";
import { CaptureValue, DEBUG_LOCKED, MarkedText } from "./parts";
import { runBlock } from "./RunBlocks";
import { plural } from "./timeline";
import { useScenarioRunValues, type BlockValues, type ScenarioRunDetail } from "./queries";

/* What a paused scenario run shows to inspect (ADR 0049, spec 23 § Debugging a run written as
 * blocks): its inputs, the environment's values included, and for each finished block its
 * rendered inputs, status and last output, read from its record with the launch cookie
 * (`GET …/values`), only while it is paused and never on a production environment. Each block's
 * values stay folded until opened. */

const STATUS_WORDS: Readonly<Record<string, string>> = {
  ok: "Done",
  failed: "Failed",
  skipped: "Skipped",
};

function Json({ value }: { value: unknown }) {
  return (
    <pre className="ah-mono ah-small sc-value-json">
      <MarkedText text={JSON.stringify(value ?? null, null, 2)} />
    </pre>
  );
}

function Labelled({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="ah-stack" style={{ gap: 2 }}>
      <span id={id} className="ah-small ah-subtle">
        {label}
      </span>
      {children}
    </div>
  );
}

function Finished({ run, item }: { run: ScenarioRunDetail; item: BlockValues }) {
  // The record's values (`JsonValue`, a recursive type the linter cannot follow).
  const values = item as { with: unknown; output: unknown; last_poll: unknown };
  const block = item.address === null ? undefined : runBlock(run, item.address);
  const status = item.status === null ? "—" : (STATUS_WORDS[item.status] ?? item.status);
  const summary = [
    [item.address, block?.label].filter((part) => part !== null && part !== undefined).join(" "),
    item.node,
    status,
    ...(item.polls > 0 ? [plural(item.polls, "poll")] : []),
  ]
    .filter((part) => part !== "")
    .join(" · ");
  return (
    <li>
      <details className="sc-values-block">
        <summary className="ah-small">{summary}</summary>
        <div className="ah-stack" style={{ gap: 6, padding: "6px 0 4px 14px" }}>
          <Labelled label="With">
            <Json value={values.with} />
          </Labelled>
          <Labelled label="Output">
            <Json value={values.output} />
          </Labelled>
          {item.polls > 0 && (
            <Labelled label={`Last poll (${plural(item.polls, "poll")})`}>
              <Json value={values.last_poll} />
            </Labelled>
          )}
        </div>
      </details>
    </li>
  );
}

/** The values of `run` while `pause` (null when it is not paused) holds it, off production. */
export function RunValues({ run, pause }: { run: ScenarioRunDetail; pause: string | null }) {
  const values = useScenarioRunValues(run.run_id, pause);
  if (pause === null) return null;
  const error = values.error;
  let body: ReactNode;
  if (values.isPending) {
    body = <Skeleton height={48} />;
  } else if (error !== null) {
    body = (
      <span className="ah-small ah-muted">
        {isRunControlOff(error)
          ? "Values cannot be read from the agent-hub container: run hub web on your machine."
          : error.status === 401
            ? DEBUG_LOCKED
            : error.status === 409 && error.code === "not_paused"
              ? "The scenario run is not paused right now: its values show while it is paused."
              : `Could not read the values: ${error.detail ?? error.title}`}
      </span>
    );
  } else {
    const inputs = Object.entries((values.data as { inputs: Record<string, unknown> }).inputs);
    body = (
      <>
        <Labelled label="Inputs, environment values included">
          {inputs.length === 0 ? (
            <span className="ah-small">—</span>
          ) : (
            <ul className="ah-small sc-values-list">
              {inputs.map(([name, value]) => (
                <li key={name}>
                  <span className="ah-mono">{name}</span> = <CaptureValue value={value} />
                </li>
              ))}
            </ul>
          )}
        </Labelled>
        <Labelled label="Finished blocks">
          {values.data.blocks.length === 0 ? (
            <span className="ah-small">None yet.</span>
          ) : (
            <ul className="sc-values-list" aria-label="Finished blocks">
              {values.data.blocks.map((item) => (
                <Finished key={`${item.node}:${String(item.attempt)}`} run={run} item={item} />
              ))}
            </ul>
          )}
        </Labelled>
      </>
    );
  }
  return (
    <aside className="ah-card" aria-label="Values while paused">
      <div className="ah-card-head">
        <b className="ah-small">Values while paused</b>
      </div>
      <div className="ah-stack" style={{ gap: 10, padding: "8px 16px 12px" }}>
        <span className="ah-small ah-muted">
          From the scenario run&apos;s record, credential values already hidden. Shown while it is
          paused, never on a production environment.
        </span>
        {body}
      </div>
    </aside>
  );
}
