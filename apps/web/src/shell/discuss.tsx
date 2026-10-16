import { createContext, useContext, useEffect, useMemo, useState } from "react";
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
}

interface DiscussState {
  target: DiscussTarget | null;
  setTarget: (target: DiscussTarget | null) => void;
  open: boolean;
  setOpen: (open: boolean) => void;
}

const DiscussContext = createContext<DiscussState>({
  target: null,
  setTarget: () => undefined,
  open: false,
  setOpen: () => undefined,
});

const OPEN_KEY = "ah.discuss.open";

/**
 * Holds the screen's discuss target and whether the panel is open: the owner's choice (kept across
 * reloads), unless the target asks to open on arrival and was not closed there.
 */
export function DiscussProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<DiscussTarget | null>(null);
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(() => new Set());
  const [chosenOpen, setChosenOpen] = useState(() => {
    try {
      return window.localStorage.getItem(OPEN_KEY) === "1";
    } catch {
      return false;
    }
  });
  const arriving = target?.openOnArrive === true && !dismissed.has(target.key);
  const open = arriving || chosenOpen;
  const value = useMemo<DiscussState>(
    () => ({
      target,
      setTarget,
      open,
      setOpen: (next) => {
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
    }),
    [target, open],
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
