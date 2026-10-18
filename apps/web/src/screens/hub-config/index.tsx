import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useParams, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  Banner,
  Button,
  DerivedLabel,
  Icon,
  IconButton,
  ProblemError,
  SegmentedControl,
  Skeleton,
  Toast,
  Tooltip,
} from "../../components";
import type { IconName } from "../../components";
import { useApi } from "../../lib/api";
import { useScope } from "../../lib/scope";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { useDiscuss, useDiscussTarget } from "../../shell/discuss";
import { useAgentCapabilities } from "../sessions-list/queries";
import { sessionControlUnavailable } from "../sessions-list/control";
import type { DiscussReference, DiscussStarter } from "../../shell/discuss";
import { KnowledgeProjectIndex } from "../knowledge-index";
import { LocalSettingsDialog } from "./LocalSettingsDialog";
import "./hub-config.css";

type HubConfigView = components["schemas"]["HubConfigView"];
type SourcedValue = components["schemas"]["SourcedValue"];
type PatternView = components["schemas"]["PatternView"];
type RepoConfigView = components["schemas"]["RepoConfigView"];
type LayeredList = components["schemas"]["LayeredList"];

export type Layer = "effective" | "team" | "local";
type Source = SourcedValue["source"] | PatternView["source"];

/** Where the sidebar's Hub config goes: the project in scope, else a project picker. */
export const CONFIG_PICKER = "/config";
export function configHome(project: string): string {
  return `/projects/${encodeURIComponent(project)}/config`;
}

const SOURCE_LOOK: Record<Source, { label: string; icon: IconName; dashed: boolean }> = {
  team: { label: "Team", icon: "users", dashed: false },
  project: { label: "Team", icon: "users", dashed: false },
  repo: { label: "Team · repo", icon: "book", dashed: false },
  local: { label: "Local", icon: "laptop", dashed: false },
  git: { label: "Git config", icon: "circle-dashed", dashed: true },
  derived: { label: "Derived", icon: "circle-dashed", dashed: true },
  default: { label: "Default", icon: "circle-dashed", dashed: true },
  commit_title: { label: "Default", icon: "circle-dashed", dashed: true },
};

