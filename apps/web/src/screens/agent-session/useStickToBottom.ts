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

/** Keys that scroll a container up; pressed in the transcript they mean "stop following". */
const UP_KEYS = new Set(["PageUp", "ArrowUp", "Home"]);

/** The event comes from a text field or a select, whose keys are its own. */
export const isEditable = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

const distanceToBottom = (element: HTMLElement) =>
  element.scrollHeight - element.scrollTop - element.clientHeight;

/**
 * Keeps a scroll container at its bottom while the reader is there (AC-234.17, .18): "at the
 * bottom" comes from the scroll position (within `threshold`), a scroll up detaches, and so
 * does an explicit move up (an upward wheel or swipe, PageUp/ArrowUp/Home) at once, even within
 * the threshold, until the reader scrolls down again; a
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
  const scheduled = useRef(false);
  const lastTop = useRef(0);
  /** The reader asked to go up: the threshold no longer re-attaches until they scroll down. */
  const goingUp = useRef(false);

  const follow = useCallback((value: boolean) => {
    following.current = value;
    setAtBottom(value);
  }, []);

  const scheduleWrite = useCallback(() => {
    if (!scroller || scheduled.current) return;
    scheduled.current = true;
    frame.current = requestAnimationFrame(() => {
      scheduled.current = false;
      if (!following.current) return;
      scroller.scrollTop = scroller.scrollHeight;
      lastTop.current = scroller.scrollTop;
    });
  }, [scroller]);

  useEffect(() => {
    if (!scroller) return undefined;
    lastTop.current = scroller.scrollTop;
    const detach = () => {
      goingUp.current = true;
      follow(false);
    };
    const onScroll = () => {
      const top = scroller.scrollTop;
      if (top > lastTop.current) goingUp.current = false;
      if (!goingUp.current && distanceToBottom(scroller) <= threshold) follow(true);
      // Only a move up detaches: a smooth scroll down passes through "far" on its way.
      else if (top < lastTop.current) follow(false);
      lastTop.current = top;
    };
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY < 0) detach();
    };
    let touchY: number | null = null;
    const onTouchStart = (event: TouchEvent) => {
      touchY = event.touches[0]?.clientY ?? null;
    };
    const onTouchMove = (event: TouchEvent) => {
      const y = event.touches[0]?.clientY;
      if (y === undefined) return;
      // A finger moving down scrolls the content up.
      if (touchY !== null && y > touchY) detach();
      touchY = y;
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (UP_KEYS.has(event.key) && !isEditable(event.target)) detach();
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    scroller.addEventListener("wheel", onWheel, { passive: true });
    scroller.addEventListener("touchstart", onTouchStart, { passive: true });
    scroller.addEventListener("touchmove", onTouchMove, { passive: true });
    scroller.addEventListener("keydown", onKeyDown);
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
      scroller.removeEventListener("wheel", onWheel);
      scroller.removeEventListener("touchstart", onTouchStart);
      scroller.removeEventListener("touchmove", onTouchMove);
      scroller.removeEventListener("keydown", onKeyDown);
      observer?.disconnect();
      if (scheduled.current && frame.current !== null) cancelAnimationFrame(frame.current);
      scheduled.current = false;
    };
  }, [scroller, threshold, follow, scheduleWrite]);

  const pin = useCallback(
    (behavior: "smooth" | "instant" = "instant") => {
      goingUp.current = false;
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
