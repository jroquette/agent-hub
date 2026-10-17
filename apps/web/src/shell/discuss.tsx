import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Button } from "../components/core";

/**
 * What a screen offers to discuss with Claude: the artifact on screen (a spec, a plan, a skill…).
 * `key` is stable per artifact, so reopening the panel on it brings its conversation back.
 */
export interface DiscussTarget {
  key: string;
  project: string;
  /** What kind of artifact it is, as the owner reads it: "Spec", "Workflow", "Skill"… */
  kind: string;
  /** Its name: the feature slug, the workflow id, the skill name. */
  title: string;
  /** Where it lives, relative to the hub folder, when it is one file. */
  path?: string | null | undefined;
  /** Extra context for Claude: sibling files, what the screen shows, what it may change. */
  brief?: string | undefined;
  /**
   * Open the panel when the screen shows this target, whatever the owner's last choice elsewhere.
   * Closing it there is remembered for this target until the page reloads.
   */
  openOnArrive?: boolean | undefined;
  /**
   * A whole screen rather than one artifact (the shell's fallback when a screen registers nothing):
   * the first message carries what the screen shows, its text and a screenshot.
   */
  screen?: boolean | undefined;
  /**
   * Ready-made first messages for this kind of artifact ("Is this worth keeping?"): one click
   * starts the conversation with that message.
   */
  starters?: readonly DiscussStarter[] | undefined;
}

/** A one-click first message: `label` is what the button reads, `message` what Claude gets. */
export interface DiscussStarter {
  label: string;
  message: string;
}

/**
 * A precise part of the target the owner points Claude at: one acceptance criterion, a passage of
 * the spec, a row of the plan. It rides on the next message of the target's conversation.
 */
export interface DiscussReference {
  /** Stable per part (`ac:AC-7`, `quote:<text>`): pointing at it twice keeps one chip. */
  id: string;
  /** What the chip reads: "AC-7", "Spec excerpt". */
  label: string;
  /** The file the part comes from, relative to the hub folder, when known. */
  source?: string | null | undefined;
  /** The part itself, as the screen shows it. */
  quote: string;
}

interface DiscussState {
  /** What the panel talks about: the screen's own target, else the screen itself. */
  target: DiscussTarget | null;
  setTarget: (target: DiscussTarget | null) => void;
  /** The shell names the screen itself, used while the screen registers no target. */
  setFallback: (target: DiscussTarget | null) => void;
  open: boolean;
  setOpen: (open: boolean) => void;
  /** The references waiting for the next message on the current target. */
  references: readonly DiscussReference[];
  /** Points Claude at a part of the current target: adds the chip and opens the panel. */
  addReference: (reference: DiscussReference) => void;
  removeReference: (id: string) => void;
  clearReferences: () => void;
}

const DiscussContext = createContext<DiscussState>({
  target: null,
  setTarget: () => undefined,
  setFallback: () => undefined,
  open: false,
  setOpen: () => undefined,
  references: [],
  addReference: () => undefined,
  removeReference: () => undefined,
  clearReferences: () => undefined,
});

const OPEN_KEY = "ah.discuss.open";
const NO_REFERENCES: readonly DiscussReference[] = [];

/**
 * Holds the screen's discuss target and whether the panel is open: the owner's choice (kept across
 * reloads), unless the target asks to open on arrival and was not closed there.
 */
