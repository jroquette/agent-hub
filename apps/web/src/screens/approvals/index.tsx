import { useParams, useSearchParams } from "react-router";
import type { ReactNode } from "react";

import {
  AppLink,
  Button,
  CodeBlock,
  DerivedLabel,
  EmptyState,
  Icon,
  IssueLink,
  Kbd,
  PathText,
  ProblemError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Time,
} from "../../components";
import { useNow } from "../../lib/clock";
import { useScope } from "../../lib/scope";
import { useGlobalStream } from "../../shell/GlobalStream";
import { useRefreshOnCounts } from "../portfolio/queries";
import { StaleStamp } from "../portfolio/StaleStamp";
import {
  consequences,
  DECISION,
  decideCommand,
  isPrompt,
  KIND,
  KIND_ORDER,
  LONG_WAIT_S,
  oldestFirst,
  shortId,
  waitedSeconds,
  waitText,
} from "./model";
import { useApproval, useApprovals, type Approval, type ApprovalKind } from "./queries";

function KindChip({ kind }: { kind: ApprovalKind }) {
  return (
    <span className="ah-stage ah-stage-waiting" style={{ flex: "none" }}>
      <Icon name={KIND[kind].icon} />
      {KIND[kind].label}
    </span>
  );
}

function Section({
  title,
  extra,
  children,
}: {
  title: string;
  extra?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section style={{ marginBottom: 20 }} aria-label={title}>
      <div className="ah-row" style={{ marginBottom: 8 }}>
        <h3
          className="ah-overline"
          style={{ textTransform: "uppercase", letterSpacing: "0.04em", margin: 0 }}
        >
          {title}
        </h3>
        <span className="ah-grow" />
        {extra}
      </div>
      {children}
    </section>
  );
}

function InboxRow({
  item,
  selected,
  href,
  now,
}: {
  item: Approval;
  selected: boolean;
  href: string;
  now: number;
}) {
  const waited = waitedSeconds(item, now);
  return (
    <li style={{ listStyle: "none" }}>
      <AppLink
        href={href}
        aria-current={selected ? "true" : undefined}
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto",
          gap: 12,
          padding: "12px 16px",
          borderBottom: "1px solid var(--border)",
          background: selected ? "var(--accent-soft)" : "var(--surface)",
          boxShadow: selected ? "inset 3px 0 0 var(--accent)" : undefined,
          color: "var(--text)",
          textDecoration: "none",
        }}
      >
        <span className="ah-stack" style={{ gap: 4, minWidth: 0 }}>
          <span className="ah-row" style={{ minWidth: 0 }}>
            <KindChip kind={item.kind} />
            <b
              style={{
                fontWeight: 600,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {item.title}
            </b>
          </span>
          <span
            className="ah-small ah-muted"
            style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          >
            {item.project} ·{" "}
            <span className="ah-mono" style={{ fontSize: 12 }}>
              {item.requested_by ?? "main"}
            </span>
            {item.issue ? ` · ${item.issue}` : ""}
          </span>
          {item.path && (
            <span className="ah-small">
              <PathText path={item.path} />
            </span>
          )}
        </span>
        <span className="ah-stack" style={{ gap: 2, alignItems: "flex-end" }}>
          <span
            className="ah-num"
            style={{ color: waited >= LONG_WAIT_S ? "var(--waiting)" : "var(--text-muted)" }}
          >
            {waitText(waited)}
          </span>
          <span className="ah-small ah-subtle">
            since <Time iso={item.requested_at} absolute />
          </span>
        </span>
      </AppLink>
    </li>
  );
}

function DecidedRow({ item }: { item: Approval }) {
  const look = DECISION[item.status];
  return (
    <li
      className="ah-stack"
      style={{
        listStyle: "none",
        padding: "12px 16px",
        borderBottom: "1px solid var(--border)",
        gap: 4,
      }}
    >
      <span className="ah-row">
        <StatusBadge status={look.status} label={look.label} inferred={item.inferred} />
        <b style={{ fontWeight: 600 }}>{item.title}</b>
      </span>
      <span className="ah-small ah-muted">
        {item.project} · {look.label.toLowerCase()} in the terminal ·{" "}
        {item.decided_at ? <Time iso={item.decided_at} absolute /> : "time unknown"}
      </span>
    </li>
  );
}

