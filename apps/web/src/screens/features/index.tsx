import "./features.css";

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Button,
  DerivedLabel,
  GOLDEN_STEP_LABEL,
  EmptyState,
  FacetMenu,
  FilterChip,
  Icon,
  Kbd,
  Popover,
  ProblemError,
  Skeleton,
  StatusBadge,
  Tooltip,
} from "../../components";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useScope } from "../../lib/scope";
import { readStored, writeStored } from "../../lib/storage";
import { useRowKeys } from "../../lib/useRowKeys";
import { useCollectorState } from "../../shell/GlobalStream";
import { typingIn } from "../../shell/goSequence";
import { GOLDEN_PATH_ORDER, GoldenPathBar } from "./GoldenPathBar";
import {
  GROUPS,
  byGroupOrder,
  issueId,
  matchesQuery,
  plainVerdictLine,
  reasonOf,
  type GroupId,
  type Reason,
} from "./groups";
import { AcBar, PHASES, VERDICT_STATUS } from "./parts";
import { useFeatures } from "./queries";

export { issueId } from "./groups";

type Feature = components["schemas"]["FeatureView"];

const FILTERS = ["phase", "repo", "size", "verdict"] as const;
type FilterKey = (typeof FILTERS)[number];
const NO_VERDICT = "none";
const SIZES = ["spike", "bounded", "architectural"] as const;

/** Shipped shows this many rows until the owner asks for more. */
export const SHIPPED_PREVIEW = 5;

const TONE_COLOR: Record<NonNullable<Reason["tone"]>, string> = {
  blocked: "var(--blocked)",
  failed: "var(--failed)",
  waiting: "var(--waiting)",
  done: "var(--done)",
};

const listOf = (raw: string | null): string[] => (raw ? raw.split(",").filter(Boolean) : []);

function matches(f: Feature, key: FilterKey, values: string[]): boolean {
  switch (key) {
    case "phase":
      return values.includes(f.phase);
    case "verdict":
      return values.some((v) => (v === NO_VERDICT ? f.verdict === null : f.verdict === v));
    case "repo":
      return f.repos.some((r) => values.includes(r));
    case "size":
      return f.size !== null && values.includes(f.size);
  }
}

export const featureHref = (f: Pick<Feature, "project" | "slug">) =>
  `/features/${encodeURIComponent(f.project)}/${encodeURIComponent(f.slug)}`;

const COLLAPSED_KEY = "ah.features.collapsed";

function readCollapsed(): Set<GroupId> {
  try {
    const value: unknown = JSON.parse(readStored(COLLAPSED_KEY) ?? "[]");
    const stored: unknown[] = Array.isArray(value) ? value : [];
    return new Set(GROUPS.map((g) => g.id).filter((id) => id !== "needs" && stored.includes(id)));
  } catch {
    return new Set();
  }
}

function useCollapsed(): [Set<GroupId>, (id: GroupId) => void] {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const toggle = (id: GroupId) => {
    const next = new Set(collapsed);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    writeStored(COLLAPSED_KEY, JSON.stringify([...next]));
    setCollapsed(next);
  };
  return [collapsed, toggle];
}

/** `/` focuses the search; Esc in it clears, then leaves. */
function SearchField({ value, onChange }: { value: string; onChange: (q: string) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey || typingIn(event.target)) return;
      event.preventDefault();
      ref.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  return (
    <div className="ah-search ft-search">
      <Icon name="search" size="sm" />
      <input
        ref={ref}
        type="search"
        className="ah-input"
        aria-label="Find features"
        placeholder="Find by name, issue or repo"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          if (value) onChange("");
          else event.currentTarget.blur();
        }}
      />
      {!value && (
        <span className="ft-search-kbd" aria-hidden="true">
          <Kbd>/</Kbd>
        </span>
      )}
    </div>
  );
}

