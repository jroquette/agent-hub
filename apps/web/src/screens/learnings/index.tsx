import { Fragment, useState } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Button,
  DataTable,
  EmptyState,
  ExternalLabel,
  IdChip,
  Icon,
  Kbd,
  PathText,
  PhaseTag,
  ProblemError,
  ProvenanceBadge,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Tabs,
  Time,
  type IconName,
} from "../../components";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useScope } from "../../lib/scope";
import { useCollectorState } from "../../shell/GlobalStream";
import { useLearnings, useLiveLearnings, type LearningStatus } from "./queries";

type Learning = components["schemas"]["Learning"];
type TargetKind = NonNullable<components["schemas"]["LearningTarget"]["kind"]>;

const TARGET: Record<TargetKind, { icon: IconName; short: string; via: string }> = {
  team: { icon: "library", short: "team brain", via: "team brain · via hub PR" },
  repo: { icon: "book", short: "repo AGENTS.md", via: "repo AGENTS.md · via that repo's PR" },
  personal: {
    icon: "lock",
    short: "personal",
    via: "written by /learn personal on this machine",
  },
};
const STATUSES: readonly { id: LearningStatus; label: string }[] = [
  { id: "proposed", label: "Proposed" },
  { id: "accepted", label: "Accepted" },
  { id: "rejected", label: "Rejected" },
];

