import { useCallback, useEffect, useRef, useState } from "react";

import { readStored, removeStored, writeStored } from "../../lib/storage";
import type { Answers, OpenQuestion } from "./openQuestions";

/** Drafts above this many bytes of UTF-8 are not kept (as the chat composer's). */
export const ANSWERS_MAX_BYTES = 64 * 1024;
const SAVE_AFTER_MS = 500;

export const answersKey = (project: string, slug: string, record: string) =>
  `ah.approve.answers.${project}:${slug}:${record}`;

/** What is kept per question: the answer and the title it answered. */
type Stored = Record<string, { title: string; text: string }>;

function readAnswers(key: string): Stored {
  try {
    const value: unknown = JSON.parse(readStored(key) ?? "{}");
    if (typeof value !== "object" || value === null) return {};
    const kept: Stored = {};
    for (const [id, entry] of Object.entries(value as Record<string, unknown>)) {
      const { title, text } = (entry ?? {}) as { title?: unknown; text?: unknown };
      if (typeof title === "string" && typeof text === "string") kept[id] = { title, text };
    }
    return kept;
  } catch {
    return {};
  }
}

function saveAnswers(key: string, stored: Stored) {
  const kept = Object.fromEntries(Object.entries(stored).filter(([, entry]) => entry.text.trim()));
  const json = JSON.stringify(kept);
  if (Object.keys(kept).length === 0 || new TextEncoder().encode(json).length > ANSWERS_MAX_BYTES) {
    removeStored(key);
  } else {
    writeStored(key, json);
  }
}

export interface AnswerDrafts {
  answers: Answers;
  set: (question: OpenQuestion, text: string) => void;
  /** Ids whose kept answer was written for a question whose title changed since. */
  changed: ReadonlySet<string>;
  /** The approval was accepted: forget the drafts. */
  clear: () => void;
}

/**
 * The owner's answers to a record's open questions, kept in this browser per feature record:
 * saved 500 ms after the last change (or when the page is hidden), restored on open, cleared once
 * the approval is accepted. Storage that is off or full only loses the drafts.
 */
export function useAnswerDrafts(
  project: string,
  slug: string,
  record: string,
  questions: readonly OpenQuestion[],
): AnswerDrafts {
  const key = answersKey(project, slug, record);
  const [stored, setStored] = useState<Stored>(() => readAnswers(key));
  const latest = useRef(stored);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flush = useCallback(() => {
    if (timer.current === null) return;
    clearTimeout(timer.current);
    timer.current = null;
    saveAnswers(key, latest.current);
  }, [key]);

  useEffect(() => {
    const onHide = () => {
      flush();
    };
    window.addEventListener("pagehide", onHide);
    document.addEventListener("visibilitychange", onHide);
    return () => {
      window.removeEventListener("pagehide", onHide);
      document.removeEventListener("visibilitychange", onHide);
      flush();
    };
  }, [flush]);

  const set = useCallback(
    (question: OpenQuestion, text: string) => {
      const next = { ...latest.current, [question.id]: { title: question.title, text } };
      latest.current = next;
      setStored(next);
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(flush, SAVE_AFTER_MS);
    },
    [flush],
  );

  const clear = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    latest.current = {};
    setStored({});
    removeStored(key);
  }, [key]);

  const answers: Record<string, string> = {};
  const changed = new Set<string>();
  for (const question of questions) {
    const entry = stored[question.id];
    if (!entry) continue;
    answers[question.id] = entry.text;
    if (entry.text.trim() && entry.title !== question.title) changed.add(question.id);
  }
  return { answers, set, changed, clear };
}
