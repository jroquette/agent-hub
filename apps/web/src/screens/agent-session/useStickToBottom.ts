import { useCallback, useEffect, useRef, useState } from "react";

/** Within this many pixels of the bottom the transcript counts as at the bottom (AC-234.18). */
export const STICK_THRESHOLD_PX = 24;

export interface StickToBottom {
  /** The reader is at the bottom: new content keeps the transcript there. */
  atBottom: boolean;
  /** Scrolls to the bottom and follows again; smooth only when asked and motion is allowed. */
  pin: (behavior?: "smooth" | "instant") => void;
  /** Stops following, as when the chat opens on an earlier entry. */
  release: () => void;
}

/** The reader asked the system for less motion. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const distanceToBottom = (element: HTMLElement) =>
  element.scrollHeight - element.scrollTop - element.clientHeight;

/**
 * Keeps a scroll container at its bottom while the reader is there (AC-234.17, .18): "at the
 * bottom" comes from the scroll position (within `threshold`), a scroll up detaches, a
 * ResizeObserver re-pins when the content or the container changes size, and the position is
 * written at most once per animation frame. Takes the element (from a callback ref), so it
 * attaches when the scroller mounts after a loading state. It starts at the bottom.
 */
export function useStickToBottom(
  scroller: HTMLElement | null,
  threshold = STICK_THRESHOLD_PX,
): StickToBottom {
  const [atBottom, setAtBottom] = useState(true);
  const following = useRef(true);
  const frame = useRef<number | null>(null);
  const lastTop = useRef(0);

  const follow = useCallback((value: boolean) => {
    following.current = value;
    setAtBottom(value);
  }, []);

  const scheduleWrite = useCallback(() => {
    if (!scroller || frame.current !== null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      if (!following.current) return;
      scroller.scrollTop = scroller.scrollHeight;
      lastTop.current = scroller.scrollTop;
    });
  }, [scroller]);

  useEffect(() => {
    if (!scroller) return undefined;
    lastTop.current = scroller.scrollTop;
    const onScroll = () => {
      const top = scroller.scrollTop;
      if (distanceToBottom(scroller) <= threshold) follow(true);
      // Only a move up detaches: a smooth scroll down passes through "far" on its way.
      else if (top < lastTop.current) follow(false);
      lastTop.current = top;
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    const observer =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(() => {
            if (following.current) scheduleWrite();
          })
        : null;
    if (observer) {
      observer.observe(scroller);
      for (const child of Array.from(scroller.children)) observer.observe(child);
    }
    if (following.current) scheduleWrite();
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      observer?.disconnect();
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
    };
  }, [scroller, threshold, follow, scheduleWrite]);

  const pin = useCallback(
    (behavior: "smooth" | "instant" = "instant") => {
      follow(true);
      if (!scroller) return;
      if (
        behavior === "smooth" &&
        !prefersReducedMotion() &&
        typeof scroller.scrollTo === "function"
      )
        scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
      else scheduleWrite();
    },
    [follow, scroller, scheduleWrite],
  );

  const release = useCallback(() => {
    follow(false);
  }, [follow]);

  return { atBottom, pin, release };
}
