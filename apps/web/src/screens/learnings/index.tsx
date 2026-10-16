import { useState, type CSSProperties, type ReactNode } from "react";
import { useParams, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Banner,
  Button,
  DataTable,
  EmptyState,
  ExternalLabel,
  FilterChip,
  Icon,
  ProblemError,
  ProvenanceBadge,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Tabs,
} from "../../components";
import { useNow } from "../../lib/clock";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useScope } from "../../lib/scope";
import { useCollectorState } from "../../shell/GlobalStream";
import {
  ageOf,
  isExternal,
  LearningDetail,
  LearningStateBadge,
  stateOf,
  Title,
} from "./LearningDetail";
import {
  blockedReason,
  CLAUDE_VERDICTS,
  facetCounts,
  filterLearnings,
  filtersFromParams,
  hasFilters,
  MAX_QUERY_CHARS,
  NO_FILTERS,
  PROVENANCES,
  READINESS,
  toggle,
  withFilters,
  type ClaudeVerdict,
  type LearningFilters,
  type VerdictOf,
} from "./filters";
import { useLearnings, useLiveLearnings, type LearningStatus } from "./queries";
import { VERDICT } from "./ReviewPanel";
import { MAX_TRIAGE_BATCH } from "./review";
import { triageCandidates, useClaudeVerdicts, useTriage } from "./triage";

type Learning = components["schemas"]["Learning"];

function parseStatus(value: string | null): LearningStatus {
  return value === "accepted" || value === "rejected" ? value : "proposed";
}

const STATUSES: readonly { id: LearningStatus; label: string }[] = [
  { id: "proposed", label: "Proposed" },
  { id: "accepted", label: "Accepted" },
  { id: "rejected", label: "Rejected" },
];

/** Clamps text to `lines` lines without widening the table (a nowrap cell would). */
const clamp = (lines: number): CSSProperties => ({
  display: "-webkit-box",
  WebkitLineClamp: lines,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
  overflowWrap: "anywhere",
  // Table cells are `nowrap`; without this the clamp never wraps and the title is cut off.
  whiteSpace: "normal",
});

const CLAUDE_LABEL: Record<ClaudeVerdict, string> = {
  ready: "Goes in",
  needs_changes: "Needs changes",
  not_for_brain: "Leave out",
  reviewing: "Reviewing",
  unreviewed: "Not reviewed",
};

/** Claude's recommendation as the queue shows it; nothing until a review was asked for. */
function ClaudeVerdictBadge({ verdict }: { verdict: ClaudeVerdict }) {
  if (verdict === "unreviewed") return null;
  if (verdict === "reviewing") {
    return (
      <span className="ah-row ah-small ah-subtle" style={{ gap: 4 }}>
        <Icon name="loader" size="sm" />
        Claude reviewing…
      </span>
    );
  }
  const look = VERDICT[verdict];
  return <StatusBadge status={look.status} label={`Claude: ${look.label}`} />;
}

function QueueRow({ l, verdict }: { l: Learning; verdict: ClaudeVerdict }) {
  const ext = isExternal(l);
  const state = stateOf(l);
  const blocked = blockedReason(l);
  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        borderLeft: ext ? "3px solid var(--waiting)" : "3px solid transparent",
        paddingLeft: 8,
        marginLeft: -8,
      }}
    >
      <div className="ah-stack" style={{ gap: 4, minWidth: 0, flex: 1 }}>
        <span className="ah-row" style={{ gap: 6, minWidth: 0 }}>
          {ext && (
            <Icon
              name="triangle-alert"
              size="sm"
              style={{ color: "var(--waiting)", flex: "none" }}
            />
          )}
          <span
            title={l.text}
            style={{
              ...clamp(2),
              fontWeight: 500,
              textDecoration: l.status === "rejected" ? "line-through" : undefined,
            }}
          >
            <Title t={l.text} />
          </span>
        </span>
        {l.summary ? (
          <span className="ah-small ah-muted" style={clamp(1)} title={l.summary}>
            {l.summary}
          </span>
        ) : (
          !blocked && (
            <span className="ah-small ah-subtle" style={{ ...clamp(1), fontStyle: "italic" }}>
              {l.note_unavailable ?? "No summary"}
            </span>
          )
        )}
        <span className="ah-row ah-wrap" style={{ gap: 6 }}>
          <ClaudeVerdictBadge verdict={verdict} />
          {blocked && <StatusBadge status="blocked" label={blocked} />}
          {state !== "proposed" && <LearningStateBadge state={state} />}
          {l.provenance && <ProvenanceBadge provenance={l.provenance} />}
          {ext && <ExternalLabel source="External" />}
          <span className="ah-small ah-subtle">{l.project}</span>
        </span>
      </div>
    </div>
  );
}

