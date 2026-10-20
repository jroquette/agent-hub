/* The Toolkit catalog (D3, AC-164.14, AC-164.40): the drafts you left open, one tab per kind, a
 * toolbar of search, facets and sort kept in the URL, then the cards of the open tab. */
import "./Skills.css";

import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import {
  AppLink,
  Banner,
  Button,
  EmptyState,
  FacetMenu,
  Icon,
  ProblemError,
  SegmentedControl,
  Skeleton,
  Tabs,
  Time,
} from "../../components";
import type { IconName } from "../../components";
import type { components } from "../../api/schema";
import type { ApiProblem } from "../../lib/api";
import { useNow } from "../../lib/clock";
import {
  KINDS,
  KIND_HELP,
  KIND_LABEL,
  MAX_QUERY_CHARS,
  WORKFLOWS_HELP,
  MODES,
  MODE_LABEL,
  ORIGINS,
  ORIGIN_LABEL,
  facetCounts,
  filterItems,
  filtersFromParams,
  withFilters,
  type CatalogFilters,
  type ItemKind,
} from "./filters";
import { skillRoute as skillRouteOf } from "./queries";
import { newWorkflowRoute } from "./routes";
import {
  ContinueDraft,
  HookStateTags,
  KIND_ICON,
  KIND_NAME,
  OriginText,
  SkillCard,
} from "./SkillCard";
import { WorkflowList } from "../workflows";
import { newDraftRoute, studioRoute } from "./Studio";
import { openDrafts, type StoredDraft } from "./studioDrafts";

type Schemas = components["schemas"];
type SkillCatalog = Schemas["SkillCatalog"];
type ExternalPlugin = Schemas["ExternalPlugin"];
type CatalogItem = Schemas["CatalogItem"];
type WorkflowCatalog = Schemas["WorkflowCatalogView"];

/** The page's sections. The tab is where you are, not a filter: it has its own URL key. */
type Tab = "agents" | "skills" | "hooks" | "workflows";
const TABS: readonly Tab[] = ["agents", "skills", "hooks", "workflows"];
const TAB_KIND: Record<Exclude<Tab, "workflows">, ItemKind> = {
  agents: "agent",
  skills: "skill",
  hooks: "hook",
};
const KIND_TAB: Record<ItemKind, Tab> = { agent: "agents", skill: "skills", hook: "hooks" };
const TAB_KEY = "tab";
const SORT_KEY = "sort";
/** Older links: `?view=workflows` and `?kind=<kind>` name a tab. */
const LEGACY_VIEW_KEY = "view";

type Sort = "name" | "used" | "recent";

function sortFrom(raw: string | null): Sort {
  return raw === "used" || raw === "recent" ? raw : "name";
}

function sorted(items: readonly CatalogItem[], sort: Sort): CatalogItem[] {
  if (sort === "name") return [...items];
  const key = (item: CatalogItem) =>
    sort === "used" ? (item.usage?.count ?? -1) : Date.parse(item.usage?.last_used_at ?? "") || 0;
  return [...items].sort((a, b) => key(b) - key(a) || (a.name < b.name ? -1 : 1));
}

/** A hook's description, "Event (matcher): command", split back into its parts. */
export function hookParts(item: CatalogItem): {
  event: string;
  matcher: string | null;
  command: string | null;
} {
  const match = /^([A-Za-z]+)(?: \(([^)]*)\))?(?:: ([\s\S]*))?$/.exec(item.description ?? "");
  if (!match) return { event: "Other", matcher: null, command: item.description };
  return { event: match[1] ?? "Other", matcher: match[2] ?? null, command: match[3] ?? null };
}

/** The filters as they apply to one kind: Invocation only means something for skills. */
function filtersFor(filters: CatalogFilters, kind: ItemKind): CatalogFilters {
  return { ...filters, kind: [kind], mode: kind === "skill" ? filters.mode : [] };
}

