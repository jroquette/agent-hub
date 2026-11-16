import { useCallback, useEffect, useRef, useState } from "react";

import { readStored, removeStored, writeStored } from "../../lib/storage";

/** A draft above this many bytes of UTF-8 is not kept (plan "Inputs, bounds and budget"). */
export const DRAFT_MAX_BYTES = 64 * 1024;
const SAVE_AFTER_MS = 500;

export const draftKey = (id: string) => `ah.chat.draft.${id}`;

function readDraft(id: string | null): string {
  if (id === null) return "";
  try {
    const value: unknown = JSON.parse(readStored(draftKey(id)) ?? '""');
    return typeof value === "string" ? value : "";
  } catch {
    return "";
  }
}

function saveDraft(id: string, text: string) {
  if (text === "" || new TextEncoder().encode(text).length > DRAFT_MAX_BYTES) {
    removeStored(draftKey(id));
  } else {
    writeStored(draftKey(id), JSON.stringify(text));
  }
}

export interface Draft {
  text: string;
  setText: (text: string) => void;
  /** The send of `message` was accepted: clear the draft unless it changed since. */
  accepted: (message: string) => void;
}

/**
 * The composer's text, kept in this browser per session (AC-234.26): saved 500 ms after the last
 * change (or when the chat closes or the page is hidden), restored on open, cleared once its
 * send is accepted. Storage that is off or full only loses the draft.
 */
export function useDraft(id: string | null): Draft {
  const [text, setText] = useState(() => readDraft(id));
  const latest = useRef(text);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flush = useCallback(() => {
    if (timer.current === null || id === null) return;
    clearTimeout(timer.current);
    timer.current = null;
    saveDraft(id, latest.current);
  }, [id]);

  const change = useCallback(
    (next: string) => {
      latest.current = next;
      setText(next);
      if (id === null) return;
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(flush, SAVE_AFTER_MS);
    },
    [flush, id],
  );

  const accepted = useCallback(
    (message: string) => {
      if (latest.current !== message) return;
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = null;
      latest.current = "";
      setText("");
      if (id !== null) removeStored(draftKey(id));
    },
    [id],
  );

  useEffect(() => {
    // A reload or a closed tab never unmounts the chat: save the pending draft as the page goes.
    const onHidden = () => {
      if (document.visibilityState === "hidden") flush();
    };
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", onHidden);
    return () => {
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", onHidden);
      flush();
    };
  }, [flush]);

  return { text, setText: change, accepted };
}