const READINESS_LABEL = { ready: "Ready", blocked: "Blocked" } as const;

function FacetRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ah-row ah-wrap" style={{ gap: 6 }} role="group" aria-label={label}>
      <span className="ah-small ah-subtle" style={{ width: 72, flex: "none" }}>
        {label}
      </span>
      {children}
    </div>
  );
}

/** Search and facets above the queue: project (when every project is in scope), provenance and,
 * for proposals, whether they can be decided here. */
function LearningFiltersBar({
  rows,
  filters,
  onChange,
  showProject,
  showReadiness,
  verdictOf,
}: {
  rows: readonly Learning[];
  filters: LearningFilters;
  onChange: (next: LearningFilters) => void;
  showProject: boolean;
  showReadiness: boolean;
  verdictOf: VerdictOf;
}) {
  const counts = facetCounts(rows, filters, verdictOf);
  const provenances = PROVENANCES.filter(
    (p) => counts.provenance[p] > 0 || filters.provenance.includes(p),
  );
  const allProjects = counts.project.reduce((sum, [, n]) => sum + n, 0);
  return (
    <div className="ah-stack" style={{ gap: 8, padding: "12px 16px 0 32px" }}>
      <div className="ah-row" style={{ gap: 8 }}>
        <div className="ah-search ah-grow">
          <Icon name="search" size="sm" />
          <input
            type="search"
            className="ah-input"
            aria-label="Search learnings"
            placeholder="Search title, summary or project"
            maxLength={MAX_QUERY_CHARS}
            value={filters.q}
            onChange={(event) => {
              onChange({ ...filters, q: event.target.value });
            }}
          />
        </div>
        {hasFilters(filters) && (
          <Button
            size="sm"
            variant="ghost"
            icon="x"
            onClick={() => {
              onChange(NO_FILTERS);
            }}
          >
            Clear
          </Button>
        )}
      </div>
      {showProject && (
        <FacetRow label="Project">
          <FilterChip
            value={`All · ${String(allProjects)}`}
            active={filters.project === null}
            onClick={() => {
              onChange({ ...filters, project: null });
            }}
          />
          {counts.project.map(([project, n]) => (
            <FilterChip
              key={project}
              value={`${project} · ${String(n)}`}
              active={filters.project === project}
              onClick={() => {
                onChange({ ...filters, project: filters.project === project ? null : project });
              }}
            />
          ))}
        </FacetRow>
      )}
      {provenances.length > 0 && (
        <FacetRow label="Provenance">
          {provenances.map((p) => (
            <FilterChip
              key={p}
              value={`${p} · ${String(counts.provenance[p])}`}
              active={filters.provenance.includes(p)}
              onClick={() => {
                onChange({ ...filters, provenance: toggle(filters.provenance, p) });
              }}
            />
          ))}
        </FacetRow>
      )}
      {showReadiness && (
        <FacetRow label="Claude">
          {CLAUDE_VERDICTS.filter((v) => counts.claude[v] > 0 || filters.claude.includes(v)).map(
            (v) => (
              <FilterChip
                key={v}
                value={`${CLAUDE_LABEL[v]} · ${String(counts.claude[v])}`}
                active={filters.claude.includes(v)}
                onClick={() => {
                  onChange({ ...filters, claude: toggle(filters.claude, v) });
                }}
              />
            ),
          )}
        </FacetRow>
      )}
      {showReadiness && (
        <FacetRow label="Decision">
          {READINESS.map((r) => (
            <FilterChip
              key={r}
              value={`${READINESS_LABEL[r]} · ${String(counts.readiness[r])}`}
              active={filters.readiness.includes(r)}
              onClick={() => {
                onChange({ ...filters, readiness: toggle(filters.readiness, r) });
              }}
            />
          ))}
        </FacetRow>
      )}
    </div>
  );
}

