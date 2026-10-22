import { useCallback, useEffect, useLayoutEffect, type RefObject } from "react";

/**
 * A textarea that grows with its text up to `share` of the viewport, then scrolls: one layout
 * read per fit, and again on a window resize (it moves the cap).
 */
export function useAutoGrow(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
  share = 0.4,
): void {
  const fit = useCallback(() => {
    const element = ref.current;
    if (!element) return;
    const max = Math.floor(window.innerHeight * share);
    element.style.height = "auto";
    const content = element.scrollHeight;
    element.style.height = `${String(Math.min(content, max))}px`;
    element.style.overflowY = content > max ? "auto" : "hidden";
  }, [ref, share]);
  useLayoutEffect(fit, [fit, value]);
  useEffect(() => {
    window.addEventListener("resize", fit);
    return () => {
      window.removeEventListener("resize", fit);
    };
  }, [fit]);
}