export function DiscussProvider({ children }: { children: ReactNode }) {
  const [registered, setTarget] = useState<DiscussTarget | null>(null);
  const [fallback, setFallback] = useState<DiscussTarget | null>(null);
  const target = registered ?? fallback;
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(() => new Set());
  const [chosenOpen, setChosenOpen] = useState(() => {
    try {
      return window.localStorage.getItem(OPEN_KEY) === "1";
    } catch {
      return false;
    }
  });
  // References belong to the target they were taken from: another screen does not inherit them.
  const [pointed, setPointed] = useState<{ key: string; items: DiscussReference[] } | null>(null);
  const arriving = target?.openOnArrive === true && !dismissed.has(target.key);
  const open = arriving || chosenOpen;
  const choose = useCallback(
    (next: boolean) => {
      setChosenOpen(next);
      if (target?.openOnArrive) {
        const key = target.key;
        setDismissed((current) => {
          const updated = new Set(current);
          if (next) updated.delete(key);
          else updated.add(key);
          return updated;
        });
      }
      try {
        window.localStorage.setItem(OPEN_KEY, next ? "1" : "0");
      } catch {
        // A browser without storage only forgets the panel on reload.
      }
    },
    [target],
  );
  const references = target && pointed?.key === target.key ? pointed.items : NO_REFERENCES;
  const value = useMemo<DiscussState>(
    () => ({
      target,
      setTarget,
      setFallback,
      open,
      setOpen: choose,
      references,
      addReference: (reference) => {
        if (!target) return;
        const kept = references.filter((r) => r.id !== reference.id);
        setPointed({ key: target.key, items: [...kept, reference] });
        if (!open) choose(true);
      },
      removeReference: (id) => {
        if (!target) return;
        setPointed({ key: target.key, items: references.filter((r) => r.id !== id) });
      },
      clearReferences: () => {
        setPointed(null);
      },
    }),
    [target, open, choose, references],
  );
  return <DiscussContext.Provider value={value}>{children}</DiscussContext.Provider>;
}

export function useDiscuss(): DiscussState {
  return useContext(DiscussContext);
}

/**
 * A screen names what can be discussed while it is shown; the target is dropped when it unmounts.
 * Only the fields are compared, so an inline object does not re-register on every render.
 */
export function useDiscussTarget(target: DiscussTarget | null) {
  const { setTarget } = useDiscuss();
  const signature = target ? JSON.stringify(target) : null;
  useEffect(() => {
    setTarget(signature ? (JSON.parse(signature) as DiscussTarget) : null);
    return () => {
      setTarget(null);
    };
  }, [signature, setTarget]);
}

/** An in-page "Discuss with Claude" button: opens the side panel on what the screen registered. */
export function DiscussButton({ label = "Discuss with Claude" }: { label?: string }) {
  const { open, setOpen } = useDiscuss();
  return (
    <Button
      size="sm"
      variant={open ? "primary" : "default"}
      icon="message-square"
      aria-pressed={open}
      onClick={() => {
        setOpen(!open);
      }}
    >
      {label}
    </Button>
  );
}

/** The first message of a conversation: the artifact, the ground rules, then the owner's words. */
export function discussPrompt(target: DiscussTarget, message: string): string {
  const lines = [
    `I am the owner of the agent-hub project "${target.project}", writing from the agent-hub web app.`,
    `I want to discuss this ${target.kind}: ${target.title}.`,
  ];
  if (target.path) lines.push(`It is the file \`${target.path}\` in this folder. Read it first.`);
  if (target.brief) lines.push(target.brief);
  lines.push(
    "Discuss it with me. Change files only when I ask for a change; keep the file's format and frontmatter, and add a changelog line when the file has a changelog. Answer briefly.",
    "",
    "My message:",
    message,
  );
  return lines.join("\n");
}

/**
 * The owner's message with the parts they pointed at, quoted ahead of it so Claude answers about
 * exactly those: each reference names its file and quotes the part.
 */
export function referencedMessage(
  references: readonly DiscussReference[],
  message: string,
): string {
  if (references.length === 0) return message;
  const quoted = references.map((reference) => {
    const head = reference.source
      ? `${reference.label} (from \`${reference.source}\`):`
      : `${reference.label}:`;
    const body = reference.quote
      .trim()
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n");
    return `${head}\n${body}`;
  });
  return [
    references.length === 1 ? "About this part:" : "About these parts:",
    "",
    quoted.join("\n\n"),
    "",
    message,
  ].join("\n");
}