/** The issue ids, mono and neutral: the list has no tracker URLs, so they are not links. */
function IssuesCell({ issues }: { issues: string[] }) {
  const [open, setOpen] = useState(false);
  const [first, ...rest] = issues;
  if (!first) return <span className="ah-subtle">—</span>;
  const firstId = issueId(first);
  return (
    <span className="ah-row" style={{ gap: 4, position: "relative", flexWrap: "nowrap" }}>
      <Tooltip label={firstId === first.trim() ? undefined : first}>
        <span className="ah-mono ah-small" style={{ whiteSpace: "nowrap" }}>
          {firstId}
        </span>
      </Tooltip>
      {rest.length > 0 && (
        <button
          type="button"
          className="ah-btn ah-btn-sm ah-btn-ghost"
          style={{ minHeight: 24, padding: "0 6px" }}
          aria-expanded={open}
          aria-label={`${String(rest.length)} more issue${rest.length === 1 ? "" : "s"}`}
          onClick={(e) => {
            e.stopPropagation();
            setOpen(!open);
          }}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Escape") setOpen(false);
          }}
          onBlur={() => {
            setOpen(false);
          }}
        >
          +{rest.length}
        </button>
      )}
      <Popover
        open={open}
        label="All issues"
        style={{ top: 28, left: 0, minWidth: 140, maxWidth: 360, padding: 8 }}
      >
        <span className="ah-stack" style={{ gap: 4 }}>
          {issues.map((id) => (
            <span key={id} className="ah-mono ah-small" style={{ overflowWrap: "anywhere" }}>
              {id}
            </span>
          ))}
        </span>
      </Popover>
    </span>
  );
}

/** The Evaluate step's own meta when it is not done, so a verdict is not read as the whole feature's. */
function verdictScope(f: Feature): string | null {
  const evaluate = f.golden_path.steps.find((s) => s.name === "evaluate");
  return evaluate && evaluate.state !== "done" ? (evaluate.meta ?? null) : null;
}

function VerdictCell({ f }: { f: Feature }) {
  if (!f.verdict) return <span className="ah-subtle">—</span>;
  const scope = verdictScope(f);
  const line = f.verdict_line ? plainVerdictLine(f.verdict_line) : "From eval.md";
  return (
    <Tooltip label={scope ? `${line} · ${scope}` : line}>
      <span>
        <StatusBadge status={VERDICT_STATUS[f.verdict]} label={f.verdict} />
      </span>
    </Tooltip>
  );
}

function AcCell({ f }: { f: Feature }) {
  if (f.problem || !f.acs) return <span className="ah-subtle">—</span>;
  return <AcBar acs={f.acs} width={96} />;
}

/** Everything the row's cells show, for keyboard and screen-reader users: the bars are not tab stops. */
function rowLabel(f: Feature, reason: Reason): string {
  const acs =
    f.acs && !f.problem
      ? `ACs ${String(f.acs.passing + f.acs.owner_steps)} of ${String(f.acs.total)}`
      : null;
  const issues = f.issues.length ? `issues ${f.issues.map(issueId).join(", ")}` : null;
  return [
    f.slug,
    reason.line,
    `golden path at ${GOLDEN_STEP_LABEL[f.phase]}`,
    acs,
    `verdict ${f.verdict ?? "none"}`,
    issues,
  ]
    .filter(Boolean)
    .join(". ");
}

