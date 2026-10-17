import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  DataTable,
  DerivedLabel,
  EmptyState,
  Icon,
  Popover,
  ProblemError,
  Skeleton,
  StatusBadge,
  Tooltip,
} from "../../components";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useScope } from "../../lib/scope";
import { useCollectorState } from "../../shell/GlobalStream";
import { GOLDEN_PATH_ORDER, GoldenPathBar, waitsOnOwner } from "./GoldenPathBar";
import { AcBar, FilterMenu, PHASES, VERDICT_STATUS, phaseIndex } from "./parts";
import { useFeatures } from "./queries";

type Feature = components["schemas"]["FeatureView"];

const FILTERS = ["phase", "verdict", "repo", "size"] as const;
type FilterKey = (typeof FILTERS)[number];

const NO_VERDICT = "none";

function matches(f: Feature, key: FilterKey, value: string): boolean {
  switch (key) {
    case "phase":
      return f.phase === value;
    case "verdict":
      return value === NO_VERDICT ? f.verdict === null : f.verdict === value;
    case "repo":
      return f.repos.includes(value);
    case "size":
      return f.size === value;
  }
}

const shipped = (f: Feature) => f.phase === "shipped";

/** In progress first, furthest along first, shipped last (spec 17). */
function byProgress(a: Feature, b: Feature): number {
  return (
    Number(shipped(a)) - Number(shipped(b)) ||
    phaseIndex(b.phase) - phaseIndex(a.phase) ||
    a.slug.localeCompare(b.slug)
  );
}

const ISSUE_ID = /^[A-Z][A-Z0-9]*-\d+/;

/** The tracker id at the head of an issue entry, so a note after it ("AGH-200 (provisional …)") never widens the column. */
export const issueId = (raw: string): string => ISSUE_ID.exec(raw.trim())?.[0] ?? raw.trim();

