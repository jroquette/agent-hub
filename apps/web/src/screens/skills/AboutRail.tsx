/* The About rail of an item's detail (D4): where the file lives, what it runs with, what it costs
 * and what it is linked to, beside the text so the facts stay in view while reading. */
import "./SkillDetail.css";

import { CopyButton, IdChip, PathText } from "../../components";
import type { components } from "../../api/schema";
import { ContextCost } from "./ContextCost";
import { frontmatterText } from "./FrontmatterTable";
import { HookFactsList } from "./HookDetail";
import { RailFact } from "./RailFact";
import { Relations } from "./Relations";
import { KIND_NAME } from "./SkillCard";

type SkillDetail = components["schemas"]["SkillDetail"];

/** Keys the header or the rail shows by name; any other known key is listed under its own key. */
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
const PATH_CHARS = 34;

function Chips({ names }: { names: readonly string[] }) {
  return (
    <ul className="ah-skill-fm-list">
      {names.map((name) => (
        <li key={name} className="ah-fm-chip">
          {name}
        </li>
      ))}
    </ul>
  );
}

function PathFact({ term, path }: { term: string; path: string }) {
  return (
    <RailFact term={term} mono>
      <span className="ah-skill-path">
        <PathText path={path} max={PATH_CHARS} dimDir />
        <CopyButton text={path} label={`Copy path ${path}`} />
      </span>
    </RailFact>
  );
}

export interface AboutRailProps {
  project: string;
  detail: SkillDetail;
}

export function AboutRail({ project, detail }: AboutRailProps) {
  const others = detail.frontmatter.filter((pair) => pair.known && !SHOWN_KEYS.has(pair.key));
  const sha = detail.lock?.sha256;
  const commands = detail.structure?.commands ?? [];
  return (
    <aside className="ah-skill-rail" aria-labelledby="skill-about">
      <h2 id="skill-about" className="ah-sr">
        About this {KIND_NAME[detail.kind].toLowerCase()}
      </h2>
      <dl className="ah-skill-rail-section ah-skill-rail-facts">
        {detail.hook && <HookFactsList hook={detail.hook} />}
        {detail.model && (
          <RailFact term="Model" mono>
            {detail.model}
          </RailFact>
        )}
        {detail.tools.length > 0 && (
          <RailFact term="Tools">
            <Chips names={detail.tools} />
          </RailFact>
        )}
        {detail.allowed_tools.length > 0 && (
          <RailFact term="Allowed tools">
            <Chips names={detail.allowed_tools} />
          </RailFact>
        )}
        <PathFact term={detail.hook ? "Source file" : "Source"} path={detail.source_path} />
        {detail.linked_from.map((path) => (
          <PathFact key={path} term="Linked from" path={path} />
        ))}
        {detail.lock && (
          <RailFact term="hub.lock">
            <span className="ah-skill-path">
              {detail.lock.ownership === "managed" ? "Managed by hub sync" : detail.lock.ownership}
              {sha && <IdChip id={sha} short={sha.slice(0, 12)} kind="sha256" />}
            </span>
          </RailFact>
        )}
        {others.map((pair) => (
          <RailFact key={pair.key} term={pair.key} mono>
            {frontmatterText(pair.value)}
          </RailFact>
        ))}
      </dl>
      {detail.kind !== "hook" && (
        <ContextCost cost={detail.context_cost ?? null} kind={detail.kind} />
      )}
      {detail.kind !== "hook" && (
        <Relations project={project} uses={detail.uses} usedBy={detail.used_by} />
      )}
      {commands.length > 0 && (
        <section className="ah-skill-rail-section" aria-labelledby="skill-commands">
          <h3 id="skill-commands" className="ah-caption" style={{ margin: "0 0 6px" }}>
            Commands it runs
          </h3>
          <ul className="ah-skill-rail-commands">
            {commands.map((command) => (
              <li key={command}>
                <code title={command}>{command}</code>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}
