import type { ReactNode } from "react";

import { Icon, PathText, type IconName } from "../../../components";
import { EffectBadge } from "../parts";
import type { ScenarioAction } from "../queries";
import { maxChecks, pace } from "../story";
import { conditionWords, shown, text, type BuilderNode, type Json } from "./model";

/* What a step card says (scenario builder v5): a title a person reads, the line of what runs
 * (action · language · script) and a small facts grid (With, Calls, Gives, Keeps, Checks…).
 * Every fact is read from the scenario's keys or the action's own files; nothing is guessed.
 * A value that comes from elsewhere is a value token (icon + name), never `$CTX.x`. */

function record(value: Json | undefined): Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

/** Where a value comes from, when it is a reference. */
export function tokenOf(value: string): { icon: IconName; label: string; title: string } | null {
  const input = /^\$INPUTS\.([A-Za-z0-9_]+)$/.exec(value);
  if (input) {
    const name = input[1] ?? "";
    return { icon: "flag", label: name, title: `Scenario input ${name}` };
  }
  const kept = /^\$CTX\.([A-Za-z0-9_]+)$/.exec(value);
  if (kept) {
    const name = kept[1] ?? "";
    return { icon: "bookmark", label: name, title: `Kept value ${name}` };
  }
  const self = /^\$self\.output\.(.+)$/.exec(value);
  if (self) {
    const path = self[1] ?? "";
    return { icon: "corner-down-right", label: path, title: `Output ${path} of this step` };
  }
  const typed = /^\$([a-z0-9_-]+)\.output\.text$/i.exec(value);
  if (typed) {
    const step = typed[1] ?? "";
    return {
      icon: "hand",
      label: `answer of ${step}`,
      title: `The value typed at step ${step}`,
    };
  }
  const output = /^\$([a-z0-9_-]+)\.output(?:\.(.+))?$/i.exec(value);
  if (output) {
    const step = output[1] ?? "";
    const path = output[2] ?? "output";
    return {
      icon: "corner-down-right",
      label: `${step} · ${path}`,
      title: `Output ${path} of step ${step}`,
    };
  }
  return null;
}

/** A reference drawn as a token: its source's icon and its name. */
export function ValueToken({ value }: { value: string }) {
  const token = tokenOf(value);
  if (!token) return <>{value}</>;
  return (
    <span className="bk-token" title={token.title}>
      <Icon name={token.icon} size="sm" />
      <span className="ah-sr">{token.title.replace(token.label, "")}</span>
      {token.label}
    </span>
  );
}

const REFERENCE = /\$(?:INPUTS|CTX)\.[A-Za-z0-9_]+|\$[a-z0-9_-]+\.output(?:\.[A-Za-z0-9_.]+)?/gi;

/** A text with its references drawn as tokens, inline. */
export function TokenText({ value }: { value: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of value.matchAll(REFERENCE)) {
    const at = match.index;
    if (at > last) parts.push(value.slice(last, at));
    parts.push(<ValueToken key={at} value={match[0]} />);
    last = at + match[0].length;
  }
  if (last < value.length) parts.push(value.slice(last));
  return <>{parts}</>;
}

function firstLine(value: string): string {
  return value.split("\n")[0] ?? "";
}

/** The first sentence of a text (an action's description). */
function firstSentence(value: string): string {
  const line = firstLine(value).trim();
  const cut = /^(.+?[.!?])(\s|$)/.exec(line);
  return cut?.[1] ?? line;
}

/** The step's title: its name; else what its action does; else a sentence from its fields. */
export function cardTitle(node: BuilderNode, action: ScenarioAction | null): string {
  if (typeof node.description === "string" && node.description.trim() !== "") {
    return node.description;
  }
  const condition = text(node.until_when);
  switch (node.type) {
    case "action":
      if (action?.description) return firstSentence(action.description);
      return text(node.action) ? `Run ${text(node.action)}` : "Choose what to run";
    case "expect":
      return condition ? `Wait until ${conditionWords(condition)}` : "Wait until a state holds";
    case "approval":
      return firstSentence(text(node.message)) || "Do something by hand";
    case "wait":
      return `Pause ${text(node.duration) ? pace(text(node.duration)) : "for a while"}`;
    case "include":
      return `Run the scenario ${text(node.include) || "…"}`;
    case "loop_group":
      return condition ? `Repeat until ${conditionWords(condition)}` : "Repeat";
    default:
      return node.type;
  }
}

