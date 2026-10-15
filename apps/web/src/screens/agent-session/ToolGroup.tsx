import { memo, useId, useState } from "react";

import { Icon } from "../../components";
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

/** Consecutive tool calls with no text between them, as one disclosure (AC-234.24): open while
 * a call waits for you or failed, collapsed otherwise; the reader's toggle holds until that
 * changes. */
function ToolGroupView({ items, tools, calls, onAnswerPermission }: ToolGroupProps) {
  const listId = useId();
  const needsYou = items.some((item) => {
    const state = toolState(item.tool, item.request);
    return state === "waiting" || state === "error";
  });
  const [toggled, setToggled] = useState<{ when: boolean; open: boolean } | null>(null);
  const open = toggled !== null && toggled.when === needsYou ? toggled.open : needsYou;
  return (
    <div className="as-tool-group">
      <button
        type="button"
        className="as-tool-group-head"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => {
          setToggled({ when: needsYou, open: !open });
        }}
      >
        <Icon name={open ? "chevron-down" : "chevron-right"} size="sm" />
        <Icon name="layers" size="sm" />
        {groupSummary(items.map((item) => item.tool))}
      </button>
      {open && (
        <ul id={listId} className="as-tool-group-list">
          {items.map(({ tool, request }) => (
            <li key={tool.id}>
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
