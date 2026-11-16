/* One card of the Skills catalog (D3, AC-164.15) and the labels the detail page shares with it. */
import "./Skills.css";

import { AppLink, Button, Icon, Time, Tooltip, copyText, useCopied } from "../../components";
import type { IconName } from "../../components";
import type { components } from "../../api/schema";
import { skillRoute } from "./queries";
import {
  MODE_HELP,
  MODE_LABEL,
  ORIGIN_HELP,
  ORIGIN_LABEL,
  type ItemKind,
  type Mode,
  type Origin,
} from "./filters";

type Schemas = components["schemas"];
type CatalogItem = Schemas["CatalogItem"];
type Usage = Schemas["Usage"];

export const KIND_NAME: Record<ItemKind, string> = { skill: "Skill", agent: "Agent", hook: "Hook" };
export const KIND_ICON: Record<ItemKind, IconName> = {
  skill: "book-open",
  agent: "network",
  hook: "cable",
};
const ORIGIN_ICON: Record<Origin, IconName> = {
  managed: "package",
  "project-owned": "folder",
  local: "file",
};
const MODE_ICON: Record<Mode, IconName> = {
  "user-only": "user",
  "model-only": "cpu",
  both: "split",
  neither: "eye-off",
};

/** Who owns the item, as text with an icon; the tooltip says what it means. */
export function OriginBadge({ origin }: { origin: Origin }) {
  return (
    <Tooltip label={ORIGIN_HELP[origin]}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- the tooltip must be reachable */}
      <span className="ah-skill-tag" data-origin={origin} tabIndex={0}>
        <Icon name={ORIGIN_ICON[origin]} size="sm" />
        {ORIGIN_LABEL[origin]}
      </span>
    </Tooltip>
  );
}

/** Who owns the item, as plain text with an icon: on a card, where a tooltip would cost a Tab stop. */
export function OriginText({ origin }: { origin: Origin }) {
  return (
    <span className="ah-skill-meta" data-origin={origin}>
      <Icon name={ORIGIN_ICON[origin]} size="sm" />
      {ORIGIN_LABEL[origin]}
    </span>
  );
}

/** Who can invoke a skill (S5, L2), as text with an icon; derived from the frontmatter. */
export function ModeTag({ mode }: { mode: Mode }) {
  return (
    <Tooltip label={`${MODE_HELP[mode]} Derived from disable-model-invocation and user-invocable.`}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- the tooltip must be reachable */}
      <span className="ah-skill-tag" data-mode={mode} tabIndex={0}>
        <Icon name={MODE_ICON[mode]} size="sm" />
        {MODE_LABEL[mode]}
      </span>
    </Tooltip>
  );
}

/** "3 uses in 30 days (1 by you) · last used 1 h ago", or "Not used in 30 days". */
export function UsageLine({ usage, days, now }: { usage: Usage; days: number; now: number }) {
  const window = `in ${String(days)} days`;
  if (usage.count === 0) return <span>Not used {window}</span>;
  const last = usage.last_used_at;
  return (
    <span>
      {usage.count} {usage.count === 1 ? "use" : "uses"} {window}
      {usage.user_count > 0 && ` (${String(usage.user_count)} by you)`}
      {last && (
        <>
          {" "}
          · last used <Time iso={last} ago={Math.max(0, (now - Date.parse(last)) / 1000)} />
        </>
      )}
    </span>
  );
}

/** A hook's state as text: inactive when its plugin is off, not synced when settings.json lacks it. */
export function HookStateTags({
  active,
  state,
}: {
  active: boolean;
  state?: string | null | undefined;
}) {
  return (
    <>
      {active ? (
        <span className="ah-skill-tag">
          <Icon name="circle-check" size="sm" />
          Active
        </span>
      ) : (
        <span className="ah-skill-tag" title="Its plugin is not enabled in .claude/settings.json">
          <Icon name="circle-pause" size="sm" />
          Inactive
        </span>
      )}
      {state === "not synced" && (
        <span
          className="ah-skill-tag"
          title="In .claude/settings.project.json but not in .claude/settings.json: run hub sync"
        >
          <Icon name="refresh-cw" size="sm" />
          Not synced
        </span>
      )}
    </>
  );
}

/** The invocation line with a Copy button that writes exactly that text. */
export function Invocation({ text }: { text: string }) {
  const [copied, markCopied] = useCopied();
  return (
    <div className="ah-skill-invocation">
      <code title={text}>{text}</code>
      <Button
        size="sm"
        variant="ghost"
        icon={copied ? "check" : "copy"}
        aria-label={copied ? "Copied" : `Copy ${text}`}
        onClick={() => {
          copyText(text);
          markCopied();
        }}
      >
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

export interface SkillCardProps {
  item: CatalogItem;
  project: string;
  /** The current time in ms, for "last used … ago". */
  now: number;
  /** The usage window the catalog counted over. */
  usageDays: number;
  /** False for a card with no page yet (a Studio draft): the name is not a link. */
  linked?: boolean | undefined;
  /** The Studio route of an open edit draft of this item: the card offers to continue it. */
  draftHref?: string | undefined;
}

/** "Continue draft" on an item that has an open edit draft: its Studio page. */
export function ContinueDraft({ href, name }: { href: string; name: string }) {
  return (
    <AppLink
      href={href}
      className="ah-continue-draft"
      aria-label={`Continue your draft of ${name} in the Studio`}
    >
      <Icon name="file-pen" size="sm" />
      Continue draft
    </AppLink>
  );
}

/** A catalog card: rendered as a list item, so place it in a `<ul>`. The kind is said by the
 * tab around it, so the card does not repeat it; only the name link and Copy take a Tab stop. */
export function SkillCard({
  item,
  project,
  now,
  usageDays,
  linked = true,
  draftHref,
}: SkillCardProps) {
  const headingId = `skill-card-${item.id}`;
  const diagnostics = item.diagnostics_count;
  return (
    <li className="ah-skill-card-item">
      <article className="ah-skill-card" aria-labelledby={headingId}>
        <header className="ah-skill-card-head">
          <h3 id={headingId} className="ah-skill-name">
            {linked ? <AppLink href={skillRoute(project, item)}>{item.name}</AppLink> : item.name}
          </h3>
          <span className="ah-grow" />
          {draftHref && <ContinueDraft href={draftHref} name={item.name} />}
        </header>
        {item.kind === "hook" ? (
          <code className="ah-skill-command" title={item.description ?? undefined}>
            {item.description ?? "No command"}
          </code>
        ) : (
          <p className="ah-skill-desc" title={item.description ?? undefined}>
            {item.description ?? "No description."}
          </p>
        )}
        {item.invocation && <Invocation text={item.invocation} />}
        <footer className="ah-skill-card-foot">
          <span className="ah-skill-card-line">
            {item.mode && (
              <span className="ah-skill-meta" data-mode={item.mode}>
                <Icon name={MODE_ICON[item.mode]} size="sm" />
                {MODE_LABEL[item.mode]}
              </span>
            )}
            <OriginText origin={item.origin} />
            {item.kind === "hook" && <HookStateTags active={item.active} state={item.state} />}
          </span>
          {item.usage && (
            <span className="ah-skill-meta">
              <Icon name="activity" size="sm" />
              <UsageLine usage={item.usage} days={usageDays} now={now} />
            </span>
          )}
          {diagnostics > 0 && (
            <span className="ah-skill-meta">
              <Icon name="circle-alert" size="sm" />
              {diagnostics} {diagnostics === 1 ? "diagnostic" : "diagnostics"}
            </span>
          )}
        </footer>
      </article>
    </li>
  );
}