/** Backticks in a learning title render as inline code (design). */
function Title({ t }: { t: string }) {
  return (
    <>
      {t.split("`").map((part, i) =>
        i % 2 ? (
          <code
            key={i}
            className="ah-mono"
            style={{
              fontSize: "0.92em",
              background: "var(--code-bg)",
              padding: "0 3px",
              borderRadius: 3,
            }}
          >
            {part}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

const isExternal = (l: Learning) => l.provenance === "agent-from-external";

function ageOf(l: Learning, now: number): string {
  return l.proposed_at
    ? fmtAgo(Math.max(1, (now - Date.parse(l.proposed_at)) / 1000)).replace(" ago", "")
    : "—";
}

function QueueRow({ l }: { l: Learning }) {
  const ext = isExternal(l);
  const kind = l.target.kind;
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
            style={{
              fontWeight: 500,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              textDecoration: l.status === "rejected" ? "line-through" : undefined,
            }}
          >
            <Title t={l.text} />
          </span>
        </span>
        <span className="ah-row ah-wrap" style={{ gap: 6 }}>
          {l.provenance && <ProvenanceBadge provenance={l.provenance} />}
          <span className="ah-small ah-subtle">{kind ? TARGET[kind].short : "no target"}</span>
          <span className="ah-small ah-subtle">· {l.project}</span>
        </span>
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "120px 1fr",
        gap: 12,
        padding: "12px 0",
        borderTop: "1px solid var(--border)",
      }}
    >
      <div className="ah-small ah-subtle">{label}</div>
      <div style={{ minWidth: 0 }}>{children}</div>
    </div>
  );
}

function Detail({ l, now }: { l: Learning; now: number }) {
  const ext = isExternal(l);
  const kind = l.target.kind;
  return (
    <section
      aria-label="Proposal"
      style={{ display: "flex", flexDirection: "column", minWidth: 0 }}
    >
      <div style={{ padding: "20px 28px 12px" }}>
        <div
          style={
            ext
              ? {
                  border: "1px solid var(--waiting)",
                  borderLeft: "3px solid var(--waiting)",
                  borderRadius: "var(--radius-lg)",
                  overflow: "hidden",
                }
              : undefined
          }
        >
          <div
            style={ext ? { background: "var(--waiting-soft)", padding: "12px 16px" } : undefined}
          >
            <div className="ah-row" style={{ gap: 8, alignItems: "flex-start" }}>
              {ext && (
                <Icon name="triangle-alert" style={{ color: "var(--waiting)", marginTop: 4 }} />
              )}
              <h2 className="ah-h2" style={{ fontSize: 18, lineHeight: "26px" }}>
                <Title t={l.text} />
              </h2>
            </div>
            <div className="ah-row ah-wrap ah-small ah-muted" style={{ gap: 8, marginTop: 6 }}>
              {l.provenance && <ProvenanceBadge provenance={l.provenance} />}
              {ext && <ExternalLabel source="External content" />}
              <span>
                proposed {l.proposed_at ? `${ageOf(l, now)} ago` : ""} by{" "}
                <span className="ah-mono" style={{ color: "var(--text)" }}>
                  {l.author ?? "an agent"}
                </span>
              </span>
              {l.source_session_id && (
                <>
                  <span>· session</span>
                  <IdChip id={l.source_session_id} kind="session" />
                </>
              )}
              <span>· {l.project}</span>
            </div>
          </div>
          {ext && (
            <div style={{ padding: "12px 16px" }}>
              <b style={{ fontWeight: 600 }}>Verify before accepting.</b> This text came from
              outside the project and was relayed by an agent.
            </div>
          )}
        </div>

        <div style={{ marginTop: 16 }}>
          <Section label="Proposed text">
            <div
              style={{
                background: "var(--surface-sunken)",
                borderRadius: "var(--radius-md)",
                padding: "10px 14px",
                borderLeft: "2px solid var(--border-strong)",
                lineHeight: "22px",
              }}
            >
              “<Title t={l.text} />”
            </div>
            <div className="ah-small ah-subtle" style={{ marginTop: 6 }}>
              As proposed, unedited. Proposed text is never styled as fact.
            </div>
          </Section>
          <Section label="Target">
            <div className="ah-row ah-wrap" style={{ gap: 8 }}>
              <Icon
                name={kind ? TARGET[kind].icon : "circle-dashed"}
                size="sm"
                style={{ color: "var(--text-subtle)" }}
              />
              {kind === "personal" ? (
                <b style={{ fontWeight: 500 }}>Personal memory (yours only)</b>
              ) : l.target.path ? (
                <PathText path={l.target.path} max={52} dimDir />
              ) : (
                <span className="ah-subtle">No target recorded</span>
              )}
              {kind && <span className="ah-small ah-subtle">({TARGET[kind].via})</span>}
              <Button size="sm" variant="ghost" iconRight="chevron-down" phase="P3">
                Change target
              </Button>
            </div>
          </Section>
          <Section label="Evidence">
            {l.source_session_id ? (
              <div className="ah-row ah-wrap" style={{ gap: 8 }}>
                <span className="ah-small">
                  session{" "}
                  <span className="ah-mono">
                    {l.source_session_id.replace(/-/g, "").slice(0, 8)}
                  </span>
                </span>
                <Link
                  className="ah-small ah-row"
                  style={{ gap: 4 }}
                  to={`/sessions/${l.source_session_id}?tab=timeline${l.source_event_id ? `&event=${l.source_event_id}` : ""}`}
                >
                  Open at that moment
                  <Icon name="arrow-right" size="sm" />
                </Link>
              </div>
            ) : (
              <span className="ah-small ah-subtle">No source session recorded.</span>
            )}
          </Section>
          {l.status !== "proposed" && (
            <Section label="Decision">
              <div className="ah-stack" style={{ gap: 4 }}>
                <span className="ah-row" style={{ gap: 8 }}>
                  <StatusBadge
                    status={l.status === "accepted" ? "done" : "idle"}
                    label={l.status}
                  />
                  {l.decided_at && (
                    <span className="ah-small ah-muted">
                      <Time iso={l.decided_at} absolute />
                      {l.decided_by ? ` by ${l.decided_by}` : ""}
                    </span>
                  )}
                </span>
                {l.rejection_reason && <span className="ah-small">{l.rejection_reason}</span>}
                {l.brain_path && (
                  <span className="ah-small">
                    Written to <span className="ah-mono">{l.brain_path}</span>
                    {l.commit ? ` at ${l.commit.slice(0, 7)}` : ""}
                  </span>
                )}
              </div>
            </Section>
          )}
        </div>
      </div>
      <div
        style={{
          borderTop: "1px solid var(--border)",
          padding: "12px 28px",
          background: "var(--surface)",
        }}
      >
        <div className="ah-row" style={{ gap: 8 }}>
          <Button variant="primary" icon="check" phase="P3">
            Accept <Kbd>a</Kbd>
          </Button>
          <Button icon="x" phase="P3">
            Reject <Kbd>r</Kbd>
          </Button>
          <Button variant="ghost" icon="clock" phase="P3">
            Snooze 7 d <Kbd>s</Kbd>
          </Button>
        </div>
        <div className="ah-small ah-subtle" style={{ marginTop: 8 }}>
          Deciding here arrives in Phase 3. Until then, triage with /learn in a Claude Code session
          in the hub.
        </div>
      </div>
    </section>
  );
}

/** Knowledge › Learnings (spec 22, D20, D21): read-only triage queue, tagged P3. */
export function LearningsScreen() {
  const [scope] = useScope();
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<LearningStatus>("proposed");
  const learnings = useLearnings(scope, status);
  useLiveLearnings();
  const now = useNow(30_000);
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();

  const rows = [...(learnings.data?.items ?? [])].sort((a, b) =>
    (a.proposed_at ?? "").localeCompare(b.proposed_at ?? ""),
  );
  const chosen = params.get("learning");
  const selected = rows.find((l) => l.id === chosen) ?? rows[0];
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
  } else if (learnings.isSuccess && rows.length === 0) {
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
            <span className="ah-small ah-subtle">Oldest first</span>
            <span className="ah-grow" />
            {stamp}
          </div>
          <div style={{ padding: "0 16px 0 32px" }}>
            <DataTable<Learning>
              caption="Proposed learnings"
              loading={learnings.isPending}
              rowKey={(l) => l.id}
              rows={rows}
              selected={selected ? [selected.id] : []}
              maxHeight={640}
              onRowClick={(l) => {
                select(l.id);
              }}
              columns={[
                {
                  id: "t",
                  label: `Proposal · ${learnings.isPending ? "…" : String(count)} ${status === "proposed" ? "awaiting triage" : status}`,
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
          {learnings.isPending || !selected ? (
            <div style={{ padding: "20px 28px" }} className="ah-stack" aria-busy="true">
              <Skeleton width="70%" height={22} />
              <Skeleton width="45%" />
              <Skeleton height={64} radius={8} />
            </div>
          ) : (
            <Detail l={selected} now={now} />
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
          <PhaseTag phase="P3" />
          <span className="ah-subtle ah-small">What did the agents propose to remember?</span>
          <span className="ah-grow" />
          <SegmentedControl
            label="Status"
            value={status}
            onChange={(id) => {
              setStatus(id as LearningStatus);
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
