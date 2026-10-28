import { useEffect, useRef, type RefObject } from "react";

import { Icon } from "./Icon";
import { Kbd } from "./core";
import { typingIn } from "../shell/goSequence";

export interface SearchFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** The input's accessible name. */
  label: string;
  placeholder: string;
  /** The screen's class for the box (`ft-search`, `sl-search`), beside `ah-search`. */
  className: string;
  /** The screen's class for the `/` hint; without it, the field has no keys of its own. */
  kbdClassName?: string;
  /** The input, for a screen that moves focus to it (after a delete, say). */
  inputRef?: RefObject<HTMLInputElement>;
}

/**
 * A list's search box (the Features, Tickets, Sessions and Scenarios toolbars). With a
 * `kbdClassName`, `/` focuses it (spec 01 keyboard map) and Esc in it clears, then leaves.
 */
export function SearchField({
  value,
  onChange,
  label,
  placeholder,
  className,
  kbdClassName,
  inputRef,
}: SearchFieldProps) {
  const own = useRef<HTMLInputElement>(null);
  const ref = inputRef ?? own;
  const keys = kbdClassName !== undefined;
  useEffect(() => {
    if (!keys) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey || typingIn(event.target)) return;
      if (ref.current === null) return;
      event.preventDefault();
      ref.current.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [keys, ref]);
  return (
    <div className={`ah-search ${className}`}>
      <Icon name="search" size="sm" />
      <input
        ref={ref}
        type="search"
        className="ah-input"
        aria-label={label}
        placeholder={placeholder}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        onKeyDown={
          keys
            ? (event) => {
                if (event.key !== "Escape") return;
                if (value) onChange("");
                else event.currentTarget.blur();
              }
            : undefined
        }
      />
      {keys && !value && (
        <span className={kbdClassName} aria-hidden="true">
          <Kbd>/</Kbd>
        </span>
      )}
    </div>
  );
}
