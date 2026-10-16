/* The About card of an item's detail (D4, AC-164.17): what it is, how to invoke it, where it lives. */
import "./SkillDetail.css";

import type { ReactNode } from "react";

import { Icon } from "../../components";
import type { components } from "../../api/schema";
import { frontmatterText } from "./FrontmatterTable";
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

/** Keys the header shows by name; any other known key is listed under its own key. */
const SHOWN_KEYS = new Set([
  "name",
  "description",
  "when_to_use",
  "argument-hint",
  "allowed-tools",
  "tools",
  "model",
  "disable-model-invocation",
  "user-invocable",
]);

function Fact({ term, children, mono }: { term: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="ah-skill-fact">
      <dt>{term}</dt>
      <dd className={mono ? "ah-mono" : undefined}>{children}</dd>
    </div>
  );
}

export interface DetailHeaderProps {
  detail: SkillDetail;
  /** The current time in ms, for "last used … ago". */
  now: number;
  usageDays: number;
  /** An action at the end of the card's foot, such as the Discuss button. */
  action?: ReactNode;
}

/** The header card; it holds the page's `<h1>` (the item's name). */
export function DetailHeader({ detail, now, usageDays, action }: DetailHeaderProps) {
  const others = detail.frontmatter.filter((pair) => pair.known && !SHOWN_KEYS.has(pair.key));
  const description = detail.description_full ?? detail.description;
  const sha = detail.lock?.sha256;
  return (
    <header className="ah-card ah-skill-header">
      <div className="ah-skill-header-top">
        <span className="ah-skill-kind">
          <Icon name={KIND_ICON[detail.kind]} size="sm" />
          {KIND_NAME[detail.kind]}
        </span>
        <h1 className="ah-h1 ah-skill-title">{detail.name}</h1>
      </div>
      {detail.kind !== "hook" && (
        <p className="ah-skill-lede">{description ?? "No description."}</p>
      )}
      {detail.invocation && <Invocation text={detail.invocation} />}
      {detail.kind === "agent" && (
        <p className="ah-skill-subagent">
          subagent <code>{detail.name}</code>
        </p>
      )}
      <div className="ah-skill-card-foot">
        <OriginBadge origin={detail.origin} />
        {detail.mode && <ModeTag mode={detail.mode} />}
        {detail.kind === "hook" && <HookStateTags active={detail.active} state={detail.state} />}
        {detail.usage && (
          <span className="ah-skill-meta">
            <Icon name="activity" size="sm" />
            <UsageLine usage={detail.usage} days={usageDays} now={now} />
          </span>
        )}
        {action && (
          <>
            <span className="ah-grow" />
            {action}
          </>
        )}
      </div>
      <dl className="ah-skill-facts">
        {detail.when_to_use && <Fact term="When to use">{detail.when_to_use}</Fact>}
        <Fact term="Source" mono>
          {detail.source_path}
        </Fact>
        {detail.linked_from.length > 0 && (
          <Fact term="Linked from" mono>
            {detail.linked_from.join(", ")}
          </Fact>
        )}
        {detail.lock && (
          <Fact term="hub.lock">
            <span title={sha ?? undefined}>
              {detail.lock.ownership}
              {sha && (
                <>
                  {" "}
                  · sha256 <span className="ah-mono">{sha.slice(0, 12)}</span>
                </>
              )}
            </span>
          </Fact>
        )}
        {detail.argument_hint && (
          <Fact term="Argument hint" mono>
            {detail.argument_hint}
          </Fact>
        )}
        {detail.allowed_tools.length > 0 && (
          <Fact term="Allowed tools" mono>
            {detail.allowed_tools.join(", ")}
          </Fact>
        )}
        {detail.tools.length > 0 && (
          <Fact term="Tools" mono>
            {detail.tools.join(", ")}
          </Fact>
        )}
        {detail.model && (
          <Fact term="Model" mono>
            {detail.model}
          </Fact>
        )}
        {others.map((pair) => (
          <Fact key={pair.key} term={pair.key} mono>
            {frontmatterText(pair.value)}
          </Fact>
        ))}
      </dl>
    </header>
  );
}