/** Whether a search or a facet narrows this tab (a facet that does not apply to it does not). */
function narrows(filters: CatalogFilters, tab: Tab): boolean {
  if (filters.q.trim() !== "") return true;
  if (tab === "workflows") return false;
  return filters.origin.length > 0 || filters.diag || (tab === "skills" && filters.mode.length > 0);
}

const CLEARED = (filters: CatalogFilters): CatalogFilters => ({
  ...filters,
  q: "",
  kind: [],
  origin: [],
  mode: [],
  diag: false,
});

/** The edit drafts, by the item they change, so its card can offer to continue. */
type DraftsByItem = ReadonlyMap<string, StoredDraft>;
const itemKey = (kind: string, source: string, name: string) => `${kind}/${source}/${name}`;

/** The drafts of this project, read again whenever this browser's storage may have changed. */
function useOpenDrafts(project: string): StoredDraft[] {
  const [drafts, setDrafts] = useState(() => openDrafts(project));
  useEffect(() => {
    const read = () => {
      setDrafts(openDrafts(project));
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") read();
    };
    read();
    window.addEventListener("focus", read);
    window.addEventListener("storage", read);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", read);
      window.removeEventListener("storage", read);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [project]);
  return drafts;
}

const DRAFTS_SHOWN = 3;

/** "Your drafts": work started in the Studio and not published, with how to get back to it. */
function DraftsCard({
  project,
  drafts,
  now,
}: {
  project: string;
  drafts: readonly StoredDraft[];
  now: number;
}) {
  const [all, setAll] = useState(false);
  if (drafts.length === 0) return null;
  const shown = all ? drafts : drafts.slice(0, DRAFTS_SHOWN);
  return (
    <section className="ah-card ah-drafts" aria-labelledby="toolkit-drafts">
      <div className="ah-drafts-head">
        <h2 id="toolkit-drafts" className="ah-h3">
          Your drafts <span className="ah-count">{drafts.length}</span>
        </h2>
        <p className="ah-drafts-note">
          <Icon name="info" size="sm" />
          Kept in this browser only. The files stay in the hub&apos;s{" "}
          <span className="ah-mono">.hub-drafts/</span> folder.
        </p>
      </div>
      <ul className="ah-drafts-list">
        {shown.map((draft) => {
          const kind = KIND_NAME[draft.kind].toLowerCase();
          const verb = draft.target ? `Editing ${kind}` : `New ${kind}`;
          const name = draft.name ?? `untitled ${kind}`;
          return (
            <li key={draft.draftId} className="ah-draft-row">
              <Icon name={draft.target ? "file-pen" : "file-plus"} size="sm" />
              <span className="ah-draft-verb">{verb}</span>
              <AppLink
                href={studioRoute(project, draft.draftId)}
                className="ah-mono ah-draft-name"
                aria-label={`Continue ${draft.target ? "editing" : "new"} ${kind} ${name} in the Studio`}
              >
                {name}
              </AppLink>
              <span className="ah-grow" />
              <span className="ah-draft-when">
                Changed{" "}
                <Time
                  iso={draft.updatedAt}
                  ago={Math.max(0, (now - Date.parse(draft.updatedAt)) / 1000)}
                />
              </span>
            </li>
          );
        })}
      </ul>
      {drafts.length > DRAFTS_SHOWN && (
        <div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setAll(!all);
            }}
          >
            {all ? "Show fewer" : `Show all ${String(drafts.length)} drafts`}
          </Button>
        </div>
      )}
    </section>
  );
}

/** A hook as one row: matcher, command, name, where it comes from and its state. */
function HookRow({
  item,
  project,
  draft,
}: {
  item: CatalogItem;
  project: string;
  draft: StoredDraft | undefined;
}) {
  const parts = hookParts(item);
  const headingId = `skill-card-${item.id}`;
  return (
    <li className="ah-hook-row-item">
      <article className="ah-hook-row" aria-labelledby={headingId}>
        <span className="ah-hook-matcher">{parts.matcher ?? "any"}</span>
        <code className="ah-hook-command" title={parts.command ?? undefined}>
          {parts.command ?? "No command"}
        </code>
        <h3 id={headingId} className="ah-hook-name">
          <AppLink href={skillRouteOf(project, item)}>{item.name}</AppLink>
        </h3>
        <span className="ah-hook-tags">
          <OriginText origin={item.origin} />
          <HookStateTags active={item.active} state={item.state} />
          {item.diagnostics_count > 0 && (
            <span
              className="ah-skill-meta"
              aria-label={`${String(item.diagnostics_count)} diagnostics`}
            >
              <Icon name="circle-alert" size="sm" />
              {item.diagnostics_count}
            </span>
          )}
          {draft && <ContinueDraft href={studioRoute(project, draft.draftId)} name={item.name} />}
        </span>
      </article>
    </li>
  );
}