/** Which layer set a value: a chip in words and icon, its tooltip naming the file and key. */
export function ConfigSource({ source, where }: { source: Source; where: string }) {
  const look = SOURCE_LOOK[source];
  return (
    <Tooltip label={where}>
      {/* Focusable so keyboard users reach the file and key in its tooltip. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <span className="ah-config-source" data-dashed={look.dashed || undefined} tabIndex={0}>
        <Icon name={look.icon} />
        {look.label}
      </span>
    </Tooltip>
  );
}

const SAMPLE_HOW =
  "Rendered by agent-hub with sample values: type feat, scope api, summary “add the hub config view”, issue <TEAM>-42, slug hub-config, and your branch prefix.";

function PatternExample({ example }: { example: string | null | undefined }) {
  if (!example) return null;
  return (
    <div className="ah-config-example">
      <Icon name="corner-down-right" />
      <code className="ah-mono">{example}</code>
      <DerivedLabel how={SAMPLE_HOW}>Example</DerivedLabel>
    </div>
  );
}

const SOURCE_WORD: Record<Source, string> = {
  team: "Team",
  project: "Team",
  repo: "Team · repo",
  local: "Local",
  git: "Git config",
  derived: "Derived",
  default: "Default",
  commit_title: "Default",
};

function jsonPathOf(where: string): string {
  const arrow = where.indexOf("→ ");
  return arrow === -1 ? where : where.slice(arrow + 2);
}

function reference(
  id: string,
  label: string,
  value: string,
  source: Source,
  where: string,
  example?: string | null,
): DiscussReference {
  const lines = [
    `${jsonPathOf(where)}: ${JSON.stringify(value)}   (source: ${SOURCE_WORD[source]})`,
  ];
  if (example) lines.push(`example: ${example}`);
  return {
    id: `config:${id}`,
    label,
    source: source === "local" ? "hub.local.json" : "hub.json",
    quote: lines.join("\n"),
  };
}

const BRIEF = [
  "Team values are in hub.json (committed, shared). This developer's values are in hub.local.json at the root of the hub's main checkout (never committed); it accepts only project.branch_prefix, project.author_name, project.author_email, tracker.transport, guard.blocked_words, guard.blocked_words_files, guard.blocked_words_env, environments and repos[].services, and it can only add blocked entries, never relax a guard.",
  "A change to hub.json goes through a hub pull request: work on a new branch from a freshly fetched origin, follow the hub's AGENTS.md for branch, commit and PR rules, keep hub.json plain JSON valid against hub.schema.json, run ./hub doctor (and ./hub sync when rendered files change), show me the diff and ask me before you push or open the PR.",
  "A change to hub.local.json is edited in place, never committed; run ./hub doctor after it.",
  "Conventions (branch, commit_title, pr_title) are set in project.conventions or per repo in repos[].conventions; see docs/design/project-config.md of agent-hub for their placeholders.",
  "Never paste the blocked words into a message, a command or a commit message; refer to them by key.",
].join("\n");

const STARTERS: readonly DiscussStarter[] = [
  {
    label: "Change the commit title pattern",
    message:
      "I want to change the commit title pattern. Show me today's pattern for each repo and an example, then propose the new one before you change anything.",
  },
  {
    label: "Add a blocked word",
    message:
      "I want to add a blocked word. Ask me the word and whether it is for the team (hub.json, through a PR) or only me (hub.local.json).",
  },
  {
    label: "Explain where a value comes from",
    message:
      "Explain which layer sets each value on this screen and what I would change to override it.",
  },
];

/* ---------- Rows ---------- */

/** Why Claude cannot be asked here (session control locked or off), else null. */
const AskBlocked = createContext<string | null>(null);

interface RowProps {
  label: string;
  children: ReactNode;
  source?: ReactNode;
  /** The row's action: point Claude at it, or edit it in the local settings. */
  action?: { label: string; icon: IconName; onClick: () => void; pressed?: boolean } | undefined;
}

function ConfigRow({ label, children, source, action }: RowProps) {
  const blocked = useContext(AskBlocked);
  const askDisabled = action?.icon === "message-square" && blocked !== null;
  return (
    <div className="ah-config-row">
      <div className="ah-config-label">{label}</div>
      <div className="ah-config-value">{children}</div>
      <div className="ah-config-src">{source}</div>
      <div className="ah-config-act">
        {action?.pressed && <span className="ah-small ah-muted">In next message</span>}
        {action && (
          <IconButton
            icon={action.pressed ? "check" : action.icon}
            size="sm"
            variant="ghost"
            disabled={askDisabled}
            label={
              askDisabled
                ? `${action.label} (unavailable: ${blocked})`
                : action.pressed
                  ? `${action.label}: in next message`
                  : action.label
            }
            onClick={action.onClick}
          />
        )}
      </div>
    </div>
  );
}

function Mono({ children }: { children: ReactNode }) {
  return <code className="ah-mono ah-config-code">{children}</code>;
}

function NoneText({ children = "None" }: { children?: ReactNode }) {
  return <span className="ah-muted">{children}</span>;
}

function ListValue({ items }: { items: readonly string[] }) {
  if (items.length === 0) return <NoneText />;
  return (
    <span className="ah-config-list">
      {items.map((item) => (
        <Mono key={item}>{item}</Mono>
      ))}
    </span>
  );
}

/* ---------- Sections ---------- */

interface SectionProps {
  id: string;
  title: string;
  purpose: string;
  icon: IconName;
  onAsk?: (() => void) | undefined;
  children: ReactNode;
}

function Section({ id, title, purpose, icon, onAsk, children }: SectionProps) {
  const blocked = useContext(AskBlocked);
  return (
    <section className="ah-card ah-config-section" aria-labelledby={`${id}-title`} id={id}>
      <header className="ah-config-section-head">
        <div className="ah-stack" style={{ gap: 2 }}>
          <h2 className="ah-h3" id={`${id}-title`}>
            <Icon name={icon} /> {title}
          </h2>
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            {purpose}
          </p>
        </div>
        {onAsk && (
          <Tooltip label={blocked ?? undefined}>
            <Button
              size="sm"
              icon="message-square"
              aria-label={`Ask Claude to change ${title.toLowerCase()}`}
              disabled={blocked !== null}
              onClick={onAsk}
            >
              Ask Claude to change this
            </Button>
          </Tooltip>
        )}
      </header>
      {children}
    </section>
  );
}

/** The value a row shows in a layer, or null when the row has nothing to show there. */
function layerValue(value: SourcedValue, layer: Layer): { text: string | null; note?: string } {
  if (layer === "team") {
    if (value.source === "local")
      return { text: value.team_value ?? null, note: value.value ?? "" };
    if (value.source === "team" || value.source === "default") return { text: value.value ?? null };
    return { text: value.team_value ?? null };
  }
  if (layer === "local") {
    if (value.source === "local") return { text: value.value ?? null };
    return {
      text: null,
      note: value.value ? `${value.value} (${SOURCE_WORD[value.source]})` : "nothing",
    };
  }
  return { text: value.value ?? null };
}

function SourcedCell({ value, layer }: { value: SourcedValue; layer: Layer }) {
  const shown = layerValue(value, layer);
  if (layer === "local" && shown.text === null) {
    return <NoneText>Not set · falls back to {shown.note}</NoneText>;
  }
  return (
    <span className="ah-stack" style={{ gap: 2, alignItems: "flex-start" }}>
      {shown.text ? <Mono>{shown.text}</Mono> : <NoneText>Not set</NoneText>}
      {layer === "team" && shown.note && (
        <span className="ah-small ah-muted">
          Your local value applies: <Mono>{shown.note}</Mono>
        </span>
      )}
    </span>
  );
}

function sourceShown(value: SourcedValue, layer: Layer): ReactNode {
  if (layer === "team") {
    if (value.source === "local" || value.source === "git" || value.source === "derived") {
      return value.team_value ? <ConfigSource source="team" where={value.where} /> : null;
    }
  }
  if (layer === "local" && value.source !== "local") return null;
  return <ConfigSource source={value.source} where={value.where} />;
}

/* ---------- Screen ---------- */

const LAYERS = [
  { id: "effective", label: "Effective" },
  { id: "team", label: "Team (hub.json)" },
  { id: "local", label: "Mine (hub.local.json)" },
];

const SECTIONS = [
  { id: "repositories", label: "Repositories" },
  { id: "who-commits", label: "Who commits" },
  { id: "guard", label: "Guard" },
  { id: "tracker", label: "Tracker" },
  { id: "models", label: "Models" },
];

function useAttach() {
  const { references, addReference } = useDiscuss();
  const attached = new Set(references.map((r) => r.id));
  return {
    attach: (ref: DiscussReference) => {
      addReference(ref);
    },
    isAttached: (id: string) => attached.has(`config:${id}`),
  };
}

function RepoCard({
  repo,
  layer,
  open,
  onToggle,
}: {
  repo: RepoConfigView;
  layer: Layer;
  open: boolean;
  onToggle: (open: boolean) => void;
}) {
  const { attach, isAttached } = useAttach();
  const ask = (
    key: string,
    label: string,
    value: string,
    source: Source,
    where: string,
    example?: string | null,
  ) => {
    const id = `repos[${String(repo.index)}].${key}`;
    return {
      label: `Ask Claude to change ${label.toLowerCase()} of ${repo.dir}`,
      icon: "message-square" as IconName,
      pressed: isAttached(id),
      onClick: () => {
        attach(reference(id, `${label} · ${repo.dir}`, value, source, where, example));
      },
    };
  };
  const pattern = (key: "branch" | "commit_title" | "pr_title", label: string) => {
    const p = repo[key];
    if (layer === "local") return null;
    return (
      <ConfigRow
        label={label}
        source={<ConfigSource source={p.source} where={p.where} />}
        action={ask(`conventions.${key}`, label, p.pattern, p.source, p.where, p.example)}
      >
        {p.source === "commit_title" ? (
          <NoneText>Same as the commit title</NoneText>
        ) : (
          <Mono>{p.pattern}</Mono>
        )}
        <PatternExample example={p.example} />
      </ConfigRow>
    );
  };
  return (
    <details
      className="ah-config-repo"
      open={open}
      onToggle={(event) => {
        onToggle(event.currentTarget.open);
      }}
    >
      <summary>
        <Icon name="chevron-right" className="ah-config-chevron" />
        <Icon name="book" />
        <span className="ah-config-repo-name">{repo.dir}</span>
        <span className="ah-muted ah-small">
          {repo.role} · {repo.github}
        </span>
      </summary>
      {layer === "local" ? (
        <p className="ah-small ah-muted ah-config-note">
          A repo&apos;s branch, conventions and checks are team values: they live in hub.json only.
        </p>
      ) : (
        <div className="ah-config-rows">
          <ConfigRow
            label="Default branch"
            source={
              <ConfigSource source={repo.default_branch.source} where={repo.default_branch.where} />
            }
            action={ask(
              "default_branch",
              "Default branch",
              repo.default_branch.value ?? "",
              repo.default_branch.source,
              repo.default_branch.where,
            )}
          >
            <Mono>{repo.default_branch.value}</Mono>
          </ConfigRow>
          {pattern("branch", "Branch")}
          {pattern("commit_title", "Commit title")}
          {pattern("pr_title", "PR title")}
          <ConfigRow
            label="Fast check"
            source={
              <ConfigSource
                source="team"
                where={`hub.json → repos[${String(repo.index)}].check_fast`}
              />
            }
            action={ask(
              "check_fast",
              "Fast check",
              repo.check_fast ?? "",
              "team",
              `hub.json → repos[${String(repo.index)}].check_fast`,
            )}
          >
            {repo.check_fast ? (
              <span>
                <Mono>{repo.check_fast}</Mono>{" "}
                <span className="ah-small ah-muted">
                  · timeout {String(repo.check_fast_timeout ?? 150)} s
                </span>
              </span>
            ) : (
              <NoneText>None · no Stop gate</NoneText>
            )}
          </ConfigRow>
          <ConfigRow
            label="Full check"
            source={
              <ConfigSource source="team" where={`hub.json → repos[${String(repo.index)}].check`} />
            }
            action={ask(
              "check",
              "Full check",
              repo.check,
              "team",
              `hub.json → repos[${String(repo.index)}].check`,
            )}
          >
            <Mono>{repo.check}</Mono>
          </ConfigRow>
        </div>
      )}
    </details>
  );
}

function BlockedRow({
  label,
  list,
  layer,
  keyPath,
  sensitive,
  onEditLocal,
}: {
  label: string;
  list: LayeredList;
  layer: Layer;
  keyPath: string;
  sensitive?: boolean;
  onEditLocal: () => void;
}) {
  const [shown, setShown] = useState(false);
  const { attach, isAttached } = useAttach();
  const items =
    layer === "team" ? list.team : layer === "local" ? list.local : [...list.team, ...list.local];
  const count =
    layer === "effective"
      ? `${String(list.team.length)} team · ${String(list.local.length)} yours`
      : String(items.length);
  const id = `guard.${keyPath}`;
  return (
    <ConfigRow
      label={label}
      source={
        layer === "local" ? (
          list.local.length > 0 ? (
            <ConfigSource source="local" where={`hub.local.json → guard.${keyPath}`} />
          ) : null
        ) : (
          <ConfigSource source="team" where={`hub.json → guard.${keyPath}, plus hub.local.json`} />
        )
      }
      action={
        layer === "local"
          ? {
              label: `Edit ${label.toLowerCase()} in my local settings`,
              icon: "pencil",
              onClick: onEditLocal,
            }
          : {
              label: `Ask Claude to change ${label.toLowerCase()}`,
              icon: "message-square",
              pressed: isAttached(id),
              onClick: () => {
                attach({
                  id: `config:${id}`,
                  label,
                  source: "hub.json",
                  // Never the words themselves: the key and the counts only.
                  quote: `guard.${keyPath}: ${String(list.team.length)} in hub.json, ${String(list.local.length)} in hub.local.json`,
                });
              },
            }
      }
    >
      {!sensitive ? (
        <ListValue items={items} />
      ) : items.length === 0 ? (
        <NoneText />
      ) : (
        <span className="ah-stack" style={{ gap: 6, alignItems: "flex-start" }}>
          <span className="ah-row" style={{ gap: 8 }}>
            <span>{count}</span>
            <Button
              size="sm"
              variant="ghost"
              icon={shown ? "eye-off" : "search"}
              aria-expanded={shown}
              onClick={() => {
                setShown(!shown);
              }}
            >
              {shown ? "Hide words" : "Show words"}
            </Button>
          </span>
          {shown && <ListValue items={items} />}
        </span>
      )}
    </ConfigRow>
  );
}

function ConfigBody({
  view,
  layer,
  onSaved,
}: {
  view: HubConfigView;
  layer: Layer;
  onSaved: () => void;
}) {
  const [params, setParams] = useSearchParams();
  const openRepo = params.get("repo");
  const { attach, isAttached } = useAttach();
  const [editing, setEditing] = useState<string | null>(null);

  const askSection = (id: string, label: string, quote: string) => () => {
    attach({ id: `config:section:${id}`, label, source: "hub.json", quote });
  };
  const identityRow = (key: "author_name" | "author_email" | "branch_prefix", label: string) => {
    const value = view[key];
    const id = `project.${key}`;
    return (
      <ConfigRow
        label={label}
        source={sourceShown(value, layer)}
        action={
          layer === "local"
            ? {
                label: `Edit ${label.toLowerCase()} in my local settings`,
                icon: "pencil",
                onClick: () => {
                  setEditing(key);
                },
              }
            : {
                label: `Ask Claude to change ${label.toLowerCase()}`,
                icon: "message-square",
                pressed: isAttached(id),
                onClick: () => {
                  attach(reference(id, label, value.value ?? "", value.source, value.where));
                },
              }
        }
      >
        <SourcedCell value={value} layer={layer} />
      </ConfigRow>
    );
  };
  const guard = view.guard;
  const tracker = view.tracker;
  /** A team-only row's action: point Claude at that one key. */
  const teamAsk = (path: string, label: string, value: unknown) => ({
    label: `Ask Claude to change ${label.toLowerCase()}`,
    icon: "message-square" as IconName,
    pressed: isAttached(path),
    onClick: () => {
      attach({
        id: `config:${path}`,
        label,
        source: "hub.json",
        quote: `${path}: ${JSON.stringify(value)}   (source: Team)`,
      });
    },
  });
  const editLocal = (field: string) => () => {
    setEditing(field);
  };

  return (
    <div className="ah-config-frame">
      <div className="ah-config-layout">
        <nav className="ah-config-rail" aria-label="On this page">
          <div className="ah-small ah-muted">On this page</div>
          {SECTIONS.filter((section) => layer !== "local" || section.id !== "models").map(
            (section) => (
              <a key={section.id} href={`#${section.id}`}>
                {section.label}
              </a>
            ),
          )}
          {view.repos.length > 1 &&
            view.repos.map((repo) => (
              <a
                key={repo.dir}
                href={`#repositories`}
                className="ah-config-rail-sub"
                onClick={() => {
                  setParams(
                    (prev) => {
                      prev.set("repo", repo.dir);
                      return prev;
                    },
                    { replace: true },
                  );
                }}
              >
                {repo.dir}
              </a>
            ))}
        </nav>
        <div className="ah-stack" style={{ gap: 16, minWidth: 0 }}>
          <Section
            id="repositories"
            title="Repositories"
            icon="git-branch"
            purpose="Per repo: the base branch, how branches, commits and PRs are named, and the checks the agents run."
          >
            {view.repos.map((repo, index) => (
              <RepoCard
                key={repo.dir}
                repo={repo}
                layer={layer}
                open={openRepo === null ? index === 0 : openRepo === repo.dir}
                onToggle={(isOpen) => {
                  if (isOpen && openRepo !== repo.dir)
                    setParams(
                      (prev) => {
                        prev.set("repo", repo.dir);
                        return prev;
                      },
                      { replace: true },
                    );
                }}
              />
            ))}
          </Section>

          <Section
            id="who-commits"
            title="Who commits"
            icon="user"
            purpose="The git identity and branch prefix the agents use in every repo."
            onAsk={
              layer === "local"
                ? undefined
                : askSection(
                    "who-commits",
                    "Who commits",
                    `project.author_name: ${JSON.stringify(view.author_name.value)} (source: ${SOURCE_WORD[view.author_name.source]})\nproject.author_email: ${JSON.stringify(view.author_email.value)} (source: ${SOURCE_WORD[view.author_email.source]})\nproject.branch_prefix: ${JSON.stringify(view.branch_prefix.value)} (source: ${SOURCE_WORD[view.branch_prefix.source]})`,
                  )
            }
          >
            <div className="ah-config-rows">
              {identityRow("author_name", "Author name")}
              {identityRow("author_email", "Author email")}
              {identityRow("branch_prefix", "Branch prefix")}
            </div>
            <p className="ah-small ah-muted ah-config-note">
              Commits and branches in every repo use these. A repo&apos;s own git config does not
              change them.
            </p>
          </Section>

          <Section
            id="guard"
            title="Guard"
            icon="shield-alert"
            purpose="What the agents may never touch, and the words they must never write."
            onAsk={
              layer === "local"
                ? undefined
                : askSection(
                    "guard",
                    "Guard",
                    `guard: ${String(guard.blocked_words.team.length)} blocked words in hub.json, ${String(guard.blocked_words.local.length)} in hub.local.json; deny_paths ${JSON.stringify(guard.deny_paths)}; ask_before_edit ${JSON.stringify(guard.ask_before_edit)}; deny_hosts ${JSON.stringify(guard.deny_hosts)}`,
                  )
            }
          >
            <div className="ah-config-rows">
              <BlockedRow
                label="Blocked words"
                list={guard.blocked_words}
                layer={layer}
                keyPath="blocked_words"
                sensitive
                onEditLocal={editLocal("blocked_words")}
              />
              <BlockedRow
                label="Files checked for blocked words"
                list={guard.blocked_words_files}
                layer={layer}
                keyPath="blocked_words_files"
                onEditLocal={editLocal("blocked_words_files")}
              />
              <BlockedRow
                label="Variables checked for blocked words"
                list={guard.blocked_words_env}
                layer={layer}
                keyPath="blocked_words_env"
                onEditLocal={editLocal("blocked_words_env")}
              />
              {layer !== "local" && (
                <>
                  <ConfigRow
                    label="Never read or edit"
                    action={teamAsk("guard.deny_paths", "Never read or edit", guard.deny_paths)}
                    source={<ConfigSource source="team" where="hub.json → guard.deny_paths" />}
                  >
                    <ListValue items={guard.deny_paths} />
                  </ConfigRow>
                  <ConfigRow
                    label="Ask before editing"
                    action={teamAsk(
                      "guard.ask_before_edit",
                      "Ask before editing",
                      guard.ask_before_edit,
                    )}
                    source={<ConfigSource source="team" where="hub.json → guard.ask_before_edit" />}
                  >
                    <ListValue items={guard.ask_before_edit} />
                  </ConfigRow>
                  <ConfigRow
                    label="Hosts denied"
                    action={teamAsk("guard.deny_hosts", "Hosts denied", guard.deny_hosts)}
                    source={<ConfigSource source="team" where="hub.json → guard.deny_hosts" />}
                  >
                    <ListValue items={guard.deny_hosts} />
                  </ConfigRow>
                  <ConfigRow
                    label="Secret env files"
                    action={teamAsk(
                      "guard.secret_env_files",
                      "Secret env files",
                      guard.secret_env_files,
                    )}
                    source={
                      <ConfigSource source="team" where="hub.json → guard.secret_env_files" />
                    }
                  >
                    <ListValue items={guard.secret_env_files} />
                  </ConfigRow>
                  <ConfigRow
                    label="Readable env files"
                    action={teamAsk(
                      "guard.readable_env_files",
                      "Readable env files",
                      guard.readable_env_files,
                    )}
                    source={
                      <ConfigSource source="team" where="hub.json → guard.readable_env_files" />
                    }
                  >
                    <ListValue items={guard.readable_env_files} />
                  </ConfigRow>
                  <ConfigRow
                    label="Infra guard"
                    action={teamAsk("guard.infra", "Infra guard", guard.infra_on ? "on" : "off")}
                    source={
                      <ConfigSource
                        source={guard.infra_on ? "team" : "default"}
                        where="hub.json → guard.infra"
                      />
                    }
                  >
                    {guard.infra_on ? (
                      <span>On · hub.json sets guard.infra</span>
                    ) : (
                      <NoneText>Off · the guard&apos;s fixed infra rule</NoneText>
                    )}
                  </ConfigRow>
                </>
              )}
            </div>
          </Section>

          <Section
            id="tracker"
            title="Tracker"
            icon="list-todo"
            purpose="Where the tickets live and how the agents move them."
            onAsk={
              layer === "local"
                ? undefined
                : askSection(
                    "tracker",
                    "Tracker",
                    `tracker: kind ${tracker.kind}, teams ${JSON.stringify(tracker.teams)}, transport ${JSON.stringify(tracker.transport.value)} (source: ${SOURCE_WORD[tracker.transport.source]})`,
                  )
            }
          >
            <div className="ah-config-rows">
              {layer !== "local" && (
                <ConfigRow
                  label="Tracker"
                  action={teamAsk("tracker.teams", "Tracker teams", tracker.teams)}
                  source={
                    <ConfigSource source="team" where="hub.json → tracker.kind, tracker.team(s)" />
                  }
                >
                  <span>
                    {tracker.kind === "linear" ? "Linear" : tracker.kind} ·{" "}
                    {tracker.teams.length === 1 ? "team" : "teams"}{" "}
                    <Mono>{tracker.teams.join(", ")}</Mono>
                  </span>
                </ConfigRow>
              )}
              <ConfigRow
                label="Transport"
                source={sourceShown(tracker.transport, layer)}
                action={
                  layer === "local"
                    ? {
                        label: "Edit transport in my local settings",
                        icon: "pencil",
                        onClick: editLocal("transport"),
                      }
                    : teamAsk("tracker.transport", "Transport", tracker.transport.value)
                }
              >
                <SourcedCell value={tracker.transport} layer={layer} />
              </ConfigRow>
              {layer !== "local" && (
                <>
                  <ConfigRow
                    label="Labels"
                    action={teamAsk("tracker.labels", "Labels", {
                      ready_label: tracker.ready_label,
                      failed_label: tracker.failed_label,
                      blocked_label: tracker.blocked_label,
                    })}
                    source={<ConfigSource source="team" where="hub.json → tracker.*_label" />}
                  >
                    <span className="ah-config-list">
                      <span>
                        ready <Mono>{tracker.ready_label}</Mono>
                      </span>
                      <span>
                        failed <Mono>{tracker.failed_label}</Mono>
                      </span>
                      <span>
                        blocked <Mono>{tracker.blocked_label ?? tracker.failed_label}</Mono>
                      </span>
                    </span>
                  </ConfigRow>
                  <ConfigRow
                    label="States"
                    action={teamAsk("tracker.states", "States", {
                      started: tracker.started_state,
                      review: tracker.review_state,
                    })}
                    source={<ConfigSource source="team" where="hub.json → tracker.states" />}
                  >
                    <span className="ah-config-list">
                      <span>
                        started <Mono>{tracker.started_state}</Mono>
                      </span>
                      <span>
                        review <Mono>{tracker.review_state}</Mono>
                      </span>
                    </span>
                  </ConfigRow>
                </>
              )}
            </div>
          </Section>

          {layer !== "local" && (
            <Section
              id="models"
              title="Models"
              icon="cpu"
              purpose="Which model each tier names, and which agents move off their template's tier."
              onAsk={askSection(
                "models",
                "Models",
                `models.tiers: ${JSON.stringify(view.model_tiers)}`,
              )}
            >
              <div className="ah-config-rows">
                {(
                  [
                    ["small", "Small"],
                    ["medium", "Medium"],
                    ["large", "Large"],
                  ] as const
                ).map(([tier, tierLabel]) => (
                  <ConfigRow
                    key={tier}
                    label={tierLabel}
                    action={teamAsk(
                      `models.tiers.${tier}`,
                      `${tierLabel} model`,
                      view.model_tiers[tier],
                    )}
                    source={
                      <ConfigSource
                        source="team"
                        where={`hub.json → models.tiers.${tier} (or its default)`}
                      />
                    }
                  >
                    <Mono>{view.model_tiers[tier]}</Mono>
                  </ConfigRow>
                ))}
                <ConfigRow label="By agent">
                  {view.agent_models.length === 0 ? (
                    <NoneText>Every agent keeps its template&apos;s tier</NoneText>
                  ) : (
                    <span className="ah-config-list">
                      {view.agent_models.map((m) => (
                        <span key={m.agent}>
                          {m.agent} <Mono>{m.tier}</Mono>
                        </span>
                      ))}
                    </span>
                  )}
                </ConfigRow>
              </div>
            </Section>
          )}
        </div>
        {editing !== null && (
          <LocalSettingsDialog
            view={view}
            focus={editing}
            onClose={() => {
              setEditing(null);
            }}
            onSaved={onSaved}
          />
        )}
      </div>
    </div>
  );
}

/** The project's hub configuration: team and local values per repo, each with its source. */
export function HubConfigScreen() {
  const { project = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const layerParam = params.get("layer");
  const layer: Layer = layerParam === "team" || layerParam === "local" ? layerParam : "effective";
  const config = useApi("/api/v1/projects/{project}/config", { path: { project } });
  const { setOpen, addReference } = useDiscuss();
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (!saved) return;
    const timer = setTimeout(() => {
      setSaved(false);
    }, 4000);
    return () => {
      clearTimeout(timer);
    };
  }, [saved]);
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const blocked = unavailable ? `${unavailable.title}. ${unavailable.detail}` : null;
  const onSaved = () => {
    setSaved(true);
  };
  useDiscussTarget({
    key: `config:${project}`,
    project,
    kind: "Hub configuration",
    title: project,
    path: "hub.json",
    brief: BRIEF,
    starters: STARTERS,
  });
  useEffect(() => {
    document.title = `Hub configuration · ${project}`;
  }, [project]);

  const view = config.data;
  const localSet = view
    ? [view.author_name, view.author_email, view.branch_prefix, view.tracker.transport].filter(
        (v) => v.source === "local",
      ).length +
      view.guard.blocked_words.local.length +
      view.guard.blocked_words_files.local.length +
      view.guard.blocked_words_env.local.length
    : 0;

  let body: ReactNode;
  if (config.isError) {
    body = (
      <ProblemError
        title={
          config.error.status === 404
            ? "Project not found"
            : "Could not read this project's hub.json"
        }
        detail={`${config.error.detail ?? ""} Run ./hub doctor in the hub for the line to fix.`}
        status={config.error.status}
        onRetry={() => void config.refetch()}
      />
    );
  } else if (!view) {
    body = (
      <div className="ah-stack" style={{ gap: 12 }} aria-busy="true">
        <Skeleton height={32} />
        <Skeleton height={220} />
        <Skeleton height={140} />
      </div>
    );
  } else {
    body = (
      <>
        {layer === "local" && localSet === 0 && (
          <Banner
            tone="info"
            action={
              <Button
                size="sm"
                icon="pencil"
                onClick={() => {
                  setEditing(true);
                }}
              >
                Edit my local settings
              </Button>
            }
          >
            No hub.local.json values on this machine. Your values come from hub.json and git config.
          </Banner>
        )}
        <ConfigBody view={view} layer={layer} onSaved={onSaved} />
      </>
    );
  }

  return (
    <AskBlocked.Provider value={blocked}>
      <div className="ah-page" style={{ gap: 16 }}>
        <Breadcrumbs
          items={[
            { label: "Portfolio", href: "/" },
            { label: project, href: `/projects/${encodeURIComponent(project)}` },
            { label: "Hub configuration" },
          ]}
        />
        <header className="ah-config-head">
          <div className="ah-stack" style={{ gap: 4, minWidth: 0 }}>
            <h1 className="ah-h1">Hub configuration</h1>
            {view && (
              <>
                <p className="ah-muted ah-small" style={{ margin: 0 }}>
                  <Icon name="users" /> <Mono>hub.json</Mono> in {view.hub_repo} · shared with the
                  team, changed through a hub PR
                </p>
                <p className="ah-muted ah-small" style={{ margin: 0 }}>
                  <Icon name="laptop" /> Your layer: <Mono>hub.local.json</Mono> on this machine ·
                  only you ·{" "}
                  {localSet === 0
                    ? "nothing set"
                    : `${String(localSet)} ${localSet === 1 ? "value" : "values"} set`}
                </p>
              </>
            )}
          </div>
          <div className="ah-row" style={{ gap: 8, flexShrink: 0 }}>
            <Button
              icon="pencil"
              disabled={!view}
              onClick={() => {
                setEditing(true);
              }}
            >
              Edit my local settings
            </Button>
            <Tooltip label={blocked ?? undefined}>
              <Button
                variant="primary"
                icon="message-square"
                disabled={blocked !== null}
                onClick={() => {
                  setOpen(true);
                }}
              >
                Ask Claude to change the config
              </Button>
            </Tooltip>
          </div>
        </header>
        {view && view.local_file.problems.length > 0 && (
          <Banner
            tone="warning"
            action={
              <Button
                size="sm"
                icon="message-square"
                disabled={blocked !== null}
                onClick={() => {
                  addReference({
                    id: "config:hub.local.json",
                    label: "hub.local.json problems",
                    source: "hub.local.json",
                    quote: view.local_file.problems.join("\n"),
                  });
                }}
              >
                Ask Claude to fix it
              </Button>
            }
          >
            hub.local.json has a problem, so your local values are ignored:{" "}
            {view.local_file.problems.join("; ")}
          </Banner>
        )}
        <div className="ah-row" style={{ gap: 12, flexWrap: "wrap" }}>
          <span className="ah-small ah-muted">Show</span>
          <SegmentedControl
            label="Layer"
            options={LAYERS}
            value={layer}
            onChange={(id) => {
              setParams(
                (prev) => {
                  if (id === "effective") prev.delete("layer");
                  else prev.set("layer", id);
                  return prev;
                },
                { replace: true },
              );
            }}
          />
          <span className="ah-small ah-muted">
            {layer === "effective"
              ? "The value that applies, and the layer that set it."
              : layer === "team"
                ? "What the team prepared in hub.json, even where your local value wins."
                : "Only what hub.local.json may set on this machine."}
          </span>
        </div>
        {body}
        {editing && view && (
          <LocalSettingsDialog
            view={view}
            focus={null}
            onClose={() => {
              setEditing(false);
            }}
            onSaved={onSaved}
          />
        )}
        {saved && (
          <div className="ah-config-toast">
            <Toast>Saved hub.local.json</Toast>
          </div>
        )}
      </div>
    </AskBlocked.Provider>
  );
}

/** `/config`: the project in scope's configuration, else a project picker. */
export function HubConfigPickerScreen() {
  const [scope] = useScope();
  if (scope !== null) return <Navigate to={configHome(scope)} replace />;
  return (
    <KnowledgeProjectIndex
      title="Hub configuration"
      intro="Each project's hub rules: per repo the default branch, branch, commit and PR title patterns and checks; who commits; the guard and its blocked words. Open a project to see and change them."
      caption="Projects and their hub configuration"
      emptyLine="Register a hub to see its configuration."
      tip="Tip: pick a project in the scope switcher to open its configuration directly."
      href={configHome}
      columns={[]}
    />
  );
}
