import { useState, type ReactNode } from "react";

import { Icon, PathText, type IconName } from "../../../components";
import type { ScenarioAction, ScenarioPlanRow } from "../queries";
import { pace } from "../story";
import { conditionWords, refInWords, shown, text, type BuilderNode, type Json } from "./model";

/* What a block does, concretely, under its sentence: the action it runs (what it does, the script
 * and its runtime), the services it calls (and, after a preview in an environment, the endpoint
 * and what the script's plan mode says it would do there), its effect, what it gives and keeps.
 * Read from the action's own files and the scenario's keys; nothing is guessed. */

const EFFECT: Readonly<Record<string, { icon: IconName; words: string }>> = {
  read: { icon: "file-text", words: "Only reads: changes nothing" },
  write: { icon: "file-pen", words: "Changes data" },
  destroy: { icon: "triangle-alert", words: "Deletes or replaces data" },
};

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="bk-fact-label">{label}</dt>
      <dd className="bk-fact">{children}</dd>
    </>
  );
}

function record(value: Json | undefined): Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

interface Endpoint {
  service: string;
  url: string | null;
  resource: string | null;
}

function endpoints(row: ScenarioPlanRow | null): Endpoint[] {
  return row ? Object.values(row.endpoints) : [];
}

const DECISION: Readonly<Record<string, { icon: IconName; words: string; tone: string }>> = {
  allow: { icon: "circle-check", words: "runs without asking", tone: "var(--done)" },
  ask: { icon: "hand", words: "asks you first", tone: "var(--waiting)" },
  deny: { icon: "octagon-x", words: "denied", tone: "var(--failed)" },
};

/** The facts in one quiet line: the script it runs, the services it calls, its effect. */
function FactsLine({
  node,
  action,
  row,
}: {
  node: BuilderNode;
  action: ScenarioAction | null;
  row: ScenarioPlanRow | null;
}) {
  if ((node.type !== "action" && node.type !== "expect") || !action) return null;
  const given = record(node.with);
  const services = action.inputs
    .filter((input) => input.type === "service")
    .map((input) => {
      const value = given[input.name];
      return value === undefined ? null : refInWords(shown(value)).text;
    })
    .filter((value): value is string => value !== null);
  const effect = action.effect ? EFFECT[action.effect] : undefined;
  const script = (action.script ?? "").split("/").at(-1) ?? "";
  return (
    <span className="bk-line">
      <span title={action.script ?? undefined}>
        <Icon name="terminal" size="sm" /> {script}
      </span>
      {services.map((service) => (
        <span key={service}>
          <Icon name="globe" size="sm" /> {service}
        </span>
      ))}
      {effect && (
        <span>
          <Icon name={effect.icon} size="sm" />{" "}
          {action.effect === "read"
            ? "reads"
            : action.effect === "write"
              ? "changes data"
              : "deletes"}
        </span>
      )}
      {row && <span className="bk-line-plan">{row.plan}</span>}
    </span>
  );
}