/** Knowledge › Learnings (spec 22, AC-201.29): the triage queue; accept and reject open hub PRs. */
export function LearningsScreen() {
  const [scope] = useScope();
  const [params, setParams] = useSearchParams();
  const status = parseStatus(params.get("status"));
  const learnings = useLearnings(scope, status);
  useLiveLearnings();
  const now = useNow(30_000);
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();

  const filters = filtersFromParams(params);
  const setFilters = (next: LearningFilters) => {
    setParams((current) => withFilters(current, next), { replace: true });
  };
  const all = learnings.data?.items ?? [];
  const projects = new Set(all.map((l) => l.project));
  const claude = useClaudeVerdicts(all);
  // Learnings that can be decided first, oldest first; the blocked ones after them.
  const rows = filterLearnings(all, filters, claude.verdictOf).sort(
    (a, b) =>
      Number(blockedReason(a) !== null) - Number(blockedReason(b) !== null) ||
      (a.proposed_at ?? "").localeCompare(b.proposed_at ?? ""),
  );
  const blockedCount = rows.filter((l) => blockedReason(l) !== null).length;
  const { learningId } = useParams();
  // `/knowledge/learnings/:learningId` (a link to one proposal) and `?learning=` both pick it.
  const chosen = params.get("learning") ?? learningId ?? null;
  // A learning pinned in the URL stays open after a decision moves it out of this status's list.
  const selectedId = chosen ?? rows[0]?.id ?? null;
  const select = (id: string) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set("learning", id);
        return next;
      },
      { replace: true },
    );
  };
  const count = learnings.data?.total_estimate ?? rows.length;
  // A triage session runs in one hub: the picked project, the scope, or the only one listed.
  const triageProject =
    filters.project ?? scope ?? (projects.size === 1 ? ([...projects][0] ?? null) : null);
  const candidates = triageCandidates(
    rows.filter((l) => triageProject === null || l.project === triageProject),
  );
  const triage = useTriage(triageProject, candidates);
  const [triageStarted, setTriageStarted] = useState<number | null>(null);
  const stamp = state === "offline" && <AsOfStamp stale time={fmtClock(asOf, tz)} />;

  let body: ReactNode;
  if (learnings.isError) {
    body = (
      <div style={{ padding: 32, maxWidth: 720 }}>
        <ProblemError
          title={learnings.error.title}
          detail={learnings.error.detail}
          status={learnings.error.status}
          onRetry={() => void learnings.refetch()}
        />
      </div>
    );
  } else if (learnings.isSuccess && all.length === 0 && chosen === null) {
    // A learning pinned in the URL (just decided, or linked) stays open on an empty list.
    body = (
      <div style={{ padding: 32 }}>
        <EmptyState
          icon="sprout"
          title={status === "proposed" ? "Inbox empty" : `No ${status} learnings`}
        >
          Agents propose learnings with <code className="ah-mono">/learn</code>; notes in
          brain/_inbox/ appear here for triage.
        </EmptyState>
      </div>
    );
  } else {
    body = (
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 520px) minmax(0, 1fr)" }}>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
            borderRight: "1px solid var(--border)",
          }}
        >
          {learnings.isSuccess && (
            <LearningFiltersBar
              rows={all}
              filters={filters}
              onChange={setFilters}
              showProject={scope === null}
              showReadiness={status === "proposed"}
              verdictOf={claude.verdictOf}
            />
          )}
          {status === "proposed" && learnings.isSuccess && (
            <div className="ah-stack" style={{ gap: 6, padding: "10px 16px 0 32px" }}>
              <div className="ah-row ah-wrap" style={{ gap: 8 }}>
                <Button
                  size="sm"
                  icon="message-square"
                  disabled={triage.reason !== null || triage.pending}
                  title={triage.reason ?? undefined}
                  onClick={() => {
                    void triage.start().then((n) => {
                      setTriageStarted(n);
                      claude.refresh();
                    });
                  }}
                >
                  {triage.pending
                    ? "Starting the triage…"
                    : `Triage with Claude${candidates.length > 0 ? ` · ${String(Math.min(candidates.length, MAX_TRIAGE_BATCH))}` : ""}`}
                </Button>
                <span className="ah-small ah-subtle">
                  {triage.reason ??
                    `Claude checks each against the /learn bar and recommends whether it goes in.${candidates.length > MAX_TRIAGE_BATCH ? ` ${String(MAX_TRIAGE_BATCH)} per run.` : ""}`}
                </span>
              </div>
              {triageStarted !== null && (
                <Banner
                  tone="info"
                  boxed
                  onDismiss={() => {
                    setTriageStarted(null);
                  }}
                >
                  Claude is triaging {triageStarted} learnings. Each verdict shows on its row as it
                  is written.
                </Banner>
              )}
              {triage.error && (
                <Banner tone="warning" boxed>
                  <b style={{ fontWeight: 600 }}>The triage did not start.</b> {triage.error.title}
                </Banner>
              )}
            </div>
          )}
          {claude.sources}
          <div className="ah-row ah-wrap" style={{ gap: 6, padding: "12px 16px 10px 32px" }}>
            <span className="ah-small ah-subtle">
              {status === "proposed" && blockedCount > 0
                ? `${String(rows.length - blockedCount)} ready · ${String(blockedCount)} blocked · oldest first`
                : "Oldest first"}
            </span>
            <span className="ah-grow" />
            {stamp}
          </div>
          <div style={{ padding: "0 16px 0 32px" }}>
            <DataTable<Learning>
              caption="Proposed learnings"
              loading={learnings.isPending}
              rowKey={(l) => l.id}
              rows={rows}
              selected={selectedId ? [selectedId] : []}
              maxHeight={640}
              empty={
                <div className="ah-pad ah-small ah-muted">No learnings match these filters.</div>
              }
              scrollLabel="Learnings"
              onRowClick={(l) => {
                select(l.id);
              }}
              columns={[
                {
                  id: "t",
                  label: `Learnings · ${
                    learnings.isPending
                      ? "…"
                      : hasFilters(filters)
                        ? `${String(rows.length)} of ${String(count)}`
                        : String(count)
                  } ${status}`,
                  render: (l) => <QueueRow l={l} verdict={claude.verdictOf(l)} />,
                },
                {
                  id: "age",
                  label: "Age",
                  align: "right",
                  width: 56,
                  render: (l) => (
                    <span className="ah-num ah-small" style={{ whiteSpace: "nowrap" }}>
                      {ageOf(l, now)}
                    </span>
                  ),
                },
              ]}
            />
          </div>
        </div>
        <div style={{ minWidth: 0 }}>
          {learnings.isPending || !selectedId ? (
            <div style={{ padding: "20px 28px" }} className="ah-stack" aria-busy="true">
              <Skeleton width="70%" height={22} />
              <Skeleton width="45%" />
              <Skeleton height={64} radius={8} />
            </div>
          ) : (
            <LearningDetail
              key={selectedId}
              id={selectedId}
              row={rows.find((l) => l.id === selectedId)}
              now={now}
              onDecide={select}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div
        style={{
          padding: "16px 32px 0",
          borderBottom: "1px solid var(--border)",
          background: "var(--bg)",
        }}
      >
        <div className="ah-row ah-wrap" style={{ gap: 12, marginBottom: 8 }}>
          <h1 className="ah-h1">Knowledge</h1>
          <span className="ah-subtle ah-small">What did the agents propose to remember?</span>
          <span className="ah-grow" />
          <SegmentedControl
            label="Status"
            value={status}
            onChange={(id) => {
              // A status switch is a navigation (spec 01): Back undoes it, the URL keeps it.
              setParams((current) => {
                const next = new URLSearchParams(current);
                next.delete("learning");
                if (id === "proposed") next.delete("status");
                else next.set("status", id);
                return next;
              });
            }}
            options={STATUSES.map((s) => ({ id: s.id, label: s.label }))}
          />
        </div>
        <Tabs
          value="learnings"
          label="Knowledge"
          tabs={[
            {
              id: "learnings",
              label: "Learnings",
              icon: "sprout",
              count: status === "proposed" && learnings.isSuccess ? count : undefined,
            },
          ]}
        />
      </div>
      {body}
    </div>
  );
}
