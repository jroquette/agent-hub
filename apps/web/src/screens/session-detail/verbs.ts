/*
 * The verb table of the timeline (AGH-201, AC-201.17): each row says, in a plain verb, the
 * concrete thing done — the skill, the subagent and its task, the file, the command head, the
 * recipient. Pure functions over the stored metadata; no content is ever shown.
 */
import type { components } from "../../api/schema";
import { fmtInt } from "../../lib/format";

type Payload = components["schemas"]["TimelineEvent"]["payload"];

/** How a phrase's object reads: a command in backticks, a path or pattern in mono, or text. */
export type ObjectKind = "command" | "code" | "text";

/** A row's sentence: "Ran `make check`", "Edited a.py (+3 −1)", "Started subagent Explore: …". */
export interface Phrase {
  verb: string;
  object?: string | undefined;
  kind?: ObjectKind | undefined;
  /** Words after the object: "(+3 −1)", "(rule no-push)", "in brain/". */
  tail?: string | undefined;
}

/** The longest command head a row shows. */
export const COMMAND_HEAD = 120;

function str(payload: Payload, key: string): string | undefined {
  const value = payload[key];
  return typeof value === "string" && value !== "" ? value : undefined;
}

function num(payload: Payload, key: string): number | undefined {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/** The phrase as one line of text (search, minimap labels, live digest, tests). */
export function phraseText(phrase: Phrase): string {
  const object =
    phrase.object === undefined
      ? ""
      : phrase.kind === "command"
        ? ` \`${phrase.object}\``
        : ` ${phrase.object}`;
  return `${phrase.verb}${object}${phrase.tail ? ` ${phrase.tail}` : ""}`;
}

/** A skill as the slash command people type: `/feature`, with a `plugin:` prefix dropped. */
export function skillName(raw: string): string {
  const name = raw.includes(":") ? raw.slice(raw.lastIndexOf(":") + 1) : raw;
  return name.startsWith("/") ? name : `/${name}`;
}

/** The first line of a command, at most COMMAND_HEAD characters. */
export function commandHead(command: string): string {
  const line = command.split("\n")[0] ?? "";
  return line.length > COMMAND_HEAD ? `${line.slice(0, COMMAND_HEAD - 1)}…` : line;
}

function lineDelta(payload: Payload): string | undefined {
  const plus = num(payload, "lines_added");
  const minus = num(payload, "lines_removed");
  const parts = [
    plus === undefined ? null : `+${fmtInt(plus)}`,
    minus === undefined ? null : `−${fmtInt(minus)}`,
  ].filter((part): part is string => part !== null);
  return parts.length === 0 ? undefined : `(${parts.join(" ")})`;
}

function onPath(verb: string, payload: Payload, fallback: string): Phrase {
  const path = str(payload, "path");
  return path
    ? { verb, object: path, kind: "code", tail: lineDelta(payload) }
    : { verb: fallback, tail: lineDelta(payload) };
}

/** The phrase of a tool call, from its kept keys (`collector/tool_metadata.py`). */
export function toolPhrase(tool: string, payload: Payload): Phrase {
  if (tool.startsWith("mcp__")) {
    const server = str(payload, "mcp_server") ?? "mcp";
    const name = str(payload, "mcp_tool") ?? tool;
    return { verb: "Called", object: `${server}.${name}`, kind: "code" };
  }
  switch (tool) {
    case "Read":
      return onPath("Read", payload, "Read a file");
    case "Edit":
    case "MultiEdit":
      return onPath("Edited", payload, "Edited a file");
    case "Write":
      return onPath("Wrote", payload, "Wrote a file");
    case "NotebookEdit":
      return onPath("Edited notebook", payload, "Edited a notebook");
    case "Bash": {
      const command = str(payload, "command");
      return command
        ? { verb: "Ran", object: commandHead(command), kind: "command" }
        : { verb: "Ran a command" };
    }
    case "Grep": {
      const pattern = str(payload, "pattern");
      const path = str(payload, "path");
      if (!pattern)
        return path ? { verb: "Searched in", object: path, kind: "code" } : { verb: "Searched" };
      return {
        verb: "Searched for",
        object: `"${pattern}"`,
        kind: "code",
        tail: path ? `in ${path}` : undefined,
      };
    }
    case "Glob": {
      const pattern = str(payload, "pattern");
      const path = str(payload, "path");
      if (!pattern)
        return path
          ? { verb: "Listed files in", object: path, kind: "code" }
          : { verb: "Listed files" };
      return {
        verb: "Listed files matching",
        object: `"${pattern}"`,
        kind: "code",
        tail: path ? `in ${path}` : undefined,
      };
    }
    case "WebFetch": {
      const url = str(payload, "url");
      return url ? { verb: "Fetched", object: url, kind: "code" } : { verb: "Fetched a web page" };
    }
    case "WebSearch":
      return { verb: "Searched the web" };
    case "Skill": {
      const skill = str(payload, "skill");
      return skill
        ? { verb: "Ran skill", object: skillName(skill), kind: "text" }
        : { verb: "Ran a skill" };
    }
    case "Agent":
    case "Task": {
      const type = str(payload, "subagent_type") ?? "subagent";
      const description = str(payload, "description");
      return {
        verb: "Started subagent",
        object: description ? `${type}: ${description}` : type,
        kind: "text",
      };
    }
    case "SendMessage": {
      const to = str(payload, "to");
      return to
        ? { verb: "Sent a message to", object: to, kind: "text" }
        : { verb: "Sent a message" };
    }
    case "SubagentHandback":
      return { verb: "Handed back to the main agent" };
    case "TodoWrite":
      return { verb: "Updated the to-do list" };
    case "ToolSearch":
      return { verb: "Looked up tools" };
    case "AskUserQuestion":
      return { verb: "Asked you a question" };
    case "ExitPlanMode":
      return { verb: "Proposed a plan" };
    default: {
      const path = str(payload, "path");
      return { verb: `Used ${tool}`, object: path, kind: path ? "code" : undefined };
    }
  }
}

const size = (chars: number | null) =>
  chars === null
    ? "(size unknown)"
    : `(${fmtInt(chars)} ${chars === 1 ? "character" : "characters"})`;

/** A prompt, an agent message or a reasoning summary: described by size, never by content. */
export function contentPhrase(
  role: "prompt" | "message" | "reasoning",
  chars: number | null,
  slashCommand: string | undefined,
): Phrase {
  if (role === "reasoning") return { verb: "Recorded a reasoning summary", tail: size(chars) };
  if (role === "message") return { verb: "Replied", tail: size(chars) };
  return slashCommand
    ? { verb: "Prompted", object: slashCommand, kind: "text", tail: size(chars) }
    : { verb: "Sent a prompt", tail: size(chars) };
}

/** A gate, waiting or decided: "Requested gate plan", "Gate check failed". */
export function gatePhrase(name: string, result: string | undefined): Phrase {
  return result
    ? { verb: "Gate", object: name, kind: "text", tail: result }
    : { verb: "Requested gate", object: name, kind: "text" };
}

/** A guard denial: "Guard blocked Bash (rule no-push-main)". */
export function guardDeniedPhrase(tool: string | undefined, rule: string | undefined): Phrase {
  return {
    verb: tool ? `Guard blocked ${tool}` : "Guard blocked a tool call",
    tail: rule ? `(rule ${rule})` : undefined,
  };
}

const LEARNING_VERB: Record<string, string> = {
  "learning.proposed": "Proposed a learning",
  "learning.accepted": "Accepted a learning",
  "learning.rejected": "Rejected a learning",
};

/** A learning event: "Proposed a learning: <its title>". */
export function learningPhrase(type: string, text: string | undefined): Phrase {
  const verb = LEARNING_VERB[type] ?? "Proposed a learning";
  return text ? { verb: `${verb}:`, object: text, kind: "text" } : { verb };
}

/** A session start or resume: "Started the session in agent-hub · claude-model-a". */
export function sessionStartPhrase(
  segment: number,
  where: string,
  model: string | undefined,
): Phrase {
  return {
    verb:
      segment > 1
        ? `Resumed the session (segment ${String(segment)}) in`
        : "Started the session in",
    object: where,
    kind: "text",
    tail: model ? `· ${model}` : undefined,
  };
}

/** A session end: "Ended the session: done · clear". */
export function sessionEndPhrase(outcome: string, reason: string | undefined): Phrase {
  return {
    verb: "Ended the session:",
    object: [outcome, reason].filter(Boolean).join(" · "),
    kind: "text",
  };
}

/** A guard ask: "Guard asked you to approve Edit of docs/adr/0009.md". */
export function guardAskPhrase(path: string | undefined): Phrase {
  return path
    ? { verb: "Guard asked you to approve a change to", object: path, kind: "code" }
    : { verb: "Guard asked you to approve a tool call" };
}

/** A blocked Stop: "Blocked the stop: `make check-fast` failing". */
export function stopBlockedPhrase(command: string | undefined): Phrase {
  return command
    ? { verb: "Blocked the stop:", object: commandHead(command), kind: "command", tail: "failing" }
    : { verb: "Blocked the stop: the stop gate failed" };
}

/** A workflow step or run boundary: "Started step implement", "Finished step implement: ok". */
export function stepPhrase(
  type: "step.start" | "step.end" | "run.end",
  name: string,
  status: string | undefined,
): Phrase {
  if (type === "run.end") return { verb: "Run ended:", object: status ?? "ended", kind: "text" };
  if (type === "step.start") return { verb: "Started step", object: name, kind: "text" };
  return {
    verb: "Finished step",
    object: name,
    kind: "text",
    tail: status ? `· ${status}` : undefined,
  };
}
