/* The Skills catalog (D3, AC-164.14, AC-164.40): search, facets kept in the URL, cards by kind. */
import "./Skills.css";

import { useState } from "react";
import { useSearchParams } from "react-router";

import {
  AppLink,
  Banner,
  Button,
  EmptyState,
  FilterRail,
  Icon,
  SegmentedControl,
  Time,
} from "../../components";
import type { Facet, IconName } from "../../components";
import type { components } from "../../api/schema";
import { useNow } from "../../lib/clock";
import {
  KINDS,
  KIND_HELP,
  KIND_LABEL,
  KIND_SUMMARY,
  MAX_QUERY_CHARS,
  MODES,
  MODE_LABEL,
  NO_FILTERS,
  ORIGINS,
  ORIGIN_LABEL,
  facetCounts,
  filterItems,
  filtersFromParams,
  hasFilters,
  withFilters,
  type CatalogFilters,
  type ItemKind,
} from "./filters";
import { skillRoute as skillRouteOf } from "./queries";
import { HookStateTags, KIND_ICON, KIND_NAME, OriginBadge, SkillCard } from "./SkillCard";
import { newDraftRoute, studioRoute } from "./Studio";
import { openDrafts } from "./studioDrafts";

type Schemas = components["schemas"];
type SkillCatalog = Schemas["SkillCatalog"];
type ExternalPlugin = Schemas["ExternalPlugin"];
type CatalogItem = Schemas["CatalogItem"];

type Sort = "name" | "used" | "recent";

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

/** The kinds as selectable tiles: what each is, how many there are, how many were used. */
function KindTiles({
  value,
  counts,
  used,
  onChange,
}: {
  value: string;
  counts: Record<ItemKind | "all", number>;
  used: Record<ItemKind | "all", number>;
  onChange: (id: string) => void;
}) {
  const tiles: { id: ItemKind | "all"; label: string; icon: IconName; line: string }[] = [
    { id: "all", label: "All", icon: "layers", line: "Everything this hub's agents can do" },
    ...KINDS.map((kind) => ({
      id: kind,
      label: KIND_LABEL[kind],
      icon: KIND_ICON[kind],
      line: KIND_SUMMARY[kind],
    })),
  ];
  return (
    <div className="ah-kind-tiles" role="tablist" aria-label="Kind">
      {tiles.map((tile) => (
        <button
          key={tile.id}
          type="button"
          role="tab"
          className="ah-kind-tile"
          aria-selected={tile.id === value}
          aria-label={`${tile.label} ${String(counts[tile.id])}`}
          aria-describedby={`kind-tile-${tile.id}`}
          onClick={() => {
            onChange(tile.id);
          }}
        >
          <span className="ah-kind-badge" data-kind={tile.id} aria-hidden="true">
            <Icon name={tile.icon} size="sm" />
          </span>
          <span className="ah-kind-tile-text">
            <span className="ah-kind-tile-label">
              {tile.label} <span className="ah-kind-tile-count">{counts[tile.id]}</span>
            </span>
            <span className="ah-kind-tile-line" id={`kind-tile-${tile.id}`}>
              {tile.line}
            </span>
            {tile.id !== "hook" && (
              <span className="ah-kind-tile-used">{used[tile.id]} used in 30 days</span>
            )}
          </span>
        </button>
      ))}
    </div>
  );
}

/** A hook as one row: event, matcher, command, where it comes from and its state. */
function HookRow({ item, project }: { item: CatalogItem; project: string }) {
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
          <OriginBadge origin={item.origin} />
          <HookStateTags active={item.active} state={item.state} />
          {item.diagnostics_count > 0 && (
            <span className="ah-skill-meta">
              <Icon name="circle-alert" size="sm" />
              {item.diagnostics_count}
            </span>
          )}
        </span>
      </article>
    </li>
  );
}

