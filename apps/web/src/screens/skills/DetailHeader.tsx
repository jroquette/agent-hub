/* The header card of an item's detail (D4, AC-164.17): what it is, how to use it, and its state at
 * a glance. Where it lives and its other facts are in the About rail beside the text. */
import "./SkillDetail.css";

import type { ReactNode } from "react";

import { Icon } from "../../components";
import type { components } from "../../api/schema";
import { AnchorLink } from "./BodyView";
import {
  HookStateTags,
  Invocation,
  KIND_ICON,
  KIND_NAME,
  ModeTag,
  OriginBadge,
  UsageLine,
} from "./SkillCard";

type SkillDetail = components["schemas"]["SkillDetail"];
type HookFacts = components["schemas"]["HookFacts"];

/** When each Claude Code hook event fires, worded to follow "Runs …". */
const HOOK_WHEN: Readonly<Record<string, string>> = {
  SessionStart: "when a session starts",
  SessionEnd: "when a session ends",
  UserPromptSubmit: "when you send a prompt",
  Notification: "when Claude Code sends a notification",
  Stop: "when the main agent ends its turn",
  SubagentStart: "when a subagent starts",
  SubagentStop: "when a subagent ends",
  PreCompact: "before the context is compacted",
};
/** The tool events, worded to take the matcher: "before every Bash tool call". */
const HOOK_TOOL_WHEN: Readonly<Record<string, string>> = {
  PreToolUse: "before",
  PostToolUse: "after",
  PostToolUseFailure: "after a failed",
};

function toolList(matcher: string): string {
  const tools = matcher.split("|").map((tool) => tool.trim());
  if (tools.length === 1) return tools[0] ?? matcher;
  return `${tools.slice(0, -1).join(", ")} or ${tools.at(-1) ?? ""}`;
}

/** A hook in a plain sentence: "Runs before every Bash tool call.". */
export function hookSentence(hook: Pick<HookFacts, "event" | "matcher">): string {
  const tool = HOOK_TOOL_WHEN[hook.event];
  if (tool !== undefined) {
    const which = hook.matcher ? `${toolList(hook.matcher)} tool call` : "tool call";
    return tool === "after a failed"
      ? `Runs after every failed ${which}.`
      : `Runs ${tool} every ${which}.`;
  }
  const when = HOOK_WHEN[hook.event];
  return when ? `Runs ${when}.` : `Runs on ${hook.event}.`;
}

/** "Pass the tracker issue id." for a single `<…>` placeholder, else "Arguments: …". */
export function argumentLine(hint: string): string {
  const single = /^<([^<>]+)>$/.exec(hint.trim());
  return single?.[1] ? `Pass the ${single[1]}.` : `Arguments: ${hint}`;
}

function HealthChip({ count, warnings }: { count: number; warnings: number }) {
  if (count === 0) {
    return (
      <span className="ah-skill-tag">
        <Icon name="circle-check" size="sm" />
        No diagnostics
      </span>
    );
  }
  return (
    <AnchorLink
      anchor="skill-diagnostics"
      className="ah-skill-tag ah-skill-health"
      onGo={(anchor) => {
        const heading = document.getElementById(anchor);
        heading?.scrollIntoView({ block: "start" });
        heading?.focus();
      }}
    >
      <Icon name={warnings > 0 ? "triangle-alert" : "info"} size="sm" />
      {count} {count === 1 ? "diagnostic" : "diagnostics"}
    </AnchorLink>
  );
}

export interface DetailHeaderProps {
  detail: SkillDetail;
  /** The current time in ms, for "last used … ago". */
  now: number;
  usageDays: number;
  /** The view's actions, at the top right (Discuss, Edit with Claude). */
  action?: ReactNode;
}

/** The header card; it holds the page's `<h1>` (the item's name). */
export function DetailHeader({ detail, now, usageDays, action }: DetailHeaderProps) {
  const description = detail.description_full ?? detail.description;
  const warnings = detail.diagnostics.filter((d) => d.severity === "warning").length;
  return (
    <header className="ah-card ah-skill-header">
      <div className="ah-skill-header-top">
        <div className="ah-skill-header-name">
          <span className="ah-skill-kind">
            <Icon name={KIND_ICON[detail.kind]} size="sm" />
            {KIND_NAME[detail.kind]}
          </span>
          <h1 className="ah-h1 ah-skill-title">{detail.name}</h1>
        </div>
        {action && <div className="ah-skill-header-actions">{action}</div>}
      </div>
      {detail.hook ? (
        <p className="ah-skill-lede">{hookSentence(detail.hook)}</p>
      ) : (
        <p className="ah-skill-lede">{description ?? "No description."}</p>
      )}
      {detail.when_to_use && (
        <p className="ah-skill-when">
          <span className="ah-caption">When to use</span> {detail.when_to_use}
        </p>
      )}
      {detail.invocation && (
        <div className="ah-skill-howto">
          <Invocation text={detail.invocation} />
          {detail.argument_hint && (
            <span className="ah-small ah-muted">{argumentLine(detail.argument_hint)}</span>
          )}
        </div>
      )}
      {detail.kind === "agent" && (
        <p className="ah-skill-subagent">
          The main session delegates to it as subagent <code>{detail.name}</code>.
        </p>
      )}
      <div className="ah-skill-card-foot">
        {detail.mode && <ModeTag mode={detail.mode} />}
        <OriginBadge origin={detail.origin} />
        {detail.kind === "hook" && <HookStateTags active={detail.active} state={detail.state} />}
        {detail.usage && (
          <span className="ah-skill-meta">
            <Icon name="activity" size="sm" />
            <UsageLine usage={detail.usage} days={usageDays} now={now} />
          </span>
        )}
        <HealthChip count={detail.diagnostics.length} warnings={warnings} />
      </div>
    </header>
  );
}
