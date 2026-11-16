import { useState } from "react";

import { IconButton, MenuItem, type IconName } from "../../../components";
import type { ValueSource } from "./model";

/* "Use a value from earlier": a button that opens a menu of what exists upstream of a step
 * (scenario inputs, kept values, typed answers, earlier outputs), grouped by source. */

const GROUP_WORDS: Readonly<Record<ValueSource["group"], string>> = {
  "Scenario inputs": "Scenario inputs",
  "Kept earlier": "Kept values",
  "Typed by you": "Answers",
  "Outputs of earlier blocks": "Earlier outputs",
};

const GROUP_ICON: Readonly<Record<string, IconName>> = {
  "Scenario inputs": "flag",
  "Kept values": "bookmark",
  Answers: "hand",
  "Earlier outputs": "corner-down-right",
};

export function ValuePicker({
  name,
  sources,
  onPick,
  size,
}: {
  /** What the value goes into, for the button's name ("queue", "body · order_id"). */
  name: string;
  sources: readonly ValueSource[];
  onPick: (ref: string) => void;
  size?: "sm" | undefined;
}) {
  const [open, setOpen] = useState(false);
  if (sources.length === 0) return null;
  const groups = [...new Set(sources.map((source) => GROUP_WORDS[source.group]))];
  return (
    <span className="sb-value-pick">
      <IconButton
        icon="corner-down-right"
        size={size}
        label={`Use a value from earlier for ${name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      />
      {open && (
        <div
          className="ah-pop sb-value-menu"
          role="menu"
          tabIndex={-1}
          aria-label={`Values from earlier for ${name}`}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              setOpen(false);
            }
          }}
        >
          {groups.map((group) => (
            <div key={group} role="group" aria-label={group}>
              <div className="sb-menu-group">{group}</div>
              {sources
                .filter((source) => GROUP_WORDS[source.group] === group)
                .map((source) => (
                  <MenuItem
                    key={source.ref}
                    icon={GROUP_ICON[group] ?? "corner-down-right"}
                    hint={<span className="ah-small ah-muted">{source.hint}</span>}
                    onClick={() => {
                      setOpen(false);
                      onPick(source.ref);
                    }}
                  >
                    <span className="ah-mono">{source.label}</span>
                  </MenuItem>
                ))}
            </div>
          ))}
        </div>
      )}
    </span>
  );
}