function HowToDecide({ item }: { item: Approval }) {
  const command = decideCommand(item);
  const prompt = isPrompt(item.kind);
  return (
    <div
      className="ah-stack"
      style={{
        border: "1px solid var(--border-strong)",
        background: "var(--surface-sunken)",
        borderRadius: "var(--radius-lg)",
        padding: "12px 14px",
      }}
    >
      <div className="ah-row">
        <Icon name="square-terminal" size="sm" />
        <b>{prompt ? "Answer in the terminal session" : "Approve in the terminal session"}</b>
      </div>
      <div className="ah-small ah-muted">
        This app is read-only in this version. The session that asked is waiting at its prompt.
      </div>
      <ol
        className="ah-small"
        style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}
      >
        <li>
          {command
            ? "Open a terminal on the machine where it runs and resume it:"
            : "Open the terminal running the session that asked."}
          {command && (
            <div style={{ marginTop: 4 }}>
              <CodeBlock code={command} label="How to decide" />
            </div>
          )}
        </li>
        <li>
          {prompt ? (
            <>
              Answer the permission prompt: choose <b>Yes</b> to allow it, or <b>No</b> and say why.
            </>
          ) : (
            <>
              Answer the question with <code className="ah-mono">approve</code>, or describe the
              changes you want.
            </>
          )}
        </li>
        <li>This item moves to Decided within a few seconds of your answer.</li>
      </ol>
    </div>
  );
}

function Detail({ item }: { item: Approval }) {
  const now = useNow(60_000);
  const kind = KIND[item.kind];
  const open = item.status === "open";
  const look = DECISION[item.status];
  const session = shortId(item.session_id);
  return (
    <section
      className="ah-approval"
      aria-label={item.title}
      style={{
        height: "100%",
        position: "relative",
        borderRadius: 0,
        border: 0,
        borderLeft: "1px solid var(--border)",
      }}
    >
      <div className="ah-approval-head">
        <div className="ah-row">
          <StatusBadge
            status={look.status}
            label={open ? `Waiting ${waitText(waitedSeconds(item, now))}` : look.label}
            inferred={item.inferred}
          />
          <KindChip kind={item.kind} />
          <span className="ah-grow" />
          {item.issue && <IssueLink id={item.issue} />}
        </div>
        <h2 className="ah-h2">{item.title}</h2>
        <div className="ah-row ah-small ah-muted ah-wrap" style={{ gap: 6 }}>
          <span>
            {item.project}
            {item.repo ? ` › ${item.repo}` : ""} · requested by{" "}
            <span className="ah-mono" style={{ color: "var(--text)", fontSize: 12 }}>
              {item.requested_by ?? "main"}
            </span>{" "}
            in session{" "}
            <AppLink
              className="ah-mono"
              style={{ fontSize: 12 }}
              href={`/sessions/${item.session_id}?event=${item.request_event_id}`}
            >
              {session}
            </AppLink>
          </span>
        </div>
        <div className="ah-small ah-muted">
          waiting since <Time iso={item.requested_at} absolute /> (
          {waitText(waitedSeconds(item, now))})
        </div>
      </div>
      <div className="ah-approval-body" style={{ flex: 1, minHeight: 0 }}>
        {item.kind === "guard_ask" && (
          <Section title="Why this asks">
            <p className="ah-small" style={{ margin: 0 }}>
              {item.path ? <code className="ah-mono">{item.path}</code> : "The path"} matches{" "}
              <code className="ah-mono">guard.ask_before_edit</code> in hub.json
              {item.rule ? (
                <>
                  {" "}
                  (rule <code className="ah-mono">{item.rule}</code>)
                </>
              ) : null}
              . The guard asks a person before an agent edits it.
            </p>
          </Section>
        )}
        <Section
          title={isPrompt(item.kind) ? "What changes if I allow" : "What changes if I approve"}
          extra={
            <DerivedLabel how="Built from the kind of request; the plan's own file list is not stored in this version.">
              Derived from the request kind
            </DerivedLabel>
          }
        >
          <ul className="ah-changes">
            {consequences(item).map((line) => (
              <li key={line.text}>
                <Icon
                  name={line.icon}
                  size="sm"
                  style={{ color: "var(--text-subtle)", marginTop: 2, flex: "none" }}
                />
                <span>{line.text}</span>
              </li>
            ))}
          </ul>
        </Section>
        {open && (
          <Section title="How to decide">
            <HowToDecide item={item} />
          </Section>
        )}
        {item.kind === "guard_ask" && (
          <Section title="Proposed edit">
            <p className="ah-small ah-muted" style={{ margin: 0 }}>
              Diff content is not stored in this version.
            </p>
          </Section>
        )}
        {item.feature && (
          <div className="ah-small" style={{ paddingBottom: 8 }}>
            <AppLink
              href={`/features/${encodeURIComponent(item.project)}/${encodeURIComponent(item.feature)}`}
            >
              Open feature record
              <Icon name="arrow-right" size="sm" style={{ verticalAlign: "-3px", marginLeft: 4 }} />
            </AppLink>
          </div>
        )}
      </div>
      {open && (
        <div className="ah-approval-foot">
          <div className="ah-approve-hint ah-grow">
            <Icon name="square-terminal" size="sm" style={{ marginTop: 2 }} />
            <span>Decide in the terminal session {session}. Deciding here arrives in Phase 4.</span>
          </div>
          <Button variant="primary" icon="check" phase="P4">
            {kind.verb}
          </Button>
          <Button icon="message-square" phase="P4">
            Request changes
          </Button>
          <Button variant="danger" icon="x" phase="P4">
            Reject
          </Button>
        </div>
      )}
    </section>
  );
}