function HookGroups({
  items,
  project,
  drafts,
}: {
  items: readonly CatalogItem[];
  project: string;
  drafts: DraftsByItem;
}) {
  const events = new Map<string, CatalogItem[]>();
  for (const item of items) {
    const event = hookParts(item).event;
    events.set(event, [...(events.get(event) ?? []), item]);
  }
  return (
    <div className="ah-hook-groups">
      {[...events].map(([event, group]) => (
        <div key={event} className="ah-hook-group">
          <p className="ah-hook-event">
            <span className="ah-mono">{event}</span>
            <span className="ah-count">{group.length}</span>
          </p>
          <ul className="ah-hook-rows">
            {group.map((item) => (
              <HookRow
                key={item.id}
                item={item}
                project={project}
                draft={drafts.get(itemKey(item.kind, item.source, item.name))}
              />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function toggle<T extends string>(values: readonly T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

/** Plugins named by settings but not in this hub: folded, since there is nothing to open. */
function ExternalPlugins({ plugins }: { plugins: readonly ExternalPlugin[] }) {
  return (
    <details className="ah-card ah-skills-plugins-fold">
      <summary className="ah-card-head">
        <Icon name="chevron-right" size="sm" />
        <Icon name="plug" size="sm" />
        <span className="ah-h3">Third-party plugins</span>
        <span className="ah-count">{plugins.length}</span>
      </summary>
      <div className="ah-card-body">
        <p className="ah-small ah-muted" style={{ margin: "0 0 8px" }}>
          Named by the marketplace or <span className="ah-mono">enabledPlugins</span>; their content
          is not in this hub and is never fetched.
        </p>
        <ul className="ah-skills-plugins">
          {plugins.map((plugin) => (
            <li key={`${plugin.name}@${plugin.marketplace ?? ""}`}>
              <span className="ah-mono" style={{ fontWeight: 600 }}>
                {plugin.name}
              </span>
              {plugin.marketplace && (
                <span className="ah-muted">
                  from <span className="ah-mono">{plugin.marketplace}</span>
                </span>
              )}
              <span className="ah-skill-meta">
                <Icon name="pin" size="sm" />
                {plugin.pin ? (
                  <span>
                    pinned <span className="ah-mono">{plugin.pin}</span>
                  </span>
                ) : (
                  "not pinned"
                )}
              </span>
              <span className="ah-skill-tag">
                <Icon name={plugin.enabled ? "circle-check" : "circle-pause"} size="sm" />
                {plugin.enabled ? "Enabled" : "Disabled"}
              </span>
              <span className="ah-muted">content {plugin.content}</span>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

function Notices({ catalog }: { catalog: SkillCatalog }) {
  if (catalog.truncated) {
    return (
      <Banner tone="warning" boxed>
        The catalog is incomplete: the hub is over its bounds, so some items or files are not shown.
        {catalog.notice && <div>{catalog.notice}</div>}
      </Banner>
    );
  }
  return catalog.notice ? (
    <Banner tone="info" boxed>
      {catalog.notice}
    </Banner>
  ) : null;
}

/** The Workflows tab's panel: the project's workflows, or why there are none. */
function WorkflowsPanel({
  project,
  workflows,
  error,
  onRetry,
  query,
}: {
  project: string;
  workflows: WorkflowCatalog | undefined;
  error: ApiProblem | null;
  onRetry: (() => void) | undefined;
  query: string;
}) {
  if (error) {
    return (
      <ProblemError
        title="Could not load workflows"
        detail={error.detail}
        status={error.status}
        onRetry={onRetry}
      />
    );
  }
  if (!workflows) return <Skeleton lines={3} />;
  if (workflows.items.length + workflows.problems.length === 0) {
    return (
      <div className="ah-card">
        <EmptyState
          icon="workflow"
          title="No workflows defined"
          command="./hub sync"
          action={
            <AppLink href={newWorkflowRoute(project)} className="ah-skills-new">
              <Icon name="plus" size="sm" />
              New workflow with Claude
            </AppLink>
          }
        >
          Workflows are YAML files in the hub&apos;s <span className="ah-mono">
            workflows/
          </span>{" "}
          folder; <span className="ah-mono">hub sync</span> installs the default ones. Run it in the
          hub:
        </EmptyState>
      </div>
    );
  }
  return <WorkflowList catalog={workflows} query={query} />;
}

const TAB_ICON: Record<Tab, IconName> = {
  agents: KIND_ICON.agent,
  skills: KIND_ICON.skill,
  hooks: KIND_ICON.hook,
  workflows: "workflow",
};
const TAB_LABEL: Record<Tab, string> = {
  agents: KIND_LABEL.agent,
  skills: KIND_LABEL.skill,
  hooks: KIND_LABEL.hook,
  workflows: "Workflows",
};

/** The workflows a search keeps, as `WorkflowList` filters them. */
function workflowMatches(workflows: WorkflowCatalog, query: string): number {
  const q = query.trim().toLowerCase();
  return workflows.items.filter(
    (item) => !q || `${item.name}\n${item.description ?? ""}`.toLowerCase().includes(q),
  ).length;
}

/** The tab a URL names: `tab`, else an older `view`/`kind`, else the first with matches. */
function tabFrom(params: URLSearchParams, matches: Record<Tab, number | null>): Tab {
  const named = TABS.find((tab) => tab === params.get(TAB_KEY));
  if (named) return named;
  if (params.get(LEGACY_VIEW_KEY) === "workflows") return "workflows";
  const legacyKind = KINDS.find((kind) => (params.get("kind") ?? "").split(",").includes(kind));
  if (legacyKind) return KIND_TAB[legacyKind];
  return TABS.find((tab) => (matches[tab] ?? 0) > 0) ?? "agents";
}

export interface CatalogProps {
  catalog: SkillCatalog;
  /** The project's workflows, for the Workflows tab; absent while they load. */
  workflows?: WorkflowCatalog | undefined;
  /** Why the workflows could not be read, if they could not. */
  workflowsError?: ApiProblem | null | undefined;
  onRetryWorkflows?: (() => void) | undefined;
  /** The current time in ms (default: a clock refreshed every minute). */
  now?: number | undefined;
}

/** The catalog of one project; tab, search, facets and sort live in the URL query. */
export function Catalog({
  catalog,
  workflows,
  workflowsError = null,
  onRetryWorkflows,
  now,
}: CatalogProps) {
  const clock = useNow(60_000);
  const at = now ?? clock;
  const [params, setParams] = useSearchParams();
  const drafts = useOpenDrafts(catalog.project);
  const filters = filtersFromParams(params);
  const sort = sortFrom(params.get(SORT_KEY));
  const setFilters = (next: CatalogFilters) => {
    setParams((current) => withFilters(current, { ...next, kind: [] }), { replace: true });
  };

  const draftsByItem: DraftsByItem = new Map(
    drafts.flatMap((draft) =>
      draft.target
        ? [[itemKey(draft.target.kind, draft.target.source, draft.target.name), draft] as const]
        : [],
    ),
  );
  const draftsCard = <DraftsCard project={catalog.project} drafts={drafts} now={at} />;

  if (catalog.items.length === 0 && (workflows?.items.length ?? 0) === 0) {
    return (
      <div className="ah-stack" style={{ gap: 16 }}>
        {draftsCard}
        <div className="ah-card">
          <EmptyState
            icon="book-open"
            title={catalog.notice ?? "No agents, skills or hooks in this hub."}
            command="./hub sync"
          >
            Agents, skills and hooks come from <span className="ah-mono">plugin/</span> and{" "}
            <span className="ah-mono">.claude/</span>, which{" "}
            <span className="ah-mono">hub sync</span> writes. Run it in the hub:
          </EmptyState>
        </div>
      </div>
    );
  }

  const matches: Record<Tab, number | null> = {
    agents: filterItems(catalog.items, filtersFor(filters, "agent")).length,
    skills: filterItems(catalog.items, filtersFor(filters, "skill")).length,
    hooks: filterItems(catalog.items, filtersFor(filters, "hook")).length,
    workflows: workflows ? workflowMatches(workflows, filters.q) : null,
  };
  const tab = tabFrom(params, matches);
  const kind = tab === "workflows" ? null : TAB_KIND[tab];
  const onTab = (id: string) => {
    const next = TABS.find((value) => value === id);
    if (!next || next === tab) return;
    // A tab change is a navigation: Back returns to the previous tab.
    setParams((current) => {
      const updated = new URLSearchParams(current);
      updated.delete(LEGACY_VIEW_KEY);
      updated.delete("kind");
      updated.set(TAB_KEY, next);
      return updated;
    });
  };
  const setSort = (id: string) => {
    setParams(
      (current) => {
        const updated = new URLSearchParams(current);
        if (id === "used" || id === "recent") updated.set(SORT_KEY, id);
        else updated.delete(SORT_KEY);
        return updated;
      },
      { replace: true },
    );
  };

  const all = kind ? catalog.items.filter((item) => item.kind === kind) : [];
  const items = kind ? sorted(filterItems(catalog.items, filtersFor(filters, kind)), sort) : [];
  const counts = kind ? facetCounts(catalog.items, filtersFor(filters, kind)) : null;
  const filtered = narrows(filters, tab);
  const noun = kind ? KIND_LABEL[kind].toLowerCase() : "workflows";
  const unit = kind && all.length === 1 ? KIND_NAME[kind].toLowerCase() : noun;
  const clearAll = () => {
    setFilters(CLEARED(filters));
  };
  const otherTabs = TABS.filter((other) => other !== tab && (matches[other] ?? 0) > 0);

  return (
    <div className="ah-stack" style={{ gap: 16 }}>
      <Notices catalog={catalog} />
      {draftsCard}
      <div className="ah-toolkit">
        <Tabs
          label="Kinds in the toolkit"
          value={tab}
          onChange={onTab}
          tabs={TABS.map((id) => ({
            id,
            label: TAB_LABEL[id],
            icon: TAB_ICON[id],
            count: matches[id] ?? undefined,
          }))}
        />
        <div className="ah-toolkit-panel" role="tabpanel" aria-label={TAB_LABEL[tab]}>
          <div className="ah-row ah-wrap ah-skills-toolbar">
            <div className="ah-search ah-skills-search">
              <Icon name="search" size="sm" />
              <input
                type="search"
                className="ah-input"
                aria-label={`Search ${noun}`}
                placeholder={`Search ${noun} by name or description`}
                maxLength={MAX_QUERY_CHARS}
                value={filters.q}
                onChange={(event) => {
                  setFilters({ ...filters, q: event.target.value });
                }}
              />
            </div>
            {counts && (
              <>
                <FacetMenu
                  label="Origin"
                  options={ORIGINS.map((origin) => ({
                    id: origin,
                    label: ORIGIN_LABEL[origin],
                    count: counts.origin[origin],
                    checked: filters.origin.includes(origin),
                  }))}
                  onToggle={(id) => {
                    const origin = ORIGINS.find((value) => value === id);
                    if (origin) setFilters({ ...filters, origin: toggle(filters.origin, origin) });
                  }}
                  onClear={() => {
                    setFilters({ ...filters, origin: [] });
                  }}
                />
                {kind === "skill" && (
                  <FacetMenu
                    label="Invocation"
                    options={MODES.map((mode) => ({
                      id: mode,
                      label: MODE_LABEL[mode],
                      count: counts.mode[mode],
                      checked: filters.mode.includes(mode),
                    }))}
                    onToggle={(id) => {
                      const mode = MODES.find((value) => value === id);
                      if (mode) setFilters({ ...filters, mode: toggle(filters.mode, mode) });
                    }}
                    onClear={() => {
                      setFilters({ ...filters, mode: [] });
                    }}
                  />
                )}
                <FacetMenu
                  label="Diagnostics"
                  options={[
                    {
                      id: "1",
                      label: "Has diagnostics",
                      count: counts.diag["1"],
                      checked: filters.diag,
                    },
                  ]}
                  onToggle={() => {
                    setFilters({ ...filters, diag: !filters.diag });
                  }}
                  onClear={() => {
                    setFilters({ ...filters, diag: false });
                  }}
                />
              </>
            )}
            {filtered && (
              <Button size="sm" variant="ghost" icon="x" onClick={clearAll}>
                Clear filters
              </Button>
            )}
            <span className="ah-grow" />
            {filtered && kind && (
              <p className="ah-skills-count" role="status">
                {items.length} of {all.length} {unit}
              </p>
            )}
            {kind !== null && kind !== "hook" && (
              <SegmentedControl
                label="Sort"
                value={sort}
                onChange={setSort}
                options={[
                  { id: "name", label: "A–Z" },
                  { id: "used", label: "Most used" },
                  { id: "recent", label: "Last used" },
                ]}
              />
            )}
          </div>
          <p className="ah-skills-group-help">{kind ? KIND_HELP[kind] : WORKFLOWS_HELP}</p>
          {kind === null ? (
            <WorkflowsPanel
              project={catalog.project}
              workflows={workflows}
              error={workflowsError}
              onRetry={onRetryWorkflows}
              query={filters.q}
            />
          ) : all.length === 0 ? (
            <div className="ah-card">
              <EmptyState
                icon={KIND_ICON[kind]}
                title={`No ${noun} in this hub yet.`}
                action={
                  <AppLink href={newDraftRoute(catalog.project, kind)} className="ah-skills-new">
                    <Icon name="plus" size="sm" />
                    New {KIND_NAME[kind].toLowerCase()} with Claude
                  </AppLink>
                }
              >
                {KIND_LABEL[kind]} come from <span className="ah-mono">plugin/</span> and{" "}
                <span className="ah-mono">.claude/</span>, which{" "}
                <span className="ah-mono">hub sync</span> writes, or you can write one with Claude.
              </EmptyState>
            </div>
          ) : items.length === 0 ? (
            <div className="ah-card ah-pad ah-small ah-toolkit-nomatch">
              <p style={{ margin: 0 }}>
                No {noun} match these filters.{" "}
                <Button size="sm" variant="ghost" onClick={clearAll}>
                  Clear filters
                </Button>
              </p>
              {otherTabs.length > 0 && (
                <p className="ah-muted" style={{ margin: 0 }}>
                  Matches in other tabs:{" "}
                  {otherTabs.map((other, index) => (
                    <span key={other}>
                      {index > 0 && ", "}
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          onTab(other);
                        }}
                      >
                        {TAB_LABEL[other]} ({matches[other]})
                      </Button>
                    </span>
                  ))}
                </p>
              )}
            </div>
          ) : kind === "hook" ? (
            <HookGroups items={items} project={catalog.project} drafts={draftsByItem} />
          ) : (
            <ul className="ah-skills-grid">
              {items.map((item) => {
                const draft = draftsByItem.get(itemKey(item.kind, item.source, item.name));
                return (
                  <SkillCard
                    key={item.id}
                    item={item}
                    project={catalog.project}
                    now={at}
                    usageDays={catalog.usage_days}
                    draftHref={draft ? studioRoute(catalog.project, draft.draftId) : undefined}
                  />
                );
              })}
            </ul>
          )}
        </div>
      </div>
      {catalog.external_plugins.length > 0 && (
        <ExternalPlugins plugins={catalog.external_plugins} />
      )}
    </div>
  );
}
