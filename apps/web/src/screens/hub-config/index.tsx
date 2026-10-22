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
  Skeleton,
  Toast,
  Tooltip,
} from "../../components";
import type { IconName } from "../../components";
import { useApi } from "../../lib/api";
import { useScope } from "../../lib/scope";
import { readStored, removeStored, writeStored } from "../../lib/storage";
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

type Source = SourcedValue["source"] | PatternView["source"];

/** Where the sidebar's Hub config goes: the project in scope, else a project picker. */
export const CONFIG_PICKER = "/config";
export function configHome(project: string): string {
  return `/projects/${encodeURIComponent(project)}/config`;
}

/**
 * Who set a value, in the words a person uses. "Set by you" and "Set by the team" are the two
 * files someone edits; "Built-in" is agent-hub's own value when neither file sets one.
 */
const SOURCE_LOOK: Record<Source, { label: string; icon: IconName }> = {
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

/** A pattern rendered with sample values; the Repositories card says so once. */
function PatternExample({ example }: { example: string | null | undefined }) {
  if (!example) return null;
  return (
    <div className="ah-config-example">
      <span>e.g.</span>
      <code className="ah-mono">{example}</code>
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

interface RowAsk {
  label: string;
  pressed: boolean;
  onClick: () => void;
}

interface RowProps {
  label: string;
  children: ReactNode;
  source?: ReactNode;
  /** Point Claude at this row: shown on hover and focus, and kept once attached. */
  ask?: RowAsk | undefined;
  /** Open this row's field in my settings: only for what hub.local.json may set. */
  onEdit?: (() => void) | undefined;
  editLabel?: string;
}

function ConfigRow({
  label,
  children,
  source,
  ask,
  onEdit,
  editLabel = "Change for me",
}: RowProps) {
  const blocked = useContext(AskBlocked);
  return (
    <div className="ah-config-row">
      <div className="ah-config-label">{label}</div>
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
            aria-label={`${editLabel}: ${label.toLowerCase()}`}
            onClick={onEdit}
          >
            {editLabel}
          </Button>
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

/** A value and, when my value replaces the team's, the team's value it overrides. */
function SourcedCell({ value }: { value: SourcedValue }) {
  const overrides =
    value.source === "local" && value.team_value && value.team_value !== value.value
      ? value.team_value
      : null;
  return (
    <span className="ah-config-cell">
      {value.value ? <Mono>{value.value}</Mono> : <NoneText>Not set</NoneText>}
      {overrides !== null && (
        <span className="ah-small ah-muted">
          Overrides the team&apos;s <Mono>{overrides}</Mono>
        </span>
      )}
    </span>
  );
}

/** Who set a value; nothing when no source gives one. */
function sourceOf(value: SourcedValue): ReactNode {
  if (!value.value) return null;
  return <ConfigSource source={value.source} where={value.where} />;
}

/** A team-only key: set by the team when hub.json gives it, else agent-hub's built-in value. */
function teamOrBuiltIn(set: boolean, where: string): ReactNode {
  return set ? (
    <ConfigSource source="team" where={`hub.json → ${where}`} />
  ) : (
    <ConfigSource source="default" where={where} />
  );
}

/** Who set a list the team sets and I add to. */
function ListSource({ list, keyPath }: { list: LayeredList; keyPath: string }) {
  const team = list.team.length > 0;
  const mine = list.local.length > 0;
  if (!team && !mine) return null;
  if (team && mine)
    return (
      <Tooltip
        label={`hub.json → guard.${keyPath} (${String(list.team.length)}), plus hub.local.json → guard.${keyPath} (${String(list.local.length)})`}
      >
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
        <span className="ah-config-source" tabIndex={0}>
          <Icon name="users" />
          Set by the team and you
        </span>
      </Tooltip>
    );
  return (
    <ConfigSource
      source={team ? "team" : "local"}
      where={`${team ? "hub.json" : "hub.local.json"} → guard.${keyPath}`}
    />
  );
}

/* ---------- Sections ---------- */

interface SectionProps {
  id: string;
  title: string;
  /** What the section's Ask button names: "Ask Claude to change <askName>". */
  askName: string;
  purpose: string;
  icon: IconName;
  onAsk?: (() => void) | undefined;
  children: ReactNode;
}

function Section({ id, title, askName, purpose, icon, onAsk, children }: SectionProps) {
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

/* ---------- Where values come from ---------- */

const EXPLAINER_KEY = "ah.config.explainer";

const STEPS: readonly { icon: IconName; title: string; text: (hubRepo: string) => ReactNode }[] = [
  {
    icon: "box",
    title: "Built-in",
    text: () => "agent-hub's own value, used when no file sets one.",
  },
  {
    icon: "users",
    title: "Set by the team",
    text: (hubRepo) => (
      <>
        <Mono>hub.json</Mono> in {hubRepo}. Shared with everyone; changed through a hub PR.
      </>
    ),
  },
  {
    icon: "laptop",
    title: "Set by you",
    text: () => (
      <>
        <Mono>hub.local.json</Mono> on this machine. Only you; never committed.
      </>
    ),
  },
  {
    icon: "check",
    title: "What agents use",
    text: () => "The last one that sets a value wins. That is the value shown on each row.",
  },
];

function mineCount(localSet: number): string {
  if (localSet === 0) return "You set nothing on this machine yet.";
  return `You set ${String(localSet)} ${localSet === 1 ? "value" : "values"} on this machine.`;
}

/** How a value is chosen, said once: built-in, then the team's file, then mine. */
function WhereValuesComeFrom({ hubRepo, localSet }: { hubRepo: string; localSet: number }) {
  const [open, setOpen] = useState(() => readStored(EXPLAINER_KEY) !== "hidden");
  const toggle = (next: boolean) => {
    setOpen(next);
    if (next) removeStored(EXPLAINER_KEY);
    else writeStored(EXPLAINER_KEY, "hidden");
  };
  if (!open)
    return (
      <div className="ah-config-explainer-line ah-small ah-muted">
        <Icon name="info" />
        <span>
          Each value comes from <strong>Built-in</strong>, then <strong>Set by the team</strong>,
          then <strong>Set by you</strong>; the last one that sets it wins. {mineCount(localSet)}
        </span>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            toggle(true);
          }}
        >
          Show where values come from
        </Button>
      </div>
    );
  return (
    <section className="ah-card ah-config-explainer" aria-labelledby="config-explainer-title">
      <header className="ah-config-section-head">
        <h2 className="ah-h3" id="config-explainer-title">
          Where values come from
        </h2>
        <Button
          size="sm"
          variant="ghost"
          icon="eye-off"
          onClick={() => {
            toggle(false);
          }}
        >
          Hide
        </Button>
      </header>
      <ol className="ah-config-steps">
        {STEPS.map((step) => (
          <li key={step.title}>
            <span className="ah-config-step-title">
              <Icon name={step.icon} />
              {step.title}
            </span>
            <span className="ah-small ah-muted">{step.text(hubRepo)}</span>
          </li>
        ))}
      </ol>
      <p className="ah-small ah-muted ah-config-note">
        You can set your author name and email, branch prefix and tracker transport, and add blocked
        words. Everything else is the team&apos;s. {mineCount(localSet)}
      </p>
    </section>
  );
}

/* ---------- Screen ---------- */

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
  open,
  onToggle,
}: {
  repo: RepoConfigView;
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
  ): RowAsk => {
    const id = `repos[${String(repo.index)}].${key}`;
    return {
      label: `Ask Claude to change ${label.toLowerCase()} of ${repo.dir}`,
      pressed: isAttached(id),
      onClick: () => {
        attach(reference(id, `${label} · ${repo.dir}`, value, source, where, example));
      },
    };
  };
  const pattern = (key: "branch" | "commit_title" | "pr_title", label: string) => {
    const p = repo[key];
    const follows = p.source === "commit_title";
    return (
      <ConfigRow
        label={label}
        source={follows ? null : <ConfigSource source={p.source} where={p.where} />}
        ask={ask(`conventions.${key}`, label, p.pattern, p.source, p.where, p.example)}
      >
        {follows ? <span>Same as the commit title</span> : <Mono>{p.pattern}</Mono>}
        {!follows && <PatternExample example={p.example} />}
      </ConfigRow>
    );
  };
  const fastWhere = `repos[${String(repo.index)}].check_fast`;
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
      <div className="ah-config-rows">
        <ConfigRow
          label="Default branch"
          source={sourceOf(repo.default_branch)}
          ask={ask(
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
          source={repo.check_fast ? teamOrBuiltIn(true, fastWhere) : null}
          ask={ask(
            "check_fast",
            "Fast check",
            repo.check_fast ?? "",
            "team",
            `hub.json → ${fastWhere}`,
          )}
        >
          {repo.check_fast ? (
            <span>
              <Mono>{repo.check_fast}</Mono>{" "}
              <span className="ah-small ah-muted">
                · timeout {String(repo.check_fast_timeout ?? 150)} s
                {repo.check_fast_timeout === null ? " (built-in)" : ""}
              </span>
            </span>
          ) : (
            <NoneText>None · agents stop without a fast check</NoneText>
          )}
        </ConfigRow>
        <ConfigRow
          label="Full check"
          source={teamOrBuiltIn(true, `repos[${String(repo.index)}].check`)}
          ask={ask(
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
    </details>
  );
}

function BlockedRow({
  label,
  list,
  keyPath,
  sensitive,
  onEdit,
}: {
  label: string;
  list: LayeredList;
  keyPath: string;
  sensitive?: boolean;
  onEdit: () => void;
}) {
  const [shown, setShown] = useState(false);
  const { attach, isAttached } = useAttach();
  const items = [...list.team, ...list.local];
  const total = items.length;
  const id = `guard.${keyPath}`;
  const count =
    list.team.length > 0 && list.local.length > 0
      ? `${String(total)} words: ${String(list.team.length)} from the team, ${String(list.local.length)} added by you`
      : `${String(total)} ${total === 1 ? "word" : "words"}`;
  return (
    <ConfigRow
      label={label}
      source={<ListSource list={list} keyPath={keyPath} />}
      editLabel="Add for me"
      onEdit={onEdit}
      ask={{
        label: `Ask Claude to change ${label.toLowerCase()}`,
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
      }}
    >
      {!sensitive ? (
        <ListValue items={items} />
      ) : total === 0 ? (
        <NoneText />
      ) : (
        <span className="ah-config-cell">
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

function ConfigBody({ view, onSaved }: { view: HubConfigView; onSaved: () => void }) {
  const [params, setParams] = useSearchParams();
  const openRepo = params.get("repo");
  const { attach, isAttached } = useAttach();
  const [editing, setEditing] = useState<string | null>(null);

  const askSection = (id: string, label: string, quote: string) => () => {
    attach({ id: `config:section:${id}`, label, source: "hub.json", quote });
  };
  const editLocal = (field: string) => () => {
    setEditing(field);
  };
  const identityRow = (key: "author_name" | "author_email" | "branch_prefix", label: string) => {
    const value = view[key];
    const id = `project.${key}`;
    return (
      <ConfigRow
        label={label}
        source={sourceOf(value)}
        onEdit={editLocal(key)}
        ask={{
          label: `Ask Claude to change ${label.toLowerCase()}`,
          pressed: isAttached(id),
          onClick: () => {
            attach(reference(id, label, value.value ?? "", value.source, value.where));
          },
        }}
      >
        <SourcedCell value={value} />
      </ConfigRow>
    );
  };
  const guard = view.guard;
  const tracker = view.tracker;
  /** A team-only row's action: point Claude at that one key. */
  const teamAsk = (path: string, label: string, value: unknown): RowAsk => ({
    label: `Ask Claude to change ${label.toLowerCase()}`,
    pressed: isAttached(path),
    onClick: () => {
      attach({
        id: `config:${path}`,
        label,
        source: "hub.json",
        quote: `${path}: ${JSON.stringify(value)}`,
      });
    },
  });
  const teamList = (key: string, label: string, items: readonly string[]) => (
    <ConfigRow
      label={label}
      ask={teamAsk(`guard.${key}`, label, items)}
      source={items.length > 0 ? teamOrBuiltIn(true, `guard.${key}`) : null}
    >
      <ListValue items={items} />
    </ConfigRow>
  );
  const trackerSet = (...keys: string[]) => keys.some((key) => tracker.team_set.includes(key));

  return (
    <div className="ah-config-frame">
      <div className="ah-config-layout">
        <nav className="ah-config-rail" aria-label="On this page">
          <div className="ah-small ah-muted">On this page</div>
          {SECTIONS.map((section) => (
            <a key={section.id} href={`#${section.id}`}>
              {section.label}
            </a>
          ))}
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
            askName="the repositories"
            icon="git-branch"
            purpose="Per repo: the base branch, how branches, commits and PRs are named, and the checks the agents run. Examples use sample values."
            onAsk={askSection(
              "repositories",
              "Repositories",
              view.repos
                .map(
                  (repo) =>
                    `repos[${String(repo.index)}] ${repo.dir}: commit_title ${JSON.stringify(repo.commit_title.pattern)}, check ${JSON.stringify(repo.check)}`,
                )
                .join("\n"),
            )}
          >
            {view.repos.map((repo, index) => (
              <RepoCard
                key={repo.dir}
                repo={repo}
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
            askName="who commits"
            icon="user"
            purpose="The git identity and branch prefix the agents use in every repo."
            onAsk={askSection(
              "who-commits",
              "Who commits",
              `project.author_name: ${JSON.stringify(view.author_name.value)} (source: ${SOURCE_WORD[view.author_name.source]})\nproject.author_email: ${JSON.stringify(view.author_email.value)} (source: ${SOURCE_WORD[view.author_email.source]})\nproject.branch_prefix: ${JSON.stringify(view.branch_prefix.value)} (source: ${SOURCE_WORD[view.branch_prefix.source]})`,
            )}
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
            askName="the guard"
            icon="shield-alert"
            purpose="What the agents may never touch, and the words they must never write."
            onAsk={askSection(
              "guard",
              "Guard",
              `guard: ${String(guard.blocked_words.team.length)} blocked words in hub.json, ${String(guard.blocked_words.local.length)} in hub.local.json; deny_paths ${JSON.stringify(guard.deny_paths)}; ask_before_edit ${JSON.stringify(guard.ask_before_edit)}; deny_hosts ${JSON.stringify(guard.deny_hosts)}`,
            )}
          >
            <div className="ah-config-rows">
              <BlockedRow
                label="Blocked words"
                list={guard.blocked_words}
                keyPath="blocked_words"
                sensitive
                onEdit={editLocal("blocked_words")}
              />
              <BlockedRow
                label="Files checked for blocked words"
                list={guard.blocked_words_files}
                keyPath="blocked_words_files"
                onEdit={editLocal("blocked_words_files")}
              />
              <BlockedRow
                label="Variables checked for blocked words"
                list={guard.blocked_words_env}
                keyPath="blocked_words_env"
                onEdit={editLocal("blocked_words_env")}
              />
              {teamList("deny_paths", "Never read or edit", guard.deny_paths)}
              {teamList("ask_before_edit", "Ask before editing", guard.ask_before_edit)}
              {teamList("deny_hosts", "Hosts denied", guard.deny_hosts)}
              {teamList("secret_env_files", "Secret env files", guard.secret_env_files)}
              {teamList("readable_env_files", "Readable env files", guard.readable_env_files)}
              <ConfigRow
                label="Infra guard"
                ask={teamAsk("guard.infra", "Infra guard", guard.infra_on ? "on" : "off")}
                source={teamOrBuiltIn(guard.infra_on, "guard.infra")}
              >
                {guard.infra_on ? (
                  <span>On</span>
                ) : (
                  <NoneText>Not turned on · the guard&apos;s fixed infra rule applies</NoneText>
                )}
              </ConfigRow>
            </div>
          </Section>

          <Section
            id="tracker"
            title="Tracker"
            askName="the tracker"
            icon="list-todo"
            purpose="Where the tickets live and how the agents move them."
            onAsk={askSection(
              "tracker",
              "Tracker",
              `tracker: kind ${tracker.kind}, teams ${JSON.stringify(tracker.teams)}, transport ${JSON.stringify(tracker.transport.value)} (source: ${SOURCE_WORD[tracker.transport.source]})`,
            )}
          >
            <div className="ah-config-rows">
              <ConfigRow
                label="Tracker"
                ask={teamAsk("tracker.teams", "Tracker teams", tracker.teams)}
                source={teamOrBuiltIn(true, "tracker.kind, tracker.team(s)")}
              >
                <span>
                  {tracker.kind === "linear" ? "Linear" : tracker.kind} ·{" "}
                  {tracker.teams.length === 1 ? "team" : "teams"}{" "}
                  <Mono>{tracker.teams.join(", ")}</Mono>
                </span>
              </ConfigRow>
              <ConfigRow
                label="Transport"
                source={sourceOf(tracker.transport)}
                onEdit={editLocal("transport")}
                ask={teamAsk("tracker.transport", "Transport", tracker.transport.value)}
              >
                <SourcedCell value={tracker.transport} />
              </ConfigRow>
              <ConfigRow
                label="Labels"
                ask={teamAsk("tracker.labels", "Labels", {
                  ready_label: tracker.ready_label,
                  failed_label: tracker.failed_label,
                  blocked_label: tracker.blocked_label,
                })}
                source={teamOrBuiltIn(
                  trackerSet("ready_label", "failed_label", "blocked_label"),
                  "tracker.ready_label, failed_label, blocked_label",
                )}
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
                ask={teamAsk("tracker.states", "States", {
                  started: tracker.started_state,
                  review: tracker.review_state,
                })}
                source={teamOrBuiltIn(
                  trackerSet("started_state", "review_state"),
                  "tracker.states",
                )}
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
            </div>
          </Section>

          <Section
            id="models"
            title="Models"
            askName="the models"
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
                  ask={teamAsk(
                    `models.tiers.${tier}`,
                    `${tierLabel} model`,
                    view.model_tiers[tier],
                  )}
                  source={teamOrBuiltIn(
                    view.model_tiers_set.includes(tier),
                    `models.tiers.${tier}`,
                  )}
                >
                  <Mono>{view.model_tiers[tier]}</Mono>
                </ConfigRow>
              ))}
              <ConfigRow
                label="By agent"
                source={view.agent_models.length > 0 ? teamOrBuiltIn(true, "models.agents") : null}
              >
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

/** The project's hub configuration: the value agents use for each key, and who set it. */
export function HubConfigScreen() {
  const { project = "" } = useParams();
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
        <WhereValuesComeFrom hubRepo={view.hub_repo} localSet={localSet} />
        <ConfigBody view={view} onSaved={onSaved} />
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
            <p className="ah-muted ah-small" style={{ margin: 0 }}>
              The rules the agents follow in this project, and who set each one.
            </p>
          </div>
          <div className="ah-row" style={{ gap: 8, flexShrink: 0 }}>
            <Button
              icon="pencil"
              disabled={!view}
              onClick={() => {
                setEditing(true);
              }}
            >
              Change my settings
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
            Your settings file (hub.local.json) has a problem, so only the team&apos;s values apply:{" "}
            {view.local_file.problems.join("; ")}
          </Banner>
        )}
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
            <Toast>Saved your settings</Toast>
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
      tip="To come straight here, choose a project in the top bar."
      href={configHome}
      lead={(project) =>
        project.repos.length > 0 ? project.repos.join(" · ") : "No repos declared yet"
      }
    />
  );
}
