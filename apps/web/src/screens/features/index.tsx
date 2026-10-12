import { Link, useNavigate, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  DataTable,
  DerivedLabel,
  EmptyState,
  Icon,
  IssueLink,
  ProblemError,
  Skeleton,
  StatusBadge,
  Tooltip,
} from "../../components";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useScope } from "../../lib/scope";
import { useCollectorState } from "../../shell/GlobalStream";
import { AcBar, FilterMenu, PHASES, PhaseBar, VERDICT_STATUS, phaseIndex } from "./parts";
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

/** In progress first, furthest along first (spec 17). */
function byProgress(a: Feature, b: Feature): number {
  return phaseIndex(b.phase) - phaseIndex(a.phase) || a.slug.localeCompare(b.slug);
}

export const featureHref = (f: Pick<Feature, "project" | "slug">) =>
  `/features/${encodeURIComponent(f.project)}/${encodeURIComponent(f.slug)}`;

function AcCell({ f }: { f: Feature }) {
  if (f.problem) {
    return (
      <Tooltip label={`${f.problem}. Fix it in a hub PR.`}>
        <span className="ah-row" style={{ gap: 4 }}>
          <Icon name="octagon-x" size="sm" style={{ color: "var(--blocked)" }} title={f.problem} />
          <span className="ah-subtle">--</span>
        </span>
      </Tooltip>
    );
  }
  if (!f.acs) return <span className="ah-subtle">--</span>;
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
  const evaluated = all.filter((f) => f.verdict !== null).length;
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
            · {evaluated} evaluated · {all.length - evaluated} in progress · read from{" "}
            <span className="ah-mono">brain/features/</span> in each hub · furthest along first
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
                render: (f) => (
                  <span className="ah-stack" style={{ gap: 2 }}>
                    <Link
                      to={featureHref(f)}
                      className="ah-mono"
                      style={{ fontWeight: 500 }}
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
                render: (f) =>
                  f.issues[0] ? (
                    <span className="ah-row" style={{ gap: 4 }}>
                      <IssueLink id={f.issues[0]} />
                      {f.issues.length > 1 && (
                        <Tooltip label={f.issues.slice(1).join(", ")}>
                          <span className="ah-small ah-subtle">(+{f.issues.length - 1})</span>
                        </Tooltip>
                      )}
                    </span>
                  ) : (
                    <span className="ah-subtle">—</span>
                  ),
              },
              {
                id: "size",
                label: "Size",
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
                    <DerivedLabel how="Derived from the feature record files; review needs runs and shipped needs GitHub, not connected in this version.">
                      derived
                    </DerivedLabel>
                  </span>
                ),
                render: (f) => <PhaseBar phase={f.phase} files={f.files} verdict={f.verdict} />,
              },
              { id: "acs", label: "ACs", render: (f) => <AcCell f={f} /> },
              {
                id: "verdict",
                label: "Verdict",
                render: (f) =>
                  f.verdict ? (
                    <StatusBadge
                      status={VERDICT_STATUS[f.verdict]}
                      label={f.verdict}
                      title={f.verdict_line ?? "From eval.md"}
                    />
                  ) : (
                    <span className="ah-subtle">--</span>
                  ),
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
          {features.isSuccess && (
            <div className="ah-small ah-subtle">
              <Icon name="info" size="sm" style={{ verticalAlign: "-3px" }} /> A full AC bar never
              hides a manual step: owner steps are counted and hatched in amber. Features without
              eval.md show “--” as verdict.
            </div>
          )}
        </>
      )}
    </div>
  );
}
