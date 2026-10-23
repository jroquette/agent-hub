import { useEffect, useState } from "react";

/** A tablet, 768–1279 px (31-responsive.md): best effort, read only. */
export const TABLET = "(min-width: 768px) and (max-width: 1279px)";

/** Whether `query` matches now, following its changes; false where matchMedia is missing. */
export function useMediaQuery(query: string): boolean {
  const read = () => typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [matches, setMatches] = useState(read);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const list = window.matchMedia(query);
    const onChange = () => {
      setMatches(list.matches);
    };
    onChange();
    list.addEventListener("change", onChange);
    return () => {
      list.removeEventListener("change", onChange);
    };
  }, [query]);
  return matches;
}
