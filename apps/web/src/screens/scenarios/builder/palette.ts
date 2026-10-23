import type { IconName } from "../../../components";
import { kindLook } from "./FlowCanvas";
import { newBlock, without, type BlockKind, type BuilderDocument } from "./model";
import { freshKey, type Item } from "./program";

/* The blocks a scenario is built from, as the palette and the insert menu offer them: each with
 * the verb it reads as, a hint, its icon and tint, and how to make a fresh one. */

export interface PaletteEntry {
  key: string;
  label: string;
  hint: string;
  icon: IconName;
  tint: string;
  make: (taken: BuilderDocument) => Item;
}

export function blockItem(document: BuilderDocument, kind: BlockKind, action?: string): Item {
  const node = newBlock(document, kind, action);
  if (kind === "loop_group") return { kind: "repeat", node: without(node, "nodes"), body: [] };
  return { kind: "block", node };
}

export const CATEGORIES: readonly { title: string; entries: readonly PaletteEntry[] }[] = [
  {
    title: "Do",
    entries: [
      {
        key: "action",
        label: "run an action",
        hint: "A script, once",
        icon: "circle-play",
        tint: kindLook("action").tint,
        make: (d) => blockItem(d, "action"),
      },
      {
        key: "include",
        label: "run a scenario",
        hint: "Reuse another one",
        icon: "layers",
        tint: kindLook("include").tint,
        make: (d) => blockItem(d, "include"),
      },
    ],
  },
  {
    title: "Check",
    entries: [
      {
        key: "expect",
        label: "wait until …",
        hint: "Read until a state holds",
        icon: "timer",
        tint: kindLook("expect").tint,
        make: (d) => blockItem(d, "expect"),
      },
      {
        key: "wait",
        label: "wait 30s",
        hint: "A set time",
        icon: "hourglass",
        tint: kindLook("wait").tint,
        make: (d) => blockItem(d, "wait"),
      },
    ],
  },
  {
    title: "Control",
    entries: [
      {
        key: "repeat",
        label: "repeat until …",
        hint: "Rounds until done",
        icon: "refresh-cw",
        tint: kindLook("loop_group").tint,
        make: (d) => blockItem(d, "loop_group"),
      },
      {
        key: "if",
        label: "if … else",
        hint: "Take one path",
        icon: "split",
        tint: "var(--ev-decision)",
        make: () => ({ kind: "if", key: freshKey("if"), condition: "", then: [], otherwise: [] }),
      },
      {
        key: "parallel",
        label: "at the same time",
        hint: "Paths side by side",
        icon: "git-branch",
        tint: "var(--ev-reasoning)",
        make: () => ({ kind: "parallel", key: freshKey("together"), lanes: [[], []] }),
      },
    ],
  },
  {
    title: "You",
    entries: [
      {
        key: "approval",
        label: "ask me to …",
        hint: "A step by hand",
        icon: "stamp",
        tint: kindLook("approval").tint,
        make: (d) => blockItem(d, "approval"),
      },
    ],
  },
];