export function BlockFacts({
  node,
  action,
  row,
  environment,
  compact = false,
}: {
  node: BuilderNode;
  action: ScenarioAction | null;
  row: ScenarioPlanRow | null;
  environment: string | null;
  /** One line (what it runs, calls and changes); the full facts when the block is selected. */
  compact?: boolean;
}) {
  const [script, setScript] = useState(false);
  if (compact) return <FactsLine node={node} action={action} row={row} />;
  if (node.type === "approval") {
    return (
      <dl className="bk-facts">
        <Fact label="You do">{text(node.message) || "—"}</Fact>
        {node.capture_response === true && (
          <Fact label="You type">
            a value later blocks read as <span className="ah-mono">${node.id}.output.text</span>
          </Fact>
        )}
        <Fact label="Answers">
          {(Array.isArray(node.decisions) ? node.decisions : [])
            .map((decision) => text(record(decision).label))
            .filter(Boolean)
            .join(" · ") || "approve · reject"}
        </Fact>
      </dl>
    );
  }
  if (node.type === "wait") {
    return (
      <dl className="bk-facts">
        <Fact label="Pauses">{text(node.duration) ? pace(text(node.duration)) : "—"}</Fact>
      </dl>
    );
  }
  if (node.type === "include") {
    return (
      <dl className="bk-facts">
        <Fact label="Runs">the steps of the scenario {text(node.include) || "…"} (same pack)</Fact>
      </dl>
    );
  }
  if (node.type !== "action" && node.type !== "expect") return null;
  if (!action) {
    return (
      <dl className="bk-facts">
        <Fact label="Runs">
          {text(node.action) ? (
            <span style={{ color: "var(--failed)" }}>
              the action {text(node.action)} is not in this hub
            </span>
          ) : (
            "nothing yet: choose an action"
          )}
        </Fact>
      </dl>
    );
  }
  const given = record(node.with);
  const services = action.inputs.filter((input) => input.type === "service");
  const effect = action.effect ? EFFECT[action.effect] : undefined;
  const outputs = Object.keys(record(action.output_format?.properties as Json | undefined));
  const kept = Object.entries(record(node.capture));
  const planned = endpoints(row);
  const decision = row ? DECISION[row.decision] : undefined;
  return (
    <>
      <dl className="bk-facts">
        {action.description && <Fact label="Does">{action.description}</Fact>}
        <Fact label="Runs">
          <span className="bk-runs">
            <span>{action.runtime === "python" ? "Python" : "Shell"}</span>
            <span className="ah-mono">
              <PathText path={action.script ?? ""} max={56} dimDir />
            </span>
            <button
              type="button"
              className="bk-fact-link"
              data-no-pan=""
              aria-expanded={script}
              onPointerDown={(event) => {
                event.stopPropagation();
              }}
              onClick={(event) => {
                event.stopPropagation();
                setScript(!script);
              }}
            >
              {script ? "hide script" : "show script"}
            </button>
            {action.draft && <span className="bk-draft">draft · commit to run</span>}
          </span>
        </Fact>
        {services.length > 0 && (
          <Fact label="Calls">
            {services.map((input) => {
              const value = given[input.name];
              const words = value === undefined ? null : refInWords(shown(value));
              const at = planned.find((item) => item.service === shown(value)) ?? planned[0];
              return (
                <span key={input.name} className="bk-call">
                  <Icon name="globe" size="sm" />
                  {words ? (
                    <b>{words.text}</b>
                  ) : (
                    <span className="bk-quiet">the service in {input.name} (not set)</span>
                  )}
                  {at && environment && (
                    <span className="bk-quiet">
                      {" "}
                      → {at.url ?? at.resource ?? "no endpoint"} in {environment}
                    </span>
                  )}
                </span>
              );
            })}
          </Fact>
        )}
        {effect && (
          <Fact label="Effect">
            <span className="bk-runs">
              <Icon name={effect.icon} size="sm" /> {effect.words}
            </span>
          </Fact>
        )}
        {node.type === "expect" && text(node.every) && text(node.timeout) && (
          <Fact label="Checks">
            every {pace(text(node.every))}, up to {pace(text(node.timeout))}
            {text(node.until_when) ? `, until ${conditionWords(text(node.until_when))}` : ""}
          </Fact>
        )}
        {outputs.length > 0 && <Fact label="Gives">{outputs.join(", ")}</Fact>}
        {kept.length > 0 && (
          <Fact label="Keeps">
            {kept
              .map(([name, from]) => `${name} ← ${shown(from).replace(/^\$self\.output\.?/, "")}`)
              .join(", ")}
          </Fact>
        )}
        {row && environment && (
          <Fact label={`In ${environment}`}>
            <span className="bk-plan">
              {decision && (
                <span style={{ color: decision.tone }} className="ah-row">
                  <Icon name={decision.icon} size="sm" /> {decision.words}
                  {row.reason ? ` (${row.reason})` : ""}
                </span>
              )}
              <span>{row.plan}</span>
            </span>
          </Fact>
        )}
      </dl>
      {script && (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrollable region
        <pre className="bk-script" tabIndex={0} aria-label={`Script of ${action.name}`}>
          {action.script_text ?? "The script could not be read."}
        </pre>
      )}
    </>
  );
}
