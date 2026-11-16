import { Fragment, useState } from "react";

import {
  EVENT_CATEGORIES,
  Icon,
  StatusBadge,
  TOOL_ICON,
  type EventCategory,
} from "../../components";
import { ProblemBadge } from "./ProblemsPanel";
import { MAIN_AGENT, WORKFLOW_RUN, YOU, subagentActor, type RowActor } from "./timeline";

const ACTORS: [RowActor, string][] = [
  [MAIN_AGENT, "The agent you started in the terminal."],
  [
    subagentActor("<type>"),
    "A subagent the main agent started with the Agent tool; its rows sit under that call.",
  ],
  [YOU, "Your prompts."],
  [WORKFLOW_RUN, "Steps of a hub workflow run."],
];

const CATEGORY_TEXT: Record<EventCategory, string> = {
  prompt: "Your prompt",
  message: "Agent message (size only)",
  reasoning: "Reasoning summary (size only)",
  tool: "Tool call",
  gate: "Gate",
  decision: "Decision",
  learning: "Learning",
  lifecycle: "Session start or end",
  error: "Failed call",
  guard: "Guard event",
};

const TOOL_TEXT: Record<string, string> = {
  Read: "Read a file",
  Edit: "Edited a file",
  Write: "Wrote a file",
  Bash: "Ran a command",
  Grep: "Searched file contents",
  Glob: "Listed files",
  Agent: "Started a subagent",
  WebFetch: "Fetched a web page",
  MCP: "Called an MCP tool",
  Skill: "Ran a skill",
};

/** What the timeline's actor badges, status badges and icons mean (AC-201.19). */
export function Legend() {
  // The body renders only while open: the trace re-renders often and the legend never changes.
  const [open, setOpen] = useState(false);
  return (
    <details
      className="sd-legend"
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
      }}
    >
      <summary>Legend</summary>
      {open && (
        <div className="sd-legend-body">
          <section aria-labelledby="sd-legend-actors">
            <h3 id="sd-legend-actors" className="ah-overline">
              Who acted
            </h3>
            <dl>
              {ACTORS.map(([actor, text]) => (
                <Fragment key={actor.label}>
                  <dt>
                    <span className="ah-actor" data-actor={actor.kind}>
                      {actor.label}
                    </span>
                  </dt>
                  <dd>{text}</dd>
                </Fragment>
              ))}
            </dl>
          </section>
          <section aria-labelledby="sd-legend-status">
            <h3 id="sd-legend-status" className="ah-overline">
              Status
            </h3>
            <dl>
              <dt>
                <ProblemBadge problem={{ kind: "command_exit", resolution: "needs_you" }} />
              </dt>
              <dd>Nothing fixed it: you need to act.</dd>
              <dt>
                <ProblemBadge problem={{ kind: "command_exit", resolution: "open" }} />
              </dt>
              <dd>It just happened; the agent is still working.</dd>
              <dt>
                <ProblemBadge problem={{ kind: "command_exit", resolution: "recovered" }} />
              </dt>
              <dd>The agent retried it or carried on: nothing to do.</dd>
              <dt>
                <ProblemBadge problem={{ kind: "interrupted", resolution: "by_you" }} />
              </dt>
              <dd>You stopped it or declined it.</dd>
              <dt>
                <StatusBadge status="failed" label="Failed" />
              </dt>
              <dd>A failed call not yet classified.</dd>
              <dt>
                <StatusBadge status="running" />
              </dt>
              <dd>The call has no result yet.</dd>
              <dt>
                <span className="ah-exit ah-exit-bad">exit 2</span>
              </dt>
              <dd>The command&apos;s exit code; 0 is success.</dd>
            </dl>
          </section>
          <section aria-labelledby="sd-legend-icons">
            <h3 id="sd-legend-icons" className="ah-overline">
              Icons
            </h3>
            <ul className="sd-legend-icons">
              {(Object.keys(CATEGORY_TEXT) as EventCategory[]).map((cat) => (
                <li key={cat}>
                  <Icon name={EVENT_CATEGORIES[cat].icon} size="sm" />
                  {CATEGORY_TEXT[cat]}
                </li>
              ))}
              {Object.entries(TOOL_TEXT).map(([tool, text]) => {
                const icon = TOOL_ICON[tool];
                return icon ? (
                  <li key={tool}>
                    <Icon name={icon} size="sm" />
                    {text}
                  </li>
                ) : null;
              })}
            </ul>
          </section>
        </div>
      )}
    </details>
  );
}