function FeatureRow({
  f,
  reason,
  showProject,
  onOpen,
}: {
  f: Feature;
  reason: Reason;
  showProject: boolean;
  onOpen: (href: string) => void;
}) {
  const href = featureHref(f) + (reason.doc ? `?doc=${reason.doc}` : "");
  const lineId = `ft-line-${f.project}-${f.slug}`;
  const tags = [
    ...(showProject ? [f.project] : []),
    ...f.repos.filter((r) => r !== f.project),
    ...(f.size ? [f.size] : []),
  ];
  return (
    // The row is one keyboard stop (Enter opens), as the Sessions inbox rows are.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <li
      className="ft-row"
      data-tone={reason.tone ?? undefined}
      data-muted={reason.group === "shipped" || undefined}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      data-nav-row=""
      aria-label={rowLabel(f, reason)}
      onClick={() => {
        onOpen(href);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target === event.currentTarget) onOpen(href);
      }}
    >
      <span
        className="ft-row-lead"
        aria-hidden="true"
        style={reason.tone ? { color: TONE_COLOR[reason.tone] } : undefined}
      >
        {reason.icon && <Icon name={reason.icon} size="sm" />}
      </span>
      <div className="ft-row-main">
        <div className="ft-row-head">
          <Link
            to={href}
            className="ft-row-title"
            title={f.slug}
            aria-describedby={lineId}
            tabIndex={-1}
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            {f.slug}
          </Link>
          {tags.map((tag) => (
            <span key={tag} className="ft-row-tag">
              {tag}
            </span>
          ))}
        </div>
        <div
          id={lineId}
          className="ft-row-line"
          title={reason.line}
          style={
            reason.tone === "failed" || reason.tone === "blocked"
              ? { color: TONE_COLOR[reason.tone] }
              : undefined
          }
        >
          {reason.line}
        </div>
      </div>
      <div className="ft-row-meta">
        <span className="ft-col-issues">
          <IssuesCell issues={f.issues} />
        </span>
        <GoldenPathBar path={f.golden_path} compact />
        <AcCell f={f} />
        <VerdictCell f={f} />
      </div>
    </li>
  );
}

/** The column titles at the top of each group's card; the first card also explains them. */
function ColumnHeads({ withHints }: { withHints: boolean }) {
  const head = (label: string, hint: string, className?: string) => (
    <span className={className}>
      <span className="ah-row" style={{ gap: 4, flexWrap: "nowrap" }}>
        {label}
        {withHints && (
          <Tooltip label={hint}>
            <span
              role="img"
              // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
              tabIndex={0}
              aria-label={`${label}: ${hint}`}
              style={{ display: "inline-flex" }}
            >
              <Icon name="info" size="sm" />
            </span>
          </Tooltip>
        )}
      </span>
    </span>
  );
  return (
    <div className="ft-cols">
      <span aria-hidden="true" />
      <span>Feature</span>
      <div className="ft-cols-meta">
        {head("Issues", "The tracker issues of the feature.", "ft-col-issues")}
        {head(
          "Golden path",
          `One segment per step: ${GOLDEN_PATH_ORDER}. Derived from the record files, the tickets' status read from Linear, and the review and eval records.`,
        )}
        {head(
          "ACs",
          "Acceptance criteria passing, of the total. Owner steps are counted and hatched in amber.",
        )}
        {head("Verdict", "The verdict of the latest eval.md; “—” when there is no eval yet.")}
      </div>
    </div>
  );
}

