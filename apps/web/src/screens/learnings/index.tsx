import type { CSSProperties, ReactNode } from "react";
import { useParams, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  DataTable,
  EmptyState,
  ExternalLabel,
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
import { useLearnings, useLiveLearnings, type LearningStatus } from "./queries";

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
});

/** A proposed learning that cannot be accepted or rejected here (its note is gone, ...). */
const blockedReason = (l: Learning): string | null =>
  l.status === "proposed" ? (l.actions_unavailable ?? null) : null;

function QueueRow({ l }: { l: Learning }) {
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

  // Learnings that can be decided first, oldest first; the blocked ones after them.
  const rows = [...(learnings.data?.items ?? [])].sort(
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
  } else if (learnings.isSuccess && rows.length === 0 && chosen === null) {
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
              scrollLabel="Learnings"
              onRowClick={(l) => {
                select(l.id);
              }}
              columns={[
                {
                  id: "t",
                  label: `Learnings · ${learnings.isPending ? "…" : String(count)} ${status}`,
                  render: (l) => <QueueRow l={l} />,
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
