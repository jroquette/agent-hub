import "./features.css";

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Button,
  DerivedLabel,
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
      aria-label={`${f.slug}. ${reason.line}`}
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
            reason.tone && reason.tone !== "done" ? { color: TONE_COLOR[reason.tone] } : undefined
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

function ColumnHeads() {
  const head = (label: string, hint: string, className?: string) => (
    <Tooltip label={hint}>
      <span className={className}>{label}</span>
    </Tooltip>
  );
  return (
    <div className="ft-cols" aria-hidden="true">
      <span />
      <span />
      <div className="ft-cols-meta">
        {head("Issues", "The tracker issues of the feature.", "ft-col-issues")}
        {head("Golden path", `One segment per step: ${GOLDEN_PATH_ORDER}.`)}
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
}: {
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
      <h2 className="ft-group-head">
        <button
          type="button"
          id={headId}
          className="ft-group-toggle"
          aria-expanded={open}
          onClick={onToggle}
        >
          <Icon name={open ? "chevron-down" : "chevron-right"} size="sm" />
          {`${meta.title} · ${count}`}
        </button>
        {open && meta.hint && <span className="ft-group-hint">{meta.hint}</span>}
      </h2>
      {open &&
        (shown === null ? (
          <ul className="ft-rows" aria-hidden="true">
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

  return (
    <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <div className="ah-row ah-wrap">
        <h1 className="ah-h1">Features</h1>
        {state === "offline" && <AsOfStamp stale time={fmtClock(asOf, tz)} />}
      </div>
      {features.isError ? (
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
                (id) => all.filter((f) => f.phase === id).length,
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
                  (id) => all.filter((f) => f.repos.includes(id)).length,
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
                (id) => all.filter((f) => f.size === id).length,
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
            <span className="ah-grow" />
            {filtered && features.isSuccess && (
              <span className="ah-small ah-muted" role="status">
                {rows.length} of {all.length} feature{all.length === 1 ? "" : "s"}
              </span>
            )}
            <DerivedLabel how="Grouped from the golden path, derived from the record files, the tickets' status read from Linear, and the review and eval records.">
              derived
            </DerivedLabel>
          </div>
          <ColumnHeads />
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
