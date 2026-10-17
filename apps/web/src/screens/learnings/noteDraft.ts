import { useCallback, useState } from "react";

import { readStored, removeStored, writeStored } from "../../lib/storage";

/** An edit of a learning's note body, kept in this browser until the accept sends it. */
export interface NoteDraft {
  /** The edited body (the text after the note's frontmatter). */
  body: string;
  /** The body as the hub had it when the edit started: when the hub's differs, the draft is stale. */
  base: string;
}

const PREFIX = "ah.learning.draft.";

function parse(raw: string | null): NoteDraft | null {
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (
      typeof value === "object" &&
      value !== null &&
      "body" in value &&
      "base" in value &&
      typeof value.body === "string" &&
      typeof value.base === "string"
    ) {
      return { body: value.body, base: value.base };
    }
  } catch {
    // A draft that does not parse is dropped.
  }
  return null;
}

export function readNoteDraft(id: string): NoteDraft | null {
  return parse(readStored(PREFIX + id));
}

/** The learning's draft and how to change or drop it; one draft per learning id. */
export function useNoteDraft(id: string) {
  const [state, setState] = useState(() => ({ id, draft: readNoteDraft(id) }));
  const current = state.id === id ? state.draft : readNoteDraft(id);
  if (state.id !== id) setState({ id, draft: current });
  const save = useCallback(
    (draft: NoteDraft) => {
      writeStored(PREFIX + id, JSON.stringify(draft));
      setState({ id, draft });
    },
    [id],
  );
  const discard = useCallback(() => {
    removeStored(PREFIX + id);
    setState({ id, draft: null });
  }, [id]);
  return { draft: current, save, discard };
}