function DetailRegion({ id, fromList }: { id: string; fromList: Approval | undefined }) {
  const detail = useApproval(id, fromList);
  if (detail.isPending) {
    return (
      <div
        style={{ padding: 16, borderLeft: "1px solid var(--border)", background: "var(--surface)" }}
        className="ah-stack"
        aria-busy="true"
      >
        <Skeleton width="40%" height={14} />
        <Skeleton width="80%" height={24} />
        <Skeleton lines={6} />
      </div>
    );
  }
  if (detail.isError) {
    return (
      <div style={{ padding: 16, borderLeft: "1px solid var(--border)" }} className="ah-stack">
        <ProblemError
          title="Could not load this approval"
          detail={detail.error.detail}
          status={detail.error.status}
          onRetry={() => void detail.refetch()}
        />
        <AppLink href="/approvals" className="ah-small">
          Back to inbox
        </AppLink>
      </div>
    );
  }
  return <Detail item={detail.data} />;
}

function KindFilter({
  value,
  onChange,
}: {
  value: ApprovalKind | null;
  onChange: (kind: ApprovalKind | null) => void;
}) {
  return (
    <label className="ah-row ah-small" style={{ gap: 6 }}>
      <span className="ah-subtle">Kind</span>
      <select
        className="ah-input"
        style={{ height: 28, width: "auto", padding: "0 8px" }}
        value={value ?? ""}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next === "" ? null : (next as ApprovalKind));
        }}
      >
        <option value="">All</option>
        {KIND_ORDER.map((kind) => (
          <option key={kind} value={kind}>
            {KIND[kind].label}
          </option>
        ))}
      </select>
    </label>
  );
}

function isKind(value: string | null): value is ApprovalKind {
  return value !== null && (KIND_ORDER as readonly string[]).includes(value);
}

