import { useEffect, useState } from "react";

import { Button } from "../components";
import { useDiscuss } from "./discuss";

/** The quote a selection becomes: long enough to discuss a section, short enough for a message. */
export const MAX_QUOTE_CHARS = 4000;
const LABEL_CHARS = 40;

interface Selected {
  text: string;
  x: number;
  y: number;
}

/** The text selected inside the page's main column, and where it sits; null for anything else. */
function readSelection(): Selected | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null;
  const text = selection.toString().trim();
  if (text === "") return null;
  const main = document.getElementById("main");
  const node = selection.anchorNode;
  const anchor = node instanceof Element ? node : (node?.parentElement ?? null);
  if (!main || !anchor || !main.contains(anchor) || anchor.closest("input, textarea")) return null;
  const rect = selection.getRangeAt(0).getBoundingClientRect();
  return { text, x: rect.left + rect.width / 2, y: rect.top };
}

/** "“Only the live DataMode selects…”": the chip of a quote reads as its first words. */
export function quoteLabel(text: string): string {
  const line = text.replace(/\s+/g, " ").trim();
  return `“${line.length > LABEL_CHARS ? `${line.slice(0, LABEL_CHARS - 1)}…` : line}”`;
}

/**
 * Select text on a screen that offers something to discuss (a spec section, a plan step, a line of
 * research) and a "Discuss selection" button appears over it: it quotes that text into the
 * target's conversation, so Claude answers about exactly that part.
 */
export function DiscussSelection() {
  const { target, addReference } = useDiscuss();
  const [selected, setSelected] = useState<Selected | null>(null);

  useEffect(() => {
    if (!target) return;
    const read = () => {
      setSelected(readSelection());
    };
    const clearIfGone = () => {
      if (window.getSelection()?.isCollapsed !== false) setSelected(null);
    };
    const hide = () => {
      setSelected(null);
    };
    document.addEventListener("mouseup", read);
    document.addEventListener("keyup", read);
    document.addEventListener("selectionchange", clearIfGone);
    window.addEventListener("scroll", hide, true);
    return () => {
      document.removeEventListener("mouseup", read);
      document.removeEventListener("keyup", read);
      document.removeEventListener("selectionchange", clearIfGone);
      window.removeEventListener("scroll", hide, true);
    };
  }, [target]);

  if (!target || !selected) return null;
  return (
    <div className="ah-discuss-select" style={{ left: selected.x, top: selected.y }}>
      <Button
        size="sm"
        variant="primary"
        icon="message-square"
        // Keep the selection: a press on the button would otherwise collapse it first.
        onMouseDown={(event) => {
          event.preventDefault();
        }}
        onClick={() => {
          const quote = selected.text.slice(0, MAX_QUOTE_CHARS);
          addReference({
            id: `quote:${quote}`,
            label: quoteLabel(quote),
            source: target.path ?? null,
            quote,
          });
          window.getSelection()?.removeAllRanges();
          setSelected(null);
        }}
      >
        Discuss selection
      </Button>
    </div>
  );
}
