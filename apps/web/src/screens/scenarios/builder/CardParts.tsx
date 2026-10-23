import type { ReactNode } from "react";

import { Icon, Skeleton, type IconName } from "../../../components";
import type { ScenarioAction } from "../queries";
import { pace } from "../story";
import { conditionWords, text, type BuilderNode } from "./model";

/* What a step says, shared by the step list and the editor: its title (a name a person reads)
 * and its values drawn as tokens. A value that comes from elsewhere is a value token (icon +
 * name), never `$CTX.x`. */

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
    case "action": {
      // The id the author chose ("fetch-orders") says why the step is there; an id the builder
      // made (the action's name, "script-2") does not.
      const ref = text(node.action).split("/").at(-1) ?? "";
      const base = node.id.replace(/-\d+$/, "");
      if (base !== ref && base !== "script" && /^[a-z][a-z0-9-]*$/.test(node.id)) {
        const words = node.id.replace(/-/g, " ");
        return words.charAt(0).toUpperCase() + words.slice(1);
      }
      if (action?.description) return firstSentence(action.description);
      return text(node.action) ? `Run ${text(node.action)}` : "Choose what to run";
    }
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

/** A card while the scenario loads: the final shape (head, two title lines, runs line, facts). */
export function CardSkeleton() {
  return (
    <div className="bk-card bk-card-skeleton" aria-hidden="true">
      <div className="bk-card-head">
        <Skeleton width={24} height={24} radius={4} />
        <Skeleton width={110} height={12} />
      </div>
      <Skeleton lines={2} height={14} />
      <Skeleton width={240} height={12} />
      <div className="bk-facts-grid">
        <Skeleton lines={3} height={12} />
      </div>
    </div>
  );
}