/** The card's top line: the kind's tile and words, the step number, the marks. */
export function CardHead({
  icon,
  kind,
  number,
  action,
  errors,
  warnings,
  extra,
}: {
  icon: IconName;
  kind: string;
  number: string | undefined;
  action: ScenarioAction | null;
  errors: number;
  warnings: number;
  extra?: ReactNode;
}) {
  return (
    <div className="bk-card-head">
      <span className="bk-icon" aria-hidden>
        <Icon name={icon} size="sm" />
      </span>
      <span className="bk-kind">
        {kind}
        {number && <span className="bk-num"> · Step {number}</span>}
      </span>
      <span className="ah-grow" />
      <span className="bk-marks">
        {action?.effect && <EffectBadge effect={action.effect} words />}
        {action?.draft && (
          <span
            className="bk-mark"
            title="Draft action: commit it in the hub before the scenario can run"
          >
            <Icon name="circle-dashed" size="sm" /> Draft
          </span>
        )}
        {warnings > 0 && (
          <span className="bk-mark" title={`${String(warnings)} warnings`}>
            <Icon name="triangle-alert" size="sm" /> {warnings}
          </span>
        )}
        {errors > 0 && (
          <span
            className="bk-mark bk-errors"
            title={`${String(errors)} ${errors === 1 ? "problem" : "problems"}`}
          >
            <Icon name="circle-x" size="sm" /> {errors}
          </span>
        )}
        {extra}
      </span>
    </div>
  );
}

