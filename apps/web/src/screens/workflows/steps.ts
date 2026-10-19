import type { IconName } from "../../components";

/* The workflow step types in plain words: what the catalog, the detail and the legend say. */

export type StepKind = "agent" | "command" | "approval" | "wait" | "repeat" | "include" | "stop";

interface KindInfo {
  icon: IconName;
  one: string;
  many: string;
  /** One line for the legend and the step list. */
  hint: string;
}

export const STEP_KINDS: Readonly<Record<StepKind, KindInfo>> = {
  agent: {
    icon: "message-square",
    one: "AI agent",
    many: "AI agents",
    hint: "A Claude session with a prompt: it reads the code, changes it and reports back.",
  },
  command: {
    icon: "terminal",
    one: "command",
    many: "commands",
    hint: "A program or script, such as the tests or git: it passes when it exits 0.",
  },
  approval: {
    icon: "stamp",
    one: "approval by you",
    many: "approvals by you",
    hint: "The run pauses until you decide in Approvals.",
  },
  wait: {
    icon: "hourglass",
    one: "wait",
    many: "waits",
    hint: "The run pauses for a time, a date or your answer.",
  },
  repeat: {
    icon: "refresh-cw",
    one: "repeat",
    many: "repeats",
    hint: "Runs a group of steps again, round after round, until they pass.",
  },
  include: {
    icon: "layers",
    one: "sub-workflow",
    many: "sub-workflows",
    hint: "Another workflow's steps, reused here.",
  },
  stop: {
    icon: "octagon-x",
    one: "stop",
    many: "stops",
    hint: "Ends the run on purpose.",
  },
};

const KIND_OF: Readonly<Record<string, StepKind>> = {
  agent: "agent",
  loop: "agent",
  shell: "command",
  script: "command",
  approval: "approval",
  wait: "wait",
  loop_group: "repeat",
  include: "include",
  halt: "stop",
};

/** The plain kind of an engine node type (`shell` and `script` are both a command). */
export function stepKind(type: string): StepKind {
  return KIND_OF[type] ?? "command";
}

/** The kinds a workflow holds and how many of each, in legend order. */
export function kindCounts(types: Record<string, number>): [StepKind, number][] {
  const counts = new Map<StepKind, number>();
  for (const [type, n] of Object.entries(types)) {
    const kind = stepKind(type);
    counts.set(kind, (counts.get(kind) ?? 0) + n);
  }
  return (Object.keys(STEP_KINDS) as StepKind[])
    .filter((kind) => counts.has(kind))
    .map((kind) => [kind, counts.get(kind) ?? 0]);
}

/** "3 AI agents", "1 command". */
export function countLabel(kind: StepKind, n: number): string {
  const info = STEP_KINDS[kind];
  if (kind === "repeat") return "repeats in rounds";
  return `${String(n)} ${n === 1 ? info.one : info.many}`;
}
