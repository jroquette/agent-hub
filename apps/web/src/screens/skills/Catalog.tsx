/* The Skills catalog (D3, AC-164.14, AC-164.40): search, facets kept in the URL, cards by kind. */
import "./Skills.css";

import { useSearchParams } from "react-router";

import { Banner, Button, EmptyState, FilterRail, Icon, Tabs } from "../../components";
import type { Facet } from "../../components";
import type { components } from "../../api/schema";
import { useNow } from "../../lib/clock";
import {
  KINDS,
  KIND_HELP,
  KIND_LABEL,
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
} from "./filters";
import { KIND_ICON, SkillCard } from "./SkillCard";

type Schemas = components["schemas"];
type SkillCatalog = Schemas["SkillCatalog"];
type ExternalPlugin = Schemas["ExternalPlugin"];

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
  const tabs = [
    { id: "all", label: "All", count: allCount },
    ...KINDS.map((kind) => ({
      id: kind,
      label: KIND_LABEL[kind],
      icon: KIND_ICON[kind],
      count: counts.kind[kind],
    })),
  ];
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
          <Tabs tabs={tabs} value={tab} onChange={onTab} label="Kind" />
          <div className="ah-row ah-wrap">
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
              const group = items.filter((item) => item.kind === kind);
              if (group.length === 0) return null;
              const headingId = `skills-group-${kind}`;
              return (
                <section key={kind} className="ah-skills-group" aria-labelledby={headingId}>
                  <h2 id={headingId} className="ah-h3">
                    <Icon name={KIND_ICON[kind]} size="sm" />
                    {KIND_LABEL[kind]} <span className="ah-count">{group.length}</span>
                  </h2>
                  <p className="ah-skills-group-help">{KIND_HELP[kind]}</p>
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
