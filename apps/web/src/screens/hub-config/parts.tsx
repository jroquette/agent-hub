import { createContext, useContext } from "react";
import type { ReactNode } from "react";

import type { components } from "../../api/schema";
import { Button, DerivedLabel, Icon, IconButton, Tooltip } from "../../components";
import type { IconName } from "../../components";
import { useDiscuss } from "../../shell/discuss";
import type { DiscussReference } from "../../shell/discuss";

/* The Hub config screen's shared pieces: its sections, rows and who-set-it labels. */

type SourcedValue = components["schemas"]["SourcedValue"];
type PatternView = components["schemas"]["PatternView"];
export type Source = SourcedValue["source"] | PatternView["source"];

/**
 * Who set a value, in the words a person uses. "Set by you" and "Set by the team" are the two
 * files someone edits; "Built-in" is agent-hub's own value when neither file sets one.
 */
export const SOURCE_LOOK: Record<Source, { label: string; icon: IconName }> = {
  team: { label: "Set by the team", icon: "users" },
  project: { label: "Set by the team", icon: "users" },
  repo: { label: "Set by the team", icon: "users" },
  local: { label: "Set by you", icon: "laptop" },
  git: { label: "From your git config", icon: "git-commit-horizontal" },
  derived: { label: "From your email", icon: "circle-dashed" },
  default: { label: "Built-in", icon: "box" },
  commit_title: { label: "Built-in", icon: "box" },
};

/** What a source's tooltip says: the file and key, or why agent-hub picked the value. */
function sourceTip(source: Source, where: string): string {
  if (source === "default" || source === "commit_title")
    return `agent-hub's own value: neither hub.json nor your hub.local.json sets this (${where}).`;
  if (source === "repo") return `Set by the team for this repo only: ${where}`;
  return where;
}

/** Who set a value: an icon and plain words, its tooltip naming the file and key. */
export function ConfigSource({ source, where }: { source: Source; where: string }) {
  if (source === "derived") return <DerivedLabel how={where}>From your email</DerivedLabel>;
  const look = SOURCE_LOOK[source];
  return (
    <Tooltip label={sourceTip(source, where)}>
      {/* Focusable so keyboard users reach the file and key in its tooltip. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <span className="ah-config-source" data-source={source} tabIndex={0}>
        <Icon name={look.icon} />
        {look.label}
      </span>
    </Tooltip>
  );
}

/** Why Claude cannot be asked here (session control locked or off), else null. */
export const AskBlocked = createContext<string | null>(null);

export interface RowAsk {
  label: string;
  pressed: boolean;
  onClick: () => void;
}

export interface RowProps {
  label: string;
  /** Shown in place of ``label`` (a name with a badge); ``label`` stays the accessible text,
   * case kept, since it is then a name. */
  labelNode?: ReactNode;
  /** More actions after Edit, such as a labelled Remove. */
  actions?: ReactNode;
  children: ReactNode;
  source?: ReactNode;
  /** Point Claude at this row: shown on hover and focus, and kept once attached. */
  ask?: RowAsk | undefined;
  /** Open this row's field in my settings: only for what hub.local.json may set. */
  onEdit?: (() => void) | undefined;
  editLabel?: string;
}

export function ConfigRow({
  label,
  labelNode,
  children,
  source,
  ask,
  onEdit,
  editLabel = "Change for me",
  actions,
}: RowProps) {
  const blocked = useContext(AskBlocked);
  return (
    <div className="ah-config-row">
      <div className="ah-config-label">{labelNode ?? label}</div>
      <div className="ah-config-value">{children}</div>
      <div className="ah-config-src">{source}</div>
      <div className="ah-config-act">
        {ask && (
          <span className="ah-config-ask" data-pressed={ask.pressed || undefined}>
            {ask.pressed && <span className="ah-small ah-muted">In next message</span>}
            <IconButton
              icon={ask.pressed ? "check" : "message-square"}
              size="sm"
              variant="ghost"
              disabled={blocked !== null}
              label={
                blocked !== null
                  ? `${ask.label} (unavailable: ${blocked})`
                  : ask.pressed
                    ? `${ask.label}: in next message`
                    : ask.label
              }
              onClick={ask.onClick}
            />
          </span>
        )}
        {onEdit && (
          <Button
            size="sm"
            variant="ghost"
            icon="pencil"
            aria-label={`${editLabel}: ${labelNode ? label : label.toLowerCase()}`}
            onClick={onEdit}
          >
            {editLabel}
          </Button>
        )}
        {actions}
      </div>
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <code className="ah-mono ah-config-code">{children}</code>;
}

export function NoneText({ children = "None" }: { children?: ReactNode }) {
  return <span className="ah-muted">{children}</span>;
}

export interface SectionProps {
  id: string;
  title: string;
  /** What the section's Ask button names: "Ask Claude to change <askName>". */
  askName: string;
  purpose: string;
  icon: IconName;
  onAsk?: (() => void) | undefined;
  children: ReactNode;
}

export function Section({ id, title, askName, purpose, icon, onAsk, children }: SectionProps) {
  const blocked = useContext(AskBlocked);
  return (
    <section className="ah-card ah-config-section" aria-labelledby={`${id}-title`} id={id}>
      <header className="ah-config-section-head">
        <div className="ah-config-section-title">
          <h2 className="ah-h3" id={`${id}-title`}>
            <Icon name={icon} /> {title}
          </h2>
          <p className="ah-small ah-muted">{purpose}</p>
        </div>
        {onAsk && (
          <Tooltip label={blocked ?? undefined}>
            <Button size="sm" icon="message-square" disabled={blocked !== null} onClick={onAsk}>
              Ask Claude to change {askName}
            </Button>
          </Tooltip>
        )}
      </header>
      {children}
    </section>
  );
}

export function useAttach() {
  const { references, addReference } = useDiscuss();
  const attached = new Set(references.map((r) => r.id));
  return {
    attach: (ref: DiscussReference) => {
      addReference(ref);
    },
    isAttached: (id: string) => attached.has(`config:${id}`),
  };
}