function HookGroups({ items, project }: { items: readonly CatalogItem[]; project: string }) {
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
              <HookRow key={item.id} item={item} project={project} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** The drafts this browser started in the Studio and did not publish. */
function DraftsInProgress({ project, now }: { project: string; now: number }) {
  const [drafts] = useState(() => openDrafts(project));
  if (drafts.length === 0) return null;
  return (
    <section className="ah-drafts" aria-labelledby="skills-drafts">
      <h2 id="skills-drafts" className="ah-studio-label">
        Drafts in progress
      </h2>
      <ul className="ah-drafts-list">
        {drafts.map((draft) => (
          <li key={draft.draftId}>
            <AppLink href={studioRoute(project, draft.draftId)} className="ah-draft-pill">
              <span className="ah-kind-badge" data-kind={draft.kind} aria-hidden="true">
                <Icon name={KIND_ICON[draft.kind]} size="sm" />
              </span>
              {draft.target && <span className="ah-muted">editing</span>}
              <span className="ah-mono">{draft.name ?? `untitled ${draft.kind}`}</span>
              <span className="ah-muted">
                <Time
                  iso={draft.updatedAt}
                  ago={Math.max(0, (now - Date.parse(draft.updatedAt)) / 1000)}
                />
              </span>
            </AppLink>
          </li>
        ))}
      </ul>
    </section>
  );
}

function toggle<T extends string>(values: readonly T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

function ExternalPlugins({ plugins }: { plugins: readonly ExternalPlugin[] }) {
  return (
    <section className="ah-skills-group" aria-labelledby="skills-external">
      <h2 id="skills-external" className="ah-h3">
        <Icon name="plug" size="sm" />
        Third-party plugins
      </h2>
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
    </section>
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

export interface CatalogProps {
  catalog: SkillCatalog;
  /** The current time in ms (default: a clock refreshed every minute). */
  now?: number | undefined;
}

/** The catalog of one project; search and facets live in the URL query, updated in place. */
export function Catalog({ catalog, now }: CatalogProps) {
  const clock = useNow(60_000);
  const [params, setParams] = useSearchParams();
  const [sort, setSort] = useState<Sort>("name");
  const filters = filtersFromParams(params);
  const setFilters = (next: CatalogFilters) => {
    setParams((current) => withFilters(current, next), { replace: true });
  };

  if (catalog.items.length === 0) {
    return (
      <div className="ah-card">
        <EmptyState
          icon="book-open"
          title={catalog.notice ?? "No skills, agents or hooks in this hub."}
          command="./hub sync"
        >
          Skills, agents and hooks come from <span className="ah-mono">plugin/</span> and{" "}
          <span className="ah-mono">.claude/</span>, which <span className="ah-mono">hub sync</span>{" "}
          writes. Run it in the hub:
        </EmptyState>
      </div>
    );
  }

  const items = filterItems(catalog.items, filters);
  const counts = facetCounts(catalog.items, filters);
  // The kind is picked with tabs above the cards: one kind, or all of them. A URL naming
  // several kinds (an older link) reads as All, and picking a tab replaces it.
  const tab = filters.kind.length === 1 ? (filters.kind[0] ?? "all") : "all";
  const allCount = KINDS.reduce((sum, kind) => sum + counts.kind[kind], 0);
  const tileCounts = { all: allCount, ...counts.kind };
  const usedOf = (kind?: ItemKind) =>
    catalog.items.filter(
      (item) => (kind ? item.kind === kind : true) && (item.usage?.count ?? 0) > 0,
    ).length;
  const used = { all: usedOf(), skill: usedOf("skill"), agent: usedOf("agent"), hook: 0 };
  const onTab = (id: string) => {
    const kind = KINDS.find((value) => value === id);
    setFilters({ ...filters, kind: kind ? [kind] : [] });
  };
  const facets: Facet[] = [
    {
      id: "origin",
      title: "Origin",
      options: ORIGINS.map((origin) => ({
        id: origin,
        label: ORIGIN_LABEL[origin],
        count: counts.origin[origin],
        checked: filters.origin.includes(origin),
      })),
    },
    {
      id: "mode",
      title: "Invocation",
      options: MODES.map((mode) => ({
        id: mode,
        label: MODE_LABEL[mode],
        count: counts.mode[mode],
        checked: filters.mode.includes(mode),
      })),
    },
    {
      id: "diag",
      title: "Diagnostics",
      options: [
        { id: "1", label: "Has diagnostics", count: counts.diag["1"], checked: filters.diag },
      ],
    },
  ];
  const onToggle = (facet: string, option: string) => {
    if (facet === "origin") {
      const origin = ORIGINS.find((value) => value === option);
      if (origin) setFilters({ ...filters, origin: toggle(filters.origin, origin) });
    } else if (facet === "mode") {
      const mode = MODES.find((value) => value === option);
      if (mode) setFilters({ ...filters, mode: toggle(filters.mode, mode) });
    } else setFilters({ ...filters, diag: !filters.diag });
  };
  const filtered = hasFilters(filters);

  return (
    <div className="ah-stack" style={{ gap: 16 }}>
      <Notices catalog={catalog} />
      <div className="ah-skills-layout">
        <FilterRail
          facets={facets}
          onToggle={onToggle}
          footer={
            filtered ? (
              <Button
                size="sm"
                variant="ghost"
                icon="x"
                onClick={() => {
                  setFilters(NO_FILTERS);
                }}
              >
                Clear filters
              </Button>
            ) : null
          }
        />
        <div className="ah-skills-main">
          <DraftsInProgress project={catalog.project} now={now ?? clock} />
          <KindTiles value={tab} counts={tileCounts} used={used} onChange={onTab} />
          <div className="ah-row ah-wrap ah-skills-toolbar">
            <div className="ah-search ah-skills-search ah-grow">
              <Icon name="search" size="sm" />
              <input
                type="search"
                className="ah-input"
                aria-label="Search skills, agents and hooks"
                placeholder="Search by name or description"
                maxLength={MAX_QUERY_CHARS}
                value={filters.q}
                onChange={(event) => {
                  setFilters({ ...filters, q: event.target.value });
                }}
              />
            </div>
            <SegmentedControl
              label="Sort"
              value={sort}
              onChange={(id) => {
                setSort(id === "used" || id === "recent" ? id : "name");
              }}
              options={[
                { id: "name", label: "A–Z" },
                { id: "used", label: "Most used" },
                { id: "recent", label: "Recent" },
              ]}
            />
            <p className="ah-skills-count" role="status" style={{ margin: 0 }}>
              Showing {items.length} of {catalog.items.length}
            </p>
          </div>
          {items.length === 0 ? (
            <div className="ah-card ah-pad ah-small ah-muted">
              No items match these filters.{" "}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setFilters(NO_FILTERS);
                }}
              >
                Clear filters
              </Button>
            </div>
          ) : (
            KINDS.map((kind) => {
              const group = sorted(
                items.filter((item) => item.kind === kind),
                sort,
              );
              if (group.length === 0) return null;
              const headingId = `skills-group-${kind}`;
              return (
                <section key={kind} className="ah-skills-group" aria-labelledby={headingId}>
                  <div className="ah-skills-group-head">
                    <div className="ah-grow">
                      <h2 id={headingId} className="ah-h3">
                        <Icon name={KIND_ICON[kind]} size="sm" />
                        {KIND_LABEL[kind]} <span className="ah-count">{group.length}</span>
                      </h2>
                      <p className="ah-skills-group-help">{KIND_HELP[kind]}</p>
                    </div>
                    <AppLink href={newDraftRoute(catalog.project, kind)} className="ah-skills-new">
                      <Icon name="plus" size="sm" />
                      New {KIND_NAME[kind].toLowerCase()} with Claude
                    </AppLink>
                  </div>
                  {kind === "hook" ? (
                    <HookGroups items={group} project={catalog.project} />
                  ) : (
                    <ul className="ah-skills-grid">
                      {group.map((item) => (
                        <SkillCard
                          key={item.id}
                          item={item}
                          project={catalog.project}
                          now={now ?? clock}
                          usageDays={catalog.usage_days}
                        />
                      ))}
                    </ul>
                  )}
                </section>
              );
            })
          )}
          {catalog.external_plugins.length > 0 && (
            <ExternalPlugins plugins={catalog.external_plugins} />
          )}
        </div>
      </div>
    </div>
  );
}
