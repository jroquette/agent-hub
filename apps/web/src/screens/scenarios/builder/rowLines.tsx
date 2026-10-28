import type { ReactNode } from "react";

import type { ScenarioAction } from "../queries";
import { pace } from "../story";
import { TokenText, ValueToken, cardTitle, firstSentence, tokenOf } from "./CardParts";
import { conditionWords, shown, text, type BuilderNode, type Json } from "./model";

/* What a block says, in one place: its title, the sentence of what it does, and the quiet
 * technical line (its action and short values). The step list's rows and the graph's cards both
 * read it from here, so the two views of a block never say different things. */

function record(value: Json | undefined): Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

export function compact(value: Json): string {
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (/^[[{]/.test(trimmed)) {
      try {
        return JSON.stringify(JSON.parse(trimmed));
      } catch {
        return trimmed.replace(/\s+/g, " ");
      }
    }
    return trimmed.replace(/\s+/g, " ");
  }
  return shown(value);
}

/** Line 2's values: only what the step sets itself (never a run value it merely repeats). */
export function ownValues(node: BuilderNode, action: ScenarioAction | null): [string, Json][] {
  const given = record(node.with);
  const order = action?.inputs.map((input) => input.name) ?? [];
  return Object.entries(given)
    .filter(([name, value]) => value !== `$INPUTS.${name}`)
    .sort((a, b) => {
      const ia = order.indexOf(a[0]);
      const ib = order.indexOf(b[0]);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
}

/** A value written on the row can be edited there: a plain string, number or boolean. */
export function editableValue(value: Json): boolean {
  if (typeof value === "number" || typeof value === "boolean") return true;
  if (typeof value !== "string") return false;
  const trimmed = value.trim();
  return !/^[[{]/.test(trimmed) && !trimmed.includes("\n") && !trimmed.includes("$");
}

/** What was typed, as the value's own type. */
export function typedAs(previous: Json, typed: string): Json {
  if (typeof previous === "number") {
    const n = Number(typed);
    return typed.trim() !== "" && Number.isFinite(n) ? n : typed;
  }
  if (typeof previous === "boolean") {
    if (typed.trim() === "true") return true;
    if (typed.trim() === "false") return false;
  }
  return typed;
}

export function Value({ value }: { value: Json }) {
  const written = compact(value);
  if (tokenOf(written)) return <ValueToken value={written} />;
  return <TokenText value={written} />;
}

/** What line 1 and line 2 say for a node (an action, a check, a repeat …). */
export function nodeLines(
  node: BuilderNode,
  action: ScenarioAction | null,
  inner: number,
): { title: string; detail: ReactNode; tech: ReactNode; detailText: string } {
  const named = typeof node.description === "string" && node.description.trim() !== "";
  const title = cardTitle(node, action);
  const parts: ReactNode[] = [];
  const words: string[] = [];
  const add = (part: ReactNode, word: string) => {
    parts.push(<span key={parts.length}>{part}</span>);
    words.push(word);
  };
  // Line 2 says what the step does, in words; the action and the values it sets go on a quieter
  // technical line under it (and open as chips to edit while the row is selected).
  const ref = text(node.action);
  if (node.type === "action" && action?.description) {
    const said = firstSentence(action.description).replace(/\.$/, "");
    if (said !== title.replace(/\.$/, "")) add(said, said);
  }
  if (node.type === "expect") {
    if (named && text(node.until_when)) {
      const words_ = `until ${conditionWords(text(node.until_when))}`;
      add(words_, words_);
    }
    const every = text(node.every);
    const timeout = text(node.timeout);
    if (every && timeout) {
      const timing = `checks every ${pace(every)}, up to ${pace(timeout)}`;
      add(timing, timing);
    }
  }
  const techParts: ReactNode[] = [];
  const techWords: string[] = [];
  if ((node.type === "action" || node.type === "expect") && ref) {
    techParts.push(
      <span key="ref" className="st-mono">
        {action?.name ?? ref}
      </span>,
    );
    techWords.push(ref);
  }
  if (node.type === "action" || node.type === "expect" || node.type === "include") {
    let more = 0;
    for (const [name, value] of ownValues(node, action)) {
      // A long or structured value (a JSON body) is the open row's: here it is only counted.
      if (!editableValue(value) || compact(value).length > 40) {
        more += 1;
        techWords.push(`${name} ${compact(value)}`);
        continue;
      }
      techParts.push(
        <span key={name}>
          <span className="st-key">{name}</span> <Value value={value} />
        </span>,
      );
      techWords.push(`${name} ${compact(value)}`);
    }
    if (more > 0) {
      techParts.push(
        <span key="more" className="st-key">
          +{more} {more === 1 ? "value" : "values"}
        </span>,
      );
    }
  }
  const kept = Object.keys(record(node.capture));
  if (kept.length > 0) {
    const keep = `keeps ${kept.join(", ")}`;
    add(keep, keep);
  }
  if (node.type === "approval") {
    const asks = node.capture_response === true ? " · asks for a value" : "";
    add(`You approve or reject${asks}`, `You approve or reject${asks}`);
  }
  if (node.type === "loop_group") {
    const rounds = `at most ${text(node.max_iterations, "1")} rounds · ${String(inner)} ${inner === 1 ? "step" : "steps"}`;
    add(rounds, rounds);
  }
  return {
    title,
    detail: parts.length > 0 ? interleave(parts) : null,
    tech: techParts.length > 0 ? interleave(techParts) : null,
    detailText: [...words, ...techWords].join(" · "),
  };
}

export function interleave(parts: ReactNode[]): ReactNode {
  return parts.flatMap((part, index) =>
    index === 0
      ? [part]
      : [
          <span key={`dot-${String(index)}`} className="st-dot" aria-hidden>
            ·
          </span>,
          part,
        ],
  );
}
