/* Driven sessions as rows of the sections (AC-234.8): the fields an AgentSession has, blanks for the rest (Q4). */
import type { ReactNode } from "react";

import { Money, type DataTableColumn } from "../../components";
import { fmtClock } from "../../lib/format";
import { AgentStatusBadge } from "../agent-session/SessionStatus";
import { modeLabel } from "../agent-session/model";
import { agentSessionHref } from "./control";
import type { AgentSession, Session } from "./queries";
import { isDriven, type SectionRow } from "./sections";

type Tz = "local" | "utc";

/** Marks a session hub web drives: its row opens the chat. */
export function ChatBadge() {
  return (
    <span className="ah-badge" title="Started from hub web: opens the chat">
      Chat
    </span>
  );
}

function when(iso: string, tz: Tz): ReactNode {
  return (
    <span className="ah-mono" style={{ fontSize: 12 }} title={iso}>
      {new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}{" "}
      {fmtClock(iso, tz)}
    </span>
  );
}

const ONE_LINE = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } as const;

/** The cells a driven row fills, by column id; every other column stays blank. */
const DRIVEN_CELLS: Record<string, (a: AgentSession, tz: Tz) => ReactNode> = {
  started: (a, tz) => when(a.created_at, tz),
  // One line, like an observed row's name: Claude Code's title once it has written one, the
  // first prompt until then; the whole of it shows on hover.
  session: (a) => {
    const title = a.title ?? "Untitled session";
    const detail = [a.workdir_label, modeLabel(a.mode), a.model].filter(Boolean).join(" · ");
    return (
      <span className="ah-row" style={{ gap: 6, minWidth: 0 }}>
        <span className="ah-stack" style={{ gap: 0, minWidth: 0 }}>
          <span style={{ ...ONE_LINE, fontWeight: 500 }} title={title}>
            {title}
          </span>
          <span className="ah-mono ah-small ah-subtle" style={ONE_LINE} title={detail}>
            {detail}
          </span>
        </span>
        <ChatBadge />
      </span>
    );
  },
  project: (a) => a.project,
  repo: (a) => <span className="ah-mono ah-small">{a.workdir_label}</span>,
  outcome: (a) => <AgentStatusBadge status={a.status} endReason={a.end_reason} />,
  cost: (a) => (a.cost_usd ? <Money value={a.cost_usd} precise /> : "—"),
  model: (a) => <span className="ah-mono ah-small">{a.model ?? "—"}</span>,
  last: (a, tz) => when(a.updated_at, tz),
};

/**
 * `column` for section rows: a driven row gets its own cell; a twin gets the Chat badge by its name.
 * The session cell ends with `action(row)`, such as Resume (AC-234.15).
 */
export function withDriven(
  column: DataTableColumn<Session>,
  tz: Tz,
  action: (row: SectionRow) => ReactNode = () => null,
): DataTableColumn<SectionRow> {
  const render = column.render;
  const driven = DRIVEN_CELLS[column.id];
  const cell = (row: SectionRow): ReactNode => {
    if (isDriven(row)) return driven ? driven(row, tz) : "";
    const own = render?.(row);
    return column.id === "session" && row.agent_session_id ? (
      <span className="ah-row" style={{ gap: 6 }}>
        {own}
        <ChatBadge />
      </span>
    ) : (
      own
    );
  };
  if (column.id !== "session") return { ...column, render: cell };
  return {
    ...column,
    render: (row) => {
      const extra = action(row);
      return extra ? (
        <span className="ah-row" style={{ gap: 8 }}>
          {cell(row)}
          {extra}
        </span>
      ) : (
        cell(row)
      );
    },
  };
}

/** Where a row opens: a driven session or a twin opens its chat, others their detail. */
export function rowHref(row: SectionRow): string {
  if (isDriven(row)) return agentSessionHref(row.id);
  return row.agent_session_id
    ? agentSessionHref(row.agent_session_id)
    : `/sessions/${encodeURIComponent(row.id)}`;
}
