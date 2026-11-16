import { useEffect, type RefObject } from "react";

import { typingIn } from "../shell/goSequence";

const NAV = "[data-nav-row]";

/** `j` / `k` move across the `[data-nav-row]` rows under `root`; `o` opens the focused one. */
export function useRowKeys(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (typingIn(event.target)) return;
      const el = root.current;
      if (!el) return;
      const items = [...el.querySelectorAll<HTMLElement>(NAV)];
      const active = document.activeElement;
      const at = items.findIndex((item) => item === active || item.contains(active));
      if (event.key === "j" || event.key === "k") {
        if (items.length === 0) return;
        event.preventDefault();
        const step = event.key === "j" ? 1 : -1;
        const next =
          at < 0
            ? step > 0
              ? 0
              : items.length - 1
            : Math.min(items.length - 1, Math.max(0, at + step));
        items[next]?.focus();
        items[next]?.scrollIntoView({ block: "nearest" });
      } else if (event.key === "o" && at >= 0) {
        event.preventDefault();
        items[at]?.click();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [root]);
}