/** What runs: the action, its language and its script file. */
export function RunsLine({ node, action }: { node: BuilderNode; action: ScenarioAction | null }) {
  if (node.type !== "action" && node.type !== "expect") return null;
  const ref = text(node.action);
  if (!ref) return null;
  if (!action) {
    return (
      <div className="bk-runs-line bk-runs-missing" aria-label="Runs">
        <Icon name="circle-x" size="sm" /> {ref} is not an action of this hub
      </div>
    );
  }
  return (
    <div className="bk-runs-line" aria-label="Runs">
      <Icon name="circle-play" size="sm" />
      <span className="ah-mono">{action.name}</span>
      <span className="bk-quiet">· {action.runtime === "python" ? "Python" : "Shell"}</span>
      {action.script ? (
        <span className="bk-quiet">
          · <PathText path={action.script.replace(/^actions\/[^/]+\//, "")} max={36} dimDir />
        </span>
      ) : (
        <span className="bk-quiet">· script not declared</span>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="sc-value">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** A value of the With rows: a token, a JSON read short, or the literal. */
function WithValue({ value }: { value: Json }) {
  const written = shown(value);
  if (tokenOf(written)) return <ValueToken value={written} />;
  if (typeof value === "object" && value !== null) {
    return <span className="ah-mono">{summarizeJson(value)}</span>;
  }
  if (/^\s*[[{]/.test(written)) {
    return <span className="ah-mono">{summarizeText(written)}</span>;
  }
  return <TokenText value={written} />;
}

/** A JSON object written as text, read short: its keys, with literal values. */
function summarizeText(written: string): string {
  try {
    return summarizeJson(JSON.parse(written) as Json);
  } catch {
    // Not strict JSON (a reference written bare): its keys and literal values as written.
    const parts = [...written.matchAll(/"([^"]+)"\s*:\s*("([^"$]*)"|[^,}\]]+)?/g)].map((match) =>
      match[3] !== undefined && match[3] !== ""
        ? `${match[1] ?? ""}: ${match[3]}`
        : (match[1] ?? ""),
    );
    return parts.length > 0 ? `{${parts.join(", ")}}` : written;
  }
}

function summarizeJson(value: Json): string {
  const data = record(value);
  const parts = Object.entries(data).map(([key, item]) =>
    (typeof item === "string" && !item.startsWith("$")) ||
    typeof item === "number" ||
    typeof item === "boolean"
      ? `${key}: ${String(item)}`
      : key,
  );
  return `{${parts.join(", ")}}`;
}

/** The With rows: literals first, then values from earlier steps; inputs passed straight through
 * fold into one row. At most 3 rows unless the card is selected. */
function WithRows({ node, selected }: { node: BuilderNode; selected: boolean }) {
  const given = Object.entries(record(node.with));
  if (given.length === 0) return null;
  const through = given.filter(([key, value]) => value === `$INPUTS.${key}`).map(([key]) => key);
  const rest = given.filter(([key, value]) => value !== `$INPUTS.${key}`);
  const rank = (value: Json) => {
    const written = shown(value);
    if (!tokenOf(written)) return 0;
    return written.startsWith("$INPUTS.") ? 2 : 1;
  };
  const ordered = [...rest].sort((a, b) => rank(a[1]) - rank(b[1]));
  const room = selected ? ordered.length : through.length > 0 ? 2 : 3;
  const shownRows = ordered.length > room ? ordered.slice(0, room - 1) : ordered;
  const more = ordered.length - shownRows.length;
  return (
    <>
      {shownRows.map(([key, value], index) => (
        <div key={key} className="sc-value">
          <dt className={index === 0 ? undefined : "bk-dt-blank"}>{index === 0 ? "With" : ""}</dt>
          <dd className="bk-with">
            <span className="bk-key">{key}</span>
            <span className="bk-val">
              <WithValue value={value} />
            </span>
          </dd>
        </div>
      ))}
      {more > 0 && (
        <Row label={shownRows.length === 0 ? "With" : ""}>
          <span className="bk-quiet">+ {more} more values</span>
        </Row>
      )}
      {through.length > 0 && (
        <Row label={shownRows.length === 0 && more === 0 ? "With" : ""}>
          <span className="bk-quiet">
            {selected
              ? `${through.join(", ")} from scenario inputs`
              : `+ ${String(through.length)} from scenario inputs`}
          </span>
        </Row>
      )}
    </>
  );
}

/** The facts grid of a card, by kind. */
export function CardFacts({
  node,
  action,
  selected,
}: {
  node: BuilderNode;
  action: ScenarioAction | null;
  selected: boolean;
}) {
  const named = typeof node.description === "string" && node.description.trim() !== "";
  const rows: ReactNode[] = [];
  if (node.type === "expect") {
    const every = text(node.every);
    const timeout = text(node.timeout);
    const checks = every && timeout ? maxChecks(every, timeout) : null;
    if (named && text(node.until_when)) {
      rows.push(
        <Row key="until" label="Until">
          {conditionWords(text(node.until_when))}
        </Row>,
      );
    }
    rows.push(
      <Row key="checks" label="Checks">
        {every && timeout ? (
          `every ${pace(every)}, up to ${pace(timeout)}${checks !== null ? ` (at most ${String(checks)} checks)` : ""}`
        ) : (
          <span className="bk-errors">timing not set</span>
        )}
      </Row>,
    );
  }
  if (node.type === "action" || node.type === "expect" || node.type === "include") {
    rows.push(<WithRows key="with" node={node} selected={selected} />);
  }
  if (action && (node.type === "action" || node.type === "expect")) {
    const given = record(node.with);
    const services = action.inputs
      .filter((input) => input.type === "service")
      .map((input) => given[input.name])
      .filter((value): value is Json => value !== undefined);
    if (services.length > 0) {
      rows.push(
        <Row key="calls" label="Calls">
          {services.map((value, index) => (
            <span key={index} className="bk-call">
              <Icon name="globe" size="sm" /> <ValueToken value={shown(value)} />
            </span>
          ))}
        </Row>,
      );
    }
    const outputs = Object.keys(record(action.output_format?.properties as Json | undefined));
    if (outputs.length > 0 && (node.type === "action" || selected)) {
      const cap = 4;
      rows.push(
        <Row key="gives" label="Gives">
          {selected || outputs.length <= cap ? (
            outputs.join(", ")
          ) : (
            <>
              {outputs.slice(0, cap).join(", ")}{" "}
              <span className="bk-quiet">+{outputs.length - cap} more</span>
            </>
          )}
        </Row>,
      );
    }
  }
  const kept = Object.entries(record(node.capture));
  if (kept.length > 0) {
    rows.push(
      <Row key="keeps" label="Keeps">
        {kept.map(([name, from]) => (
          <span key={name} className="bk-keep">
            <ValueToken value={`$CTX.${name}`} />
            <span className="bk-quiet">
              ← {shown(from).replace(/^\$self\.output\.?/, "") || "output"}
            </span>
          </span>
        ))}
      </Row>,
    );
  }
  if (node.type === "approval") {
    const message = text(node.message);
    const rest = message.slice(firstSentence(message).length).trim();
    if (rest || named) {
      rows.push(
        <Row key="do" label="You do">
          <span className={selected ? undefined : "bk-clamp-3"}>
            <TokenText value={named ? message : rest} />
          </span>
        </Row>,
      );
    }
    const answers = (Array.isArray(node.decisions) ? node.decisions : [])
      .map((decision) => text(record(decision).label) || text(record(decision).id))
      .filter((label) => label !== "");
    rows.push(
      <Row key="answers" label="Answers">
        {answers.join(" · ") || "Approve · Reject"}
      </Row>,
    );
    if (node.capture_response === true) {
      rows.push(
        <Row key="asks" label="Asks for">
          a typed value later steps can use
        </Row>,
      );
    }
  }
  if (node.type === "loop_group") {
    rows.push(
      <Row key="rounds" label="Rounds">
        at most {text(node.max_iterations, "1")}, checked after each round
      </Row>,
    );
  }
  if (rows.length === 0) return null;
  return <dl className="sc-values bk-facts-grid">{rows}</dl>;
}