/** Approvals (spec 15): what waits for a person, what a yes changes, and where to answer. */
export function ApprovalsScreen() {
  const { approvalId } = useParams();
  const [scope] = useScope();
  const [params, setParams] = useSearchParams();
  const tab = params.get("show") === "decided" ? "decided" : "open";
  const kindParam = params.get("kind");
  const kind = isKind(kindParam) ? kindParam : null;
  const list = useApprovals(scope, tab, kind);
  const { counts } = useGlobalStream();
  const now = useNow(60_000);
  useRefreshOnCounts(["/api/v1/approvals", "/api/v1/approvals/{approval_id}"]);

  const setParam = (key: string, value: string | null) => {
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

  const items = tab === "open" ? oldestFirst(list.data?.items ?? []) : (list.data?.items ?? []);
  const selectedId = approvalId ?? (tab === "open" ? items[0]?.id : undefined);
  const search = params.toString() ? `?${params.toString()}` : "";
  const oldest = items[0];
  const empty = list.isSuccess && items.length === 0;
  const live = counts?.live_sessions ?? 0;

  let listBody: ReactNode;
  if (list.isPending) {
    listBody = Array.from({ length: 3 }, (_, i) => (
      <div
        key={i}
        style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}
        className="ah-stack"
        aria-busy="true"
      >
        <Skeleton width="70%" height={14} />
        <Skeleton width="50%" />
      </div>
    ));
  } else if (list.isError) {
    listBody = (
      <div style={{ padding: 16 }}>
        <ProblemError
          title="Could not load approvals"
          detail={list.error.detail}
          status={list.error.status}
          onRetry={() => void list.refetch()}
        />
      </div>
    );
  } else if (empty && tab === "open") {
    listBody = (
      <EmptyState icon="circle-check" title="Nothing waits for you.">
        Plan approvals, human gates and guard requests appear here when an agent asks.{" "}
        {live
          ? `${String(live)} ${live === 1 ? "session is" : "sessions are"} running.`
          : "No session is running."}
      </EmptyState>
    );
  } else if (empty) {
    listBody = (
      <p className="ah-small ah-muted" style={{ padding: 16, margin: 0 }}>
        No decisions in the last 30 days.
      </p>
    );
  } else {
    listBody = (
      <>
        <ul
          style={{ margin: 0, padding: 0 }}
          aria-label={tab === "open" ? "Open approvals" : "Decided approvals"}
        >
          {items.map((item) =>
            tab === "open" ? (
              <InboxRow
                key={item.id}
                item={item}
                selected={item.id === selectedId}
                href={`/approvals/${item.id}${search}`}
                now={now}
              />
            ) : (
              <DecidedRow key={item.id} item={item} />
            ),
          )}
        </ul>
        <div className="ah-small ah-subtle" style={{ padding: 16 }}>
          Oldest first. <Kbd>Tab</Kbd> moves through the list; each row opens its request.
        </div>
      </>
    );
  }

  const showPanel = tab === "open" && !empty && !list.isError && selectedId !== undefined;
  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
      <div style={{ padding: "16px 32px 12px", borderBottom: "1px solid var(--border)" }}>
        <div className="ah-row">
          <h1 className="ah-h1">Approvals</h1>
          <StaleStamp />
          <span className="ah-grow" />
          <SegmentedControl
            label="Show"
            value={tab}
            onChange={(next) => {
              setParam("show", next === "decided" ? "decided" : null);
            }}
            options={[
              {
                id: "open",
                label: tab === "open" && list.data ? `Open ${String(items.length)}` : "Open",
              },
              { id: "decided", label: "Decided" },
            ]}
          />
        </div>
        <div className="ah-row ah-small ah-muted" style={{ marginTop: 6 }}>
          {list.isPending ? (
            <Skeleton width={180} />
          ) : tab === "open" && oldest ? (
            <span>
              <b style={{ color: "var(--text)" }}>{items.length} waiting</b> · oldest{" "}
              {waitText(waitedSeconds(oldest, now))}
            </span>
          ) : tab === "open" ? (
            <span>Nothing waiting</span>
          ) : (
            <span>Decided requests, newest first</span>
          )}
          <span className="ah-grow" />
          <KindFilter
            value={kind}
            onChange={(next) => {
              setParam("kind", next);
            }}
          />
        </div>
      </div>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: showPanel ? "minmax(320px, 460px) minmax(0, 1fr)" : "1fr",
        }}
      >
        <div style={{ overflow: "auto", background: "var(--surface)" }}>{listBody}</div>
        {showPanel && (
          <DetailRegion
            key={selectedId}
            id={selectedId}
            fromList={items.find((item) => item.id === selectedId)}
          />
        )}
      </div>
    </div>
  );
}