function Group({
  id,
  rows,
  collapsed,
  onToggle,
  showProject,
  onOpen,
  filtered,
  withHints,
}: {
  withHints: boolean;
  id: GroupId;
  rows: Feature[] | null;
  collapsed: boolean;
  onToggle: () => void;
  showProject: boolean;
  onOpen: (href: string) => void;
  filtered: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = GROUPS.find((g) => g.id === id) ?? GROUPS[0];
  if (!meta) return null;
  const headId = `ft-group-${id}`;
  const open = !collapsed;
  const count = rows === null ? "…" : String(rows.length);
  const preview = id === "shipped" && !expanded && !filtered;
  const shown = rows && preview ? rows.slice(0, SHIPPED_PREVIEW) : rows;
  const hidden = (rows?.length ?? 0) - (shown?.length ?? 0);
  return (
    <section className="ft-group" aria-labelledby={headId} data-group={id}>
      <div className="ft-group-head">
        <h2 className="ft-group-title">
          <button
            type="button"
            id={headId}
            className="ft-group-toggle"
            aria-expanded={open}
            onClick={onToggle}
          >
            <Icon name={open ? "chevron-down" : "chevron-right"} size="sm" />
            {meta.title} · <span className="ft-group-count">{count}</span>
          </button>
        </h2>
        {open && meta.hint && <span className="ft-group-hint">{meta.hint}</span>}
      </div>
      {open &&
        (shown === null ? (
          <ul className="ft-rows ft-card" aria-hidden="true">
            {Array.from({ length: 3 }, (_, i) => (
              <li key={i} className="ft-row" style={{ cursor: "default" }}>
                <span className="ft-row-lead" />
                <div className="ft-row-main">
                  <Skeleton width="40%" />
                  <Skeleton width="60%" />
                </div>
              </li>
            ))}
          </ul>
        ) : shown.length === 0 ? (
          <div className="ft-empty">{meta.empty}</div>
        ) : (
          <>
            <div className="ft-card">
              <ColumnHeads withHints={withHints} />
              <ul className="ft-rows" aria-labelledby={headId}>
                {shown.map((f) => (
                  <FeatureRow
                    key={`${f.project}/${f.slug}`}
                    f={f}
                    reason={reasonOf(f)}
                    showProject={showProject}
                    onOpen={onOpen}
                  />
                ))}
              </ul>
            </div>
            {hidden > 0 && (
              <button
                type="button"
                className="ft-more-link"
                onClick={() => {
                  setExpanded(true);
                }}
              >
                Show {hidden} more shipped feature{hidden === 1 ? "" : "s"}
              </button>
            )}
          </>
        ))}
    </section>
  );
}

/** Features list (spec 17, D23) as an inbox: what needs you, what is moving, what shipped. */
export function FeaturesScreen() {
  const [scope] = useScope();
  const features = useFeatures(scope);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();
  const [collapsed, toggle] = useCollapsed();
  const screenRef = useRef<HTMLDivElement>(null);
  useRowKeys(screenRef);

  const all = features.data?.items ?? [];
  const q = params.get("q") ?? "";
  const active = FILTERS.flatMap((key) => {
    const values = listOf(params.get(key));
    return values.length ? [{ key, values }] : [];
  });
  const filtered = q.trim() !== "" || active.length > 0;
  const rows = all.filter(
    (f) => matchesQuery(f, q) && active.every(({ key, values }) => matches(f, key, values)),
  );
  const byGroup = new Map<GroupId, Feature[]>(GROUPS.map((g) => [g.id, []]));
  for (const f of rows) byGroup.get(reasonOf(f).group)?.push(f);
  for (const list of byGroup.values()) list.sort(byGroupOrder);

  const update = (changes: Partial<Record<FilterKey | "q", string | null>>) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  };
  const toggleValue = (key: FilterKey, id: string) => {
    const values = listOf(params.get(key));
    const next = values.includes(id) ? values.filter((v) => v !== id) : [...values, id];
    update({ [key]: next.join(",") || null });
  };
  const clearAll = () => {
    update({ q: null, phase: null, repo: null, size: null, verdict: null });
  };
  const countFor = (key: FilterKey, test: (f: Feature) => boolean) =>
    all.filter(
      (f) =>
        test(f) &&
        matchesQuery(f, q) &&
        active.every((a) => a.key === key || matches(f, a.key, a.values)),
    ).length;
  const facet = (
    key: FilterKey,
    ids: readonly { id: string; label: string }[],
    count: (id: string) => number,
  ) => {
    const chosen = listOf(params.get(key));
    return ids.map((o) => ({ ...o, count: count(o.id), checked: chosen.includes(o.id) }));
  };
  const repos = [...new Set(all.flatMap((f) => f.repos))].sort();
  const projects = new Set(all.map((f) => f.project));
  const verdicts = listOf(params.get("verdict"));
  const onOpen = (href: string) => void navigate(href);
  // The first open card with rows explains the columns; the others only name them.
  const firstCard = GROUPS.find(
    (g) => !collapsed.has(g.id) && (byGroup.get(g.id)?.length ?? 0) > 0,
  )?.id;

  return (
    <div ref={screenRef} style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <div className="ft-head">
        <h1 className="ah-h1">Features</h1>
        {features.isSuccess && all.length > 0 && (
          <p className="ft-summary">
            {GROUPS.map((g) => {
              const n = all.filter((f) => reasonOf(f).group === g.id).length;
              return (
                <span key={g.id} data-group={g.id}>
                  <b>{n}</b> {g.summary}
                </span>
              );
            })}
            <DerivedLabel how="Grouped from the golden path, derived from the record files, the tickets' status read from Linear, and the review and eval records.">
              derived
            </DerivedLabel>
          </p>
        )}
        {state === "offline" ? (
          <AsOfStamp stale time={fmtClock(asOf, tz)} />
        ) : (
          features.isError &&
          features.data && <AsOfStamp stale time={fmtClock(new Date(features.dataUpdatedAt), tz)} />
        )}
      </div>
      {features.isError && !features.data ? (
        <ProblemError
          title={features.error.title}
          detail={features.error.detail}
          status={features.error.status}
          onRetry={() => void features.refetch()}
        />
      ) : features.isSuccess && all.length === 0 ? (
        <div className="ah-card">
          <EmptyState icon="list-checks" title="No feature records yet." command="/feature AGH-112">
            Features appear when <span className="ah-mono">/feature</span> writes{" "}
            <span className="ah-mono">brain/features/&lt;slug&gt;/spec.md</span> in the hub. Start
            one in a Claude Code session in the hub:
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="ft-toolbar" role="group" aria-label="Filters">
            <SearchField
              value={q}
              onChange={(value) => {
                update({ q: value });
              }}
            />
            <FacetMenu
              label="Step"
              options={facet(
                "phase",
                PHASES.map((p) => ({ id: p.id, label: p.label })),
                (id) => countFor("phase", (f) => f.phase === id),
              )}
              onToggle={(id) => {
                toggleValue("phase", id);
              }}
              onClear={() => {
                update({ phase: null });
              }}
            />
            {repos.length > 1 && (
              <FacetMenu
                label="Repo"
                options={facet(
                  "repo",
                  repos.map((r) => ({ id: r, label: r })),
                  (id) => countFor("repo", (f) => f.repos.includes(id)),
                )}
                onToggle={(id) => {
                  toggleValue("repo", id);
                }}
                onClear={() => {
                  update({ repo: null });
                }}
              />
            )}
            <FacetMenu
              label="Size"
              options={facet(
                "size",
                SIZES.map((s) => ({ id: s, label: s })),
                (id) => countFor("size", (f) => f.size === id),
              )}
              onToggle={(id) => {
                toggleValue("size", id);
              }}
              onClear={() => {
                update({ size: null });
              }}
            />
            {verdicts.map((v) => (
              <FilterChip
                key={v}
                k="Verdict"
                value={v === NO_VERDICT ? "Not evaluated" : v}
                onRemove={() => {
                  toggleValue("verdict", v);
                }}
              />
            ))}
            {filtered && (
              <Button size="sm" variant="ghost" icon="x" onClick={clearAll}>
                Clear filters
              </Button>
            )}
            {filtered && features.isSuccess && (
              <span className="ah-small ah-muted" role="status">
                {rows.length} of {all.length} feature{all.length === 1 ? "" : "s"}
              </span>
            )}
          </div>
          {features.isSuccess && filtered && rows.length === 0 ? (
            <div className="ft-empty">
              No features match these filters.{" "}
              <Button size="sm" variant="ghost" onClick={clearAll}>
                Clear filters
              </Button>
            </div>
          ) : (
            <div className="ft-groups">
              {GROUPS.map((g) => {
                const list = features.isSuccess ? (byGroup.get(g.id) ?? []) : null;
                if (filtered && list?.length === 0) return null;
                const withHints = g.id === firstCard;
                return (
                  <Group
                    key={g.id}
                    id={g.id}
                    rows={list}
                    collapsed={collapsed.has(g.id)}
                    onToggle={() => {
                      toggle(g.id);
                    }}
                    showProject={projects.size > 1}
                    onOpen={onOpen}
                    filtered={filtered}
                    withHints={withHints}
                  />
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
