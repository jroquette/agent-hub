import { memo, useId, useState } from "react";

import { Icon } from "../../components";
import { cx } from "../../lib/cx";
import { RequestCard, type AnswerPermission } from "./PermissionCard";
import { ToolCallCard } from "./ToolCallCard";
import { toolState, type PermissionView, type ToolView, type TranscriptState } from "./transcript";

/** One call of a group and the permission asked for it, when one was. */
export interface GroupItem {
  tool: ToolView;
  request?: PermissionView | undefined;
}

export interface ToolGroupProps {
  items: readonly GroupItem[];
  tools: TranscriptState["tools"];
  calls: TranscriptState["children"];
  onAnswerPermission: AnswerPermission;
}

/** "Explored · 3 Read, 2 Grep": the calls counted by name, first seen first. */
export function groupSummary(tools: readonly ToolView[]): string {
  const counts = new Map<string, number>();
  for (const tool of tools) counts.set(tool.name, (counts.get(tool.name) ?? 0) + 1);
  const parts = Array.from(counts, ([name, count]) => `${String(count)} ${name}`);
  return `Explored · ${parts.join(", ")}`;
}

/** Consecutive tool calls with no text between them (AC-234.24). One call shows as its card; two
 * or more as one disclosure that opens when a call waits for you or fails, starts collapsed
 * otherwise, and only the reader closes. A run keeps this one component as it grows, so its
 * cards keep their state and focus; a call the reader worked with keeps its run open. */
function ToolGroupView({ items, tools, calls, onAnswerPermission }: ToolGroupProps) {
  const listId = useId();
  const many = items.length > 1;
  const needsYou = items.some((item) => {
    const state = toolState(item.tool, item.request);
    return state === "waiting" || state === "error";
  });
  const [open, setOpen] = useState(needsYou);
  const [neededYou, setNeededYou] = useState(needsYou);
  if (neededYou !== needsYou) {
    setNeededYou(needsYou);
    if (needsYou) setOpen(true);
  }
  const shown = open || !many;
  return (
    <div
      className={cx("as-tool-run", many && "as-tool-group")}
      onFocus={
        many
          ? undefined
          : () => {
              setOpen(true);
            }
      }
    >
      {many && (
        <button
          type="button"
          className="as-tool-group-head"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          onClick={() => {
            setOpen(!open);
          }}
        >
          <Icon name={open ? "chevron-down" : "chevron-right"} size="sm" />
          <Icon name="layers" size="sm" />
          {groupSummary(items.map((item) => item.tool))}
        </button>
      )}
      {shown && (
        <ul
          id={listId}
          className={cx("as-tool-run-list", many && "as-tool-group-list")}
          role={many ? undefined : "presentation"}
        >
          {items.map(({ tool, request }) => (
            <li key={tool.id} role={many ? undefined : "presentation"}>
              <ToolCallCard tool={tool} tools={tools} calls={calls} request={request} />
              {request && <RequestCard request={request} onAnswerPermission={onAnswerPermission} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Equal when every call and request is the same object: a delta elsewhere skips the group. */
function sameProps(a: ToolGroupProps, b: ToolGroupProps): boolean {
  return (
    a.tools === b.tools &&
    a.calls === b.calls &&
    a.onAnswerPermission === b.onAnswerPermission &&
    a.items.length === b.items.length &&
    a.items.every((item, i) => {
      const other = b.items[i];
      return item.tool === other?.tool && item.request === other.request;
    })
  );
}

export const ToolGroup = memo(ToolGroupView, sameProps);