/** The issue ids, mono and neutral: the list has no tracker URLs, so they are not links. */
function IssuesCell({ issues }: { issues: string[] }) {
  const [open, setOpen] = useState(false);
  const [first, ...rest] = issues;
  if (!first) return <span className="ah-subtle">—</span>;
  const firstId = issueId(first);
  return (
    <span className="ah-row" style={{ gap: 4, position: "relative", flexWrap: "nowrap" }}>
      <Tooltip label={firstId === first.trim() ? undefined : first}>
        <span
          className="ah-mono ah-small"
          style={{ whiteSpace: "nowrap" }}
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={firstId === first.trim() ? undefined : 0}
        >
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

/** The eval's verdict line without its markdown, for the badge's tooltip. */
const plainVerdictLine = (line: string) => line.replace(/\*\*|`/g, "").trim();

export const featureHref = (f: Pick<Feature, "project" | "slug">) =>
  `/features/${encodeURIComponent(f.project)}/${encodeURIComponent(f.slug)}`;

function AcCell({ f }: { f: Feature }) {
  if (f.problem) {
    return (
      <Tooltip label={`${f.problem}. Fix it in a hub PR.`}>
        <span className="ah-row" style={{ gap: 4 }}>
          <Icon name="octagon-x" size="sm" style={{ color: "var(--blocked)" }} title={f.problem} />
          <span className="ah-subtle">—</span>
        </span>
      </Tooltip>
    );
  }
  if (!f.acs) return <span className="ah-subtle">—</span>;
  return <AcBar acs={f.acs} />;
}

/** Features list (spec 17, D23): golden path, ACs and verdict of each feature record. */
export function FeaturesScreen() {
  const [scope] = useScope();
  const features = useFeatures(scope);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();

  const all = [...(features.data?.items ?? [])].sort(byProgress);
  const active = FILTERS.flatMap((key) => {
    const value = params.get(key);
    return value === null ? [] : [{ key, value }];
  });
  const rows = all.filter((f) => active.every(({ key, value }) => matches(f, key, value)));
  const shippedCount = all.filter(shipped).length;
  const waitingCount = all.filter((f) => waitsOnOwner(f.golden_path)).length;
  const inProgress = all.length - shippedCount - waitingCount;
  const setFilter = (key: FilterKey, value: string | null) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value === null) next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );
  };
  const clearFilters = () => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const key of FILTERS) next.delete(key);
        return next;
      },
      { replace: true },
    );
  };
  const repos = [...new Set(all.flatMap((f) => f.repos))].sort();

  return (
    <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <div className="ah-row ah-wrap">
        <h1 className="ah-h1">Features</h1>
        {state === "offline" && <AsOfStamp stale time={fmtClock(asOf, tz)} />}
        <span className="ah-grow" />
        <FilterMenu
          label="Phase"
          value={params.get("phase")}
          options={PHASES.map((p) => ({ id: p.id, label: p.label }))}
          onChange={(v) => {
            setFilter("phase", v);
          }}
        />
        <FilterMenu
          label="Verdict"
          value={params.get("verdict")}
          options={[
            { id: "SHIP", label: "SHIP" },
            { id: "SHIP-WITH-OWNER-STEPS", label: "SHIP-WITH-OWNER-STEPS" },
            { id: "NO-SHIP", label: "NO-SHIP" },
            { id: NO_VERDICT, label: "Not evaluated" },
          ]}
          onChange={(v) => {
            setFilter("verdict", v);
          }}
        />
        <FilterMenu
          label="Repo"
          value={params.get("repo")}
          options={repos.map((r) => ({ id: r, label: r }))}
          onChange={(v) => {
            setFilter("repo", v);
          }}
        />
        <FilterMenu
          label="Size"
          value={params.get("size")}
          options={["spike", "bounded", "architectural"].map((s) => ({ id: s, label: s }))}
          onChange={(v) => {
            setFilter("size", v);
          }}
        />
      </div>
      <div className="ah-small ah-muted" style={{ marginBottom: 8 }}>
        {features.isPending ? (
          <Skeleton width={280} />
        ) : features.isSuccess && all.length > 0 ? (
          <span>
            <b style={{ color: "var(--text)" }}>
              {all.length} feature{all.length === 1 ? "" : "s"}
            </b>{" "}
            {waitingCount > 0 && (
              <>
                {" · "}
                <b style={{ color: "var(--text)" }}>
                  <Icon name="hand" size="sm" style={{ verticalAlign: "-3px" }} /> {waitingCount}{" "}
                  waiting for you
                </b>
              </>
            )}{" "}
            · {inProgress} in progress · {shippedCount} shipped · furthest along first
          </span>
        ) : null}
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
          <DataTable<Feature>
            caption="Features"
            rowKey={(f) => `${f.project}/${f.slug}`}
            rows={rows}
            loading={features.isPending}
            onRowClick={(f) => void navigate(featureHref(f))}
            empty={
              <div className="ah-small ah-muted" style={{ padding: 16 }}>
                No features match these filters.{" "}
                <button
                  type="button"
                  className="ah-btn ah-btn-sm ah-btn-ghost"
                  onClick={clearFilters}
                >
                  Clear filters
                </button>
              </div>
            }
            columns={[
              {
                id: "slug",
                label: "Feature",
                width: "26%",
                render: (f) => (
                  <span className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
                    <Link
                      to={featureHref(f)}
                      className="ah-mono"
                      style={{ fontWeight: 500, overflowWrap: "anywhere" }}
                      onClick={(e) => {
                        e.stopPropagation();
                      }}
                    >
                      {f.slug}
                    </Link>
                    <span className="ah-small ah-subtle">
                      {f.project}
                      {f.repos.length && f.repos[0] !== f.project ? ` · ${f.repos.join(", ")}` : ""}
                    </span>
                  </span>
                ),
              },
              {
                id: "issues",
                label: "Issues",
                width: 140,
                render: (f) => <IssuesCell issues={f.issues} />,
              },
              {
                id: "size",
                label: "Size",
                width: 120,
                render: (f) =>
                  f.size ? (
                    <span className="ah-fm-chip">{f.size}</span>
                  ) : (
                    <span className="ah-subtle">—</span>
                  ),
              },
              {
                id: "phase",
                label: (
                  <span className="ah-row" style={{ gap: 4 }}>
                    Golden path
                    <DerivedLabel how="Derived from the record files, the tickets' status read from Linear, and the review and eval records.">
                      derived
                    </DerivedLabel>
                  </span>
                ),
                hint: `One segment per step, left to right: ${GOLDEN_PATH_ORDER}. Focus or hover the bar for each step's state.`,
                render: (f) => <GoldenPathBar path={f.golden_path} />,
              },
              {
                id: "acs",
                label: "ACs",
                width: 180,
                hint: "Acceptance criteria passing, of the total. A full bar never hides a manual step: owner steps are counted and hatched in amber.",
                render: (f) => <AcCell f={f} />,
              },
              {
                id: "verdict",
                label: "Verdict",
                width: 200,
                hint: "The verdict of the latest eval.md; “—” when the feature has no eval yet.",
                render: (f) => {
                  if (!f.verdict) return <span className="ah-subtle">—</span>;
                  const scope = verdictScope(f);
                  return (
                    <span className="ah-stack" style={{ gap: 2, alignItems: "flex-start" }}>
                      <Tooltip
                        label={f.verdict_line ? plainVerdictLine(f.verdict_line) : "From eval.md"}
                      >
                        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
                        <span tabIndex={0}>
                          <StatusBadge status={VERDICT_STATUS[f.verdict]} label={f.verdict} />
                        </span>
                      </Tooltip>
                      {scope && <span className="ah-small ah-subtle">{scope}</span>}
                    </span>
                  );
                },
              },
            ]}
            footer={
              features.isSuccess ? (
                <span>
                  {rows.length} of {all.length} feature{all.length === 1 ? "" : "s"}
                </span>
              ) : undefined
            }
          />
        </>
      )}
    </div>
  );
}
