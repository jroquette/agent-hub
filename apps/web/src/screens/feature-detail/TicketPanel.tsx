import "./ticket-panel.css";

import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { Link, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  Button,
  EmptyState,
  GOLDEN_STATE_TEXT,
  GoldenPathStepper,
  Icon,
  FENCE,
  HEADING,
  IdChip,
  Markdown,
  ProblemError,
  ProvenanceBadge,
  SidePanel,
  Skeleton,
  StatusBadge,
  Banner,
  type Status,
  type StepperStep,
} from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtDateTime } from "../../lib/format";
import { DecisionError, GateDecision } from "../approvals/GateDecision";
import {
  FOCUS_EVAL,
  evalHistory,
  evalSearch,
  evaluatedText,
  ownerStepsWaiting,
  runLabels,
} from "./EvalTab";
import { usePreferences } from "../../lib/preferences";
import {
  AcCount,
  LinearLink,
  ReadinessText,
  STATE_STATUS,
  StateBadge,
  TICKET_STEP_LABEL,
  TicketIdLine,
  TicketOpenLink,
  TicketPrLinks,
  signalKind,
  ticketParam,
  ticketSearch,
  type TicketOpener,
} from "./PlanningView";
import { useDecideChangeRequest, useTicketRecords } from "./queries";
import { AcList, Assignee, EDGE_TITLE, TicketSessions, useTicketSessions } from "./TicketsTab";

type FeatureTickets = components["schemas"]["FeatureTickets"];
type TicketRow = components["schemas"]["TicketRow"];
type TicketStepName = components["schemas"]["TicketStepName"];
type EvalRecord = components["schemas"]["EvalRecord"];
type AcRow = components["schemas"]["AcRow"];
type TicketRecords = components["schemas"]["TicketRecords"];
type TicketRecordsQuery = ReturnType<typeof useTicketRecords>;
type ChangeRequestView = components["schemas"]["ChangeRequestView"];
type PreflightRun = components["schemas"]["PreflightRun"];
type StepState = components["schemas"]["StepState"];
type EdgeSource = components["schemas"]["EdgeSource"];
type ExternalBlocker = components["schemas"]["ExternalBlocker"];

const NOT_REACHED = "Not reached.";

/** A step's state as the step card's badge: its word (GOLDEN_STATE_TEXT) in its tone. */
const STEP_STATUS: Record<StepState, { status: Status; quiet?: boolean }> = {
  current: { status: "live" },
  partial: { status: "live" },
  done: { status: "done" },
  pending: { status: "idle" },
  unrecorded: { status: "idle", quiet: true },
  skipped: { status: "idle", quiet: true },
  waiting: { status: "waiting" },
  stale: { status: "stale" },
  blocked: { status: "blocked" },
  unknown: { status: "idle" },
};

/** How a step came out, when its meta says more than its state ("Changes requested"); else null. */
function stepOutcome(step: StepperStep<string>): string | null {
  if (!step.meta) return null;
  return step.meta.toLowerCase() === GOLDEN_STATE_TEXT[step.state].toLowerCase() ? null : step.meta;
}

const DRIFT_WORDS: Record<PreflightRun["drift"], string> = {
  none: "no drift",
  local: "local drift",
  plan: "plan drift",
};

const plural = (n: number, word: string) => `${String(n)} ${word}${n === 1 ? "" : "s"}`;

/** A plan version, "—" when the record does not say. */
const version = (n: number | null | undefined) => (n == null ? "—" : `v${String(n)}`);

/** The element id of a change request's block in the panel, the target of its openers. */
export const requestAnchor = (n: number) => `change-request-${String(n)}`;

/** Whether `name` is one of `row`'s refs (its key, its tracker id), in any case. */
function namesRow(row: TicketRow, name: string | null | undefined): boolean {
  const upper = name?.toUpperCase();
  return [row.key, row.id, row.ref].some((ref) => ref != null && ref.toUpperCase() === upper);
}

/** How long a request has waited, from its `opened_at` ("2 h ago"); null when unknown. */
export function WaitAge({ openedAt }: { openedAt: string | null | undefined }) {
  const now = useNow(60_000);
  const { tz } = usePreferences();
  if (!openedAt || Number.isNaN(Date.parse(openedAt))) return null;
  const seconds = Math.max(0, (now - Date.parse(openedAt)) / 1000);
  return (
    <span className="ah-small ah-muted">
      waiting{" "}
      <time dateTime={openedAt} title={fmtDateTime(openedAt, tz)}>
        {fmtAgo(seconds).replace(/ ago$/, "")}
      </time>
    </span>
  );
}

/** Whether each line of `lines` is code: inside a fence, closed by its own marker (as Markdown). */
function codeLines(lines: readonly string[]): boolean[] {
  let marker: string | null = null;
  return lines.map((line) => {
    if (marker !== null) {
      const trimmed = line.trim();
      if (trimmed.startsWith(marker) && /^([`~])\1*$/.test(trimmed)) marker = null;
      return true;
    }
    const fence = FENCE.exec(line);
    if (fence) marker = fence[1] ?? "```";
    return fence !== null;
  });
}

/** Markdown whose headings start at level `top`, so it sits below the heading that holds it. */
export function belowHeading(source: string, top: number): string {
  const lines = source.split("\n");
  const code = codeLines(lines);
  const level = (line: string, index: number) =>
    code[index] ? null : (HEADING.exec(line)?.[1]?.length ?? null);
  const levels = lines.map(level).filter((found): found is number => found !== null);
  const shift = Math.max(0, top - Math.min(...levels, top));
  if (shift === 0) return source;
  return lines
    .map((line, index) =>
      level(line, index) === null
        ? line
        : line.replace(
            /^( {0,3})(#{1,6})/,
            (_, indent: string, marks: string) =>
              `${indent}${"#".repeat(Math.min(6, marks.length + shift))}`,
          ),
    )
    .join("\n");
}

/**
 * The owner's decision on a change request whose run is gone (two-level-flows AC-2.14): Approve,
 * or Decline with the note the next preflight follows (AC-2.12), recorded in the hub.
 */
function LostRunDecision({
  project,
  slug,
  request,
  onDecided,
}: {
  project: string;
  slug: string;
  request: ChangeRequestView;
  onDecided: () => void;
}) {
  const decide = useDecideChangeRequest(project, slug, request.n);
  const [note, setNote] = useState("");
  const [needsNote, setNeedsNote] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const fieldId = useId();
  const hintId = useId();
  const busy = decide.isPending || decide.isSuccess;
  const send = (decision: "approved" | "declined") => {
    const text = note.trim();
    if (decision === "declined" && !text) {
      setNeedsNote(true);
      field.current?.focus();
      return;
    }
    decide.reset();
    decide.mutate({ decision, note: text || null }, { onSuccess: onDecided });
  };
  return (
    <div className="ah-stack" style={{ gap: 6 }}>
      <span className="ah-small ah-muted">
        Its run is gone (abandoned, or its record lost): your decision is recorded in the hub, and
        the next /implement of {request.ticket} reads it.
      </span>
      <label htmlFor={fieldId} className="ah-small">
        Note (required to decline)
      </label>
      <textarea
        ref={field}
        id={fieldId}
        className="ah-input"
        rows={3}
        maxLength={2000}
        value={note}
        disabled={busy}
        aria-invalid={needsNote || undefined}
        aria-describedby={needsNote ? hintId : undefined}
        onChange={(event) => {
          setNote(event.target.value);
          setNeedsNote(false);
        }}
      />
      {needsNote && (
        <span id={hintId} role="alert" className="ah-small">
          Write a note to decline: the next preflight follows it.
        </span>
      )}
      <div
        role="group"
        aria-label={`Decide change request ${String(request.n)}`}
        className="ah-row"
        style={{ gap: 8 }}
      >
        <Button
          size="sm"
          variant="primary"
          icon="check"
          disabled={busy}
          onClick={() => {
            send("approved");
          }}
        >
          Approve plan {version(request.plan_to)}
        </Button>
        <Button
          size="sm"
          variant="danger"
          icon="x"
          disabled={busy}
          onClick={() => {
            send("declined");
          }}
        >
          Decline
        </Button>
      </div>
      {decide.isPending && (
        <span role="status" className="ah-small">
          Recording your decision…
        </span>
      )}
      {decide.isSuccess && (
        <span role="status" className="ah-small">
          Decision recorded in the hub. The next /implement of {request.ticket} reads it.
        </span>
      )}
      {decide.isError && <DecisionError error={decide.error} />}
    </div>
  );
}

/**
 * What the owner reads before deciding (A20): the request's evidence and proposal, what plan
 * drift means, and what approving does.
 */
function RequestEvidence({ request }: { request: ChangeRequestView }) {
  return (
    <div className="ah-stack" style={{ gap: 6 }}>
      <span className="ah-small">
        Plan drift: it changes an AC, a contract or another ticket, so {request.ticket} is paused
        until you answer.
      </span>
      {request.body && (
        <div className="ah-stack" style={{ gap: 4 }}>
          <span className="ah-row" style={{ gap: 6 }}>
            <ProvenanceBadge provenance="agent" />
          </span>
          <Markdown source={belowHeading(request.body, 5)} />
        </div>
      )}
      {request.body_cut && (
        <span className="ah-small">
          The request goes on past what is shown: read the full request in Brain before deciding.
        </span>
      )}
      <b className="ah-small" style={{ fontWeight: 500 }}>
        What changes if you approve
      </b>
      <ul className="ah-small" style={{ margin: 0, paddingLeft: 18 }}>
        <li>
          Plan {version(request.plan_from)} becomes {version(request.plan_to)} (a new amendment).
        </li>
        <li>{request.ticket} runs preflight again on the new plan.</li>
        {request.affected.length === 1 && (
          <li>{request.affected[0]} runs preflight again before it goes on.</li>
        )}
        {request.affected.length > 1 && (
          <li>{request.affected.join(", ")} run preflight again before they go on.</li>
        )}
        <li>Nothing is merged or pushed.</li>
      </ul>
    </div>
  );
}

/**
 * A plan change request the ticket asks: while open, what it says and its decision (the run's
 * gate while it waits there; the lost-run form when the server says the run is gone; else a line
 * that the run records it); once decided, who decided it, when and with what note.
 */
function ChangeRequestBlock({
  request,
  project,
  slug,
}: {
  request: ChangeRequestView;
  project: string;
  slug: string;
}) {
  const { tz } = usePreferences();
  const [decidedHere, setDecidedHere] = useState(false);
  const decidedLine = useRef<HTMLSpanElement>(null);
  const name = `Change request ${String(request.n)}`;
  const decision = request.decision;
  const settled = request.status !== "open" || decision !== null;
  const sentLine = useRef<HTMLSpanElement>(null);
  const sent = decidedHere && !settled && !request.approval_id && !request.decidable_here;
  useEffect(() => {
    // After a decision taken here, focus lands on the line that says where it is (U6, UX r3 1).
    if (settled && decidedHere) decidedLine.current?.focus();
    else if (sent) sentLine.current?.focus();
  }, [settled, decidedHere, sent]);
  if (settled) {
    return (
      <span ref={decidedLine} tabIndex={-1} id={requestAnchor(request.n)}>
        {decision
          ? `${name} ${decision.decision} by ${decision.decided_by} · ${evaluatedText(decision.decided_at, tz)}${decision.note ? `: ${decision.note}` : ""}`
          : `${name}: ${request.problem ?? "could not be read"}`}
      </span>
    );
  }
  let decide: ReactNode;
  if (request.approval_id) {
    decide = (
      <GateDecision
        approvalId={request.approval_id}
        requireTextFor={["decline"]}
        onDecided={() => {
          setDecidedHere(true);
        }}
      />
    );
  } else if (request.decidable_here) {
    decide = (
      <LostRunDecision
        project={project}
        slug={slug}
        request={request}
        onDecided={() => {
          setDecidedHere(true);
        }}
      />
    );
  } else if (decidedHere) {
    decide = (
      <span ref={sentLine} tabIndex={-1} role="status" className="ah-small ah-muted">
        Decision sent; the run records it and this shows it.
      </span>
    );
  } else {
    decide = (
      <span className="ah-small ah-muted">
        Its run is live and asks you at its gate; the decision shows here once the gate is open.
      </span>
    );
  }
  return (
    <section
      className="ah-stack"
      style={{ gap: 6 }}
      id={requestAnchor(request.n)}
      tabIndex={-1}
      aria-label={`Plan change request ${String(request.n)}`}
    >
      <span className="ah-row ah-wrap" style={{ gap: 8 }}>
        <h4 className="ah-small" style={{ margin: 0, fontWeight: 500 }}>
          Plan change request {request.n}: plan {version(request.plan_from)} →{" "}
          {version(request.plan_to)}
        </h4>
        <WaitAge openedAt={request.opened_at} />
      </span>
      {request.problem && <span className="ah-small">{request.problem}</span>}
      <RequestEvidence request={request} />
      <Link to={brainRoute(project, request.path)}>Read the request in Brain</Link>
      {decide}
    </section>
  );
}

/**
 * The Preflight step's evidence (two-level-flows AC-2.5, AC-2.8, AC-2.12, AC-2.14): the change
 * requests the ticket asks (with their decision) or is held by, then every run, newest first,
 * with each local note.
 */
function PreflightDetail({
  row,
  records,
  project,
  slug,
}: {
  row: TicketRow;
  records: TicketRecords;
  project: string;
  slug: string;
}) {
  const { tz } = usePreferences();
  const [params] = useSearchParams();
  const runs = [...(records.preflight?.runs ?? [])].reverse();
  const asked = records.change_requests.filter((request) => namesRow(row, request.ticket));
  const holding = records.change_requests.filter(
    (request) => request.status === "open" && !namesRow(row, request.ticket),
  );
  const atPreflight = (ticket: string) => {
    const next = new URLSearchParams(ticketSearch(params, ticket));
    next.set("step", "preflight");
    return `?${next.toString()}`;
  };
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      {asked.map((request) => (
        <ChangeRequestBlock key={request.n} request={request} project={project} slug={slug} />
      ))}
      {holding.map((request) => (
        <span key={request.n}>
          Held by{" "}
          <Link to={{ search: atPreflight(request.ticket ?? "") }} replace>
            change request {request.n} from {request.ticket}
          </Link>
          : it waits until you answer it.
        </span>
      ))}
      {records.preflight?.problem && <span>{records.preflight.problem}</span>}
      {runs.length > 0 && (
        <ol className="ah-stack" style={{ gap: 6, margin: 0, paddingLeft: 18 }}>
          {runs.map((run, index) => (
            <li key={index}>
              {fmtDateTime(run.ran_at, tz)} · checked plan v{run.plan_version} against main at{" "}
              <IdChip id={run.commit} short={run.commit.slice(0, 7)} kind="commit" /> ·{" "}
              {DRIFT_WORDS[run.drift]}
              {run.input_text && (
                <span className="ah-small ah-muted">
                  {" "}
                  · {run.input === "discovery" ? "after a discovery" : "after a decline"}:{" "}
                  {run.input_text}
                </span>
              )}
              {run.local_notes.length > 0 && (
                <div className="ah-small">
                  Local drift · {plural(run.local_notes.length, "note")}
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {run.local_notes.map((note, at) => (
                      <li key={at}>{note}</li>
                    ))}
                  </ul>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function StepDetail({
  step,
  row,
  project,
  slug,
  latest,
  records,
}: {
  step: StepperStep<TicketStepName>;
  row: TicketRow;
  project: string;
  slug: string;
  /** The newest eval naming the ticket, with its label ("Eval 1"). */
  latest: { record: EvalRecord; label: string } | undefined;
  /** Its records from the per-ticket route (A7), as the query holds them. */
  records: TicketRecordsQuery;
}) {
  const [params] = useSearchParams();
  const { tz } = usePreferences();
  const unrecorded = step.state === "unrecorded";
  const id = row.id ?? row.ref;
  const found = records.data;
  const discoveries = (found?.preflight?.runs ?? []).filter((run) => run.input === "discovery");
  // The step card says the outcome above the detail: the detail never repeats it.
  const outcome = stepOutcome(step);
  const unsaid = (text: string) => (text === outcome ? null : text);
  if (step.name === "preflight" && step.state !== "pending" && step.state !== "unrecorded") {
    // The ticket's own records say more than its step: wait for them, or say why they failed.
    if (records.isPending) return <Skeleton width="80%" height={16} />;
    if (records.isError) {
      return (
        <ProblemError
          compact
          title="Could not load this ticket's records"
          detail={records.error.detail ?? undefined}
          status={records.error.status}
          onRetry={() => void records.refetch()}
        />
      );
    }
  }
  if (step.name === "preflight" && found && (found.preflight || found.change_requests.length)) {
    return <PreflightDetail row={row} records={found} project={project} slug={slug} />;
  }
  switch (step.name) {
    case "context":
    case "preflight":
      if (unrecorded) {
        return (
          <>Not recorded: tickets picked up before /implement have no context brief or preflight.</>
        );
      }
      return <>{step.state === "pending" ? NOT_REACHED : unsaid(step.meta ?? NOT_REACHED)}</>;
    case "implement":
      return (
        <>
          {step.state === "done"
            ? "A review round exists."
            : unrecorded
              ? "Not recorded."
              : unsaid(step.meta ?? NOT_REACHED)}
          {discoveries.length > 0 && (
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {discoveries.map((run, index) => (
                <li key={index}>
                  Discovery {fmtDateTime(run.ran_at, tz)}: {run.input_text}. Preflight ran again.
                </li>
              ))}
            </ul>
          )}
        </>
      );
    case "review":
      if (step.state === "pending") return <>{NOT_REACHED}</>;
      if (unrecorded) return <>Not recorded: no review record names this ticket.</>;
      return (
        <>
          {outcome === null && `${step.meta ?? "Approved"}. `}
          <Link to={brainRoute(project, `features/${slug}/reviews/${id}.md`)}>
            Open the review record in Brain
          </Link>
        </>
      );
    case "eval":
      if (!latest) return <>{unrecorded ? "Not recorded." : NOT_REACHED}</>;
      return (
        <>
          {latest.record.verdict}
          {latest.record.evaluated_at &&
            ` · ${evaluatedText(latest.record.evaluated_at, tz)}`}.{" "}
          <Link
            to={{ search: evalSearch(params, latest.record.delivery) }}
            replace
            state={FOCUS_EVAL}
          >
            Open {latest.label} in the Eval tab
          </Link>
        </>
      );
    case "pr":
      return row.pr_url ? <TicketPrLinks row={row} /> : <>No PR recorded.</>;
    case "merged":
      if (step.state === "done") return <>Done in Linear.</>;
      return (
        <>
          {step.state === "unknown" ? unsaid(step.meta ?? GOLDEN_STATE_TEXT.unknown) : NOT_REACHED}
        </>
      );
  }
}

/**
 * One section of the panel: its `h3`, a short summary beside it ("4 of 7") and an optional slot
 * on the right (the AC meter); sections are told apart by a hairline, not a colour.
 */
function Section({
  title,
  summary,
  aside,
  children,
}: {
  title: string;
  summary?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section className="ah-ticket-panel-section" aria-labelledby={headingId}>
      <div className="ah-ticket-panel-section-head">
        <h3 id={headingId} className="ah-small">
          {title}
        </h3>
        {summary != null && summary !== "" && <span className="ah-small ah-subtle">{summary}</span>}
        {aside != null && <span className="ah-ticket-panel-section-aside">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

/** How many dependency rows one sub-list shows before the rest fold away. */
const DEPENDENCIES_SHOWN = 8;

interface Dependency {
  ref: string;
  /** Where a blocker edge comes from; none for the tickets it blocks. */
  source?: EdgeSource | undefined;
}

/** A dependency as a row draws it: the ticket of this feature, or the tracker issue outside it. */
function resolve(
  dependency: Dependency,
  rows: readonly TicketRow[],
  external: readonly ExternalBlocker[],
) {
  const row = rows.find((r) => r.ref === dependency.ref);
  const outside = row ? undefined : external.find((b) => b.id === dependency.ref);
  const done = row
    ? row.readiness === "done" || row.readiness === "canceled"
    : (outside?.done ?? false);
  return { ...dependency, row, outside, done };
}

/** An issue outside the feature, as Linear names its state; Unknown when it was not read. */
function OutsideBadge({ blocker }: { blocker: ExternalBlocker }) {
  if (!blocker.state) {
    return (
      <StatusBadge
        status="idle"
        quiet
        label="Unknown"
        title="No status: Linear was not read for this issue"
      />
    );
  }
  return (
    <StatusBadge
      status={STATE_STATUS[blocker.state.type]}
      label={blocker.state.name}
      title={`${blocker.state.name} (${blocker.state.type})`}
    />
  );
}

/**
 * Other tickets as rows: each one's status, then one link on its id and title that opens its own
 * panel in place; an issue outside the feature links to Linear. Not done first, done last.
 */
function TicketRefRows({
  dependencies,
  rows,
  external,
  onOpen,
}: {
  dependencies: readonly Dependency[];
  rows: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  onOpen: TicketOpener;
}) {
  const items = dependencies
    .map((dependency) => resolve(dependency, rows, external))
    .sort((a, b) => Number(a.done) - Number(b.done));
  const list = (part: typeof items) => (
    <ul className="ah-ticket-panel-rows">
      {part.map(({ ref, source, row, outside }) => (
        <li key={ref} className="ah-ticket-dep-row" title={source ? EDGE_TITLE[source] : undefined}>
          <span className="ah-ticket-dep-badge">
            {row ? <StateBadge row={row} /> : outside && <OutsideBadge blocker={outside} />}
          </span>
          {row ? (
            <TicketOpenLink
              row={row}
              onOpen={onOpen}
              className="ah-ticket-dep-link"
              title={row.title ?? undefined}
            >
              <span className="ah-mono">{ref}</span>{" "}
              {row.title && <span className="ah-small ah-ticket-panel-clamp">{row.title}</span>}
            </TicketOpenLink>
          ) : outside ? (
            <span className="ah-ticket-dep-link">
              <LinearLink id={ref} url={outside.url} />{" "}
              {outside.title && (
                <span className="ah-small ah-ticket-panel-clamp" title={outside.title}>
                  {outside.title}
                </span>
              )}
            </span>
          ) : (
            <span className="ah-mono">{ref}</span>
          )}
        </li>
      ))}
    </ul>
  );
  const rest = items.length - DEPENDENCIES_SHOWN;
  return (
    <div className="ah-stack" style={{ gap: 4 }}>
      {list(rest > 0 ? items.slice(0, DEPENDENCIES_SHOWN) : items)}
      {rest > 0 && (
        <details className="ah-ticket-panel-more">
          <summary className="ah-small">
            Show {rest} more ticket{rest === 1 ? "" : "s"}
          </summary>
          {list(items.slice(DEPENDENCIES_SHOWN))}
        </details>
      )}
    </div>
  );
}

/** "all 1 done", "1 of 2 not done", or "none". */
function blockedBySummary(items: readonly { done: boolean }[]): string {
  if (items.length === 0) return "none";
  const open = items.filter((item) => !item.done).length;
  if (open === 0) return `all ${String(items.length)} done`;
  return `${String(open)} of ${String(items.length)} not done`;
}

/** "7, none started", "7 · 2 in progress", "7 · 3 done", or "none". */
function blocksSummary(items: readonly { done: boolean; row?: TicketRow | undefined }[]): string {
  if (items.length === 0) return "none";
  const total = String(items.length);
  const started = items.filter((item) => item.row?.readiness === "in_progress").length;
  if (started > 0) return `${total} · ${String(started)} in progress`;
  const done = items.filter((item) => item.done).length;
  if (done > 0) return `${total} · ${String(done)} done`;
  return `${total}, none started`;
}

/** What the ticket waits on and what it holds back, each as rows of tickets. */
function Dependencies({
  row,
  data,
  onOpen,
}: {
  row: TicketRow;
  data: FeatureTickets;
  onOpen: TicketOpener;
}) {
  const external = data.planning.external_blockers;
  const blockedBy: Dependency[] = row.blocked_by.map((edge) => ({
    ref: edge.ref,
    source: edge.source,
  }));
  const blocks: Dependency[] = row.blocks.map((ref) => ({ ref }));
  const sub = (title: string, dependencies: Dependency[], summary: string) => (
    <div className="ah-stack" style={{ gap: 4 }}>
      <h4 className="ah-small ah-ticket-panel-sub">
        {title} <span className="ah-subtle">· {summary}</span>
      </h4>
      {dependencies.length > 0 && (
        <TicketRefRows
          dependencies={dependencies}
          rows={data.tickets}
          external={external}
          onOpen={onOpen}
        />
      )}
    </div>
  );
  const resolved = (list: Dependency[]) => list.map((d) => resolve(d, data.tickets, external));
  return (
    <Section title="Dependencies">
      {sub("Blocked by", blockedBy, blockedBySummary(resolved(blockedBy)))}
      {sub("Blocks", blocks, blocksSummary(resolved(blocks)))}
    </Section>
  );
}

/** The ticket's sessions as rows, the count beside the heading ("3+" when there are more). */
function SessionsSection({ row, project }: { row: TicketRow; project: string }) {
  const sessions = useTicketSessions(project, row);
  const count =
    row.id && sessions.data
      ? `${String(sessions.data.items.length)}${sessions.data.next_cursor ? "+" : ""}`
      : undefined;
  return (
    <Section title="Sessions" summary={count}>
      <TicketSessions row={row} project={project} variant="row" shown={3} />
    </Section>
  );
}

/**
 * The open step's card: where it is in the seven, its state in words, how it came out, its
 * evidence; on the current step, the readiness line; on another, the way back to the current one.
 */
function StepCard({
  step,
  flow,
  readiness,
  onShowCurrent,
  children,
}: {
  step: StepperStep<TicketStepName>;
  flow: NonNullable<TicketRow["flow"]>;
  readiness: ReactNode;
  onShowCurrent: () => void;
  children: ReactNode;
}) {
  const position = flow.steps.findIndex((s) => s.name === step.name) + 1;
  const place = `${TICKET_STEP_LABEL[step.name]} · step ${String(position)} of ${String(flow.steps.length)}`;
  const current = step.name === flow.current;
  const look = STEP_STATUS[step.state];
  const outcome = stepOutcome(step);
  return (
    <section className="ah-ticket-step-card" aria-label={place}>
      <div className="ah-ticket-step-card-head">
        <span className="ah-small ah-muted">
          {current && "Current step · "}
          {place}
        </span>
        <StatusBadge
          status={look.status}
          quiet={look.quiet}
          label={GOLDEN_STATE_TEXT[step.state]}
        />
      </div>
      {outcome && <p className="ah-ticket-step-outcome">{outcome}</p>}
      <div className="ah-small ah-ticket-step-detail">{children}</div>
      {current ? (
        <div className="ah-small ah-ticket-step-ready">{readiness}</div>
      ) : (
        <span>
          <Button size="sm" variant="ghost" onClick={onShowCurrent}>
            Show the current step ({TICKET_STEP_LABEL[flow.current]})
          </Button>
        </span>
      )}
    </section>
  );
}

export interface TicketPanelProps {
  project: string;
  slug: string;
  data: FeatureTickets;
  /** `?ticket=`: a tracker id or a plan key. */
  ticket: string;
  /** The ticket it names, if it is one of the feature's. */
  row: TicketRow | undefined;
  evals: readonly EvalRecord[];
  acPasses?: Readonly<Record<string, boolean>> | undefined;
  acRows?: ReadonlyMap<string, AcRow> | undefined;
  openerRef: RefObject<HTMLElement | null>;
  /** Another ticket was opened from inside the panel. */
  onOpen: TicketOpener;
  onClose: () => void;
}

/**
 * The ticket panel (two-level-flows AC-1.10, ux-change-ticket-panel.md): one ticket's head and
 * facts, one callout for whatever waits on the owner or holds the ticket, its seven steps across
 * with the open one's evidence in a card under them, then its ACs, dependencies and sessions as
 * rows, read from the tickets route (A7). No Start: Start stays once per view, on the card or the
 * row (A15).
 */
export function TicketPanel({
  project,
  slug,
  data,
  ticket,
  row,
  evals,
  acPasses,
  acRows,
  openerRef,
  onOpen,
  onClose,
}: TicketPanelProps) {
  const [params, setParams] = useSearchParams();
  const records = useTicketRecords(project, slug, ticket);
  const body = useRef<HTMLDivElement>(null);
  const shell = (title: ReactNode, children: ReactNode) => (
    <SidePanel
      key={ticket}
      title={title}
      closeLabel={`Close ticket ${ticket}`}
      openerRef={openerRef}
      onClose={onClose}
    >
      {children}
    </SidePanel>
  );
  if (!row?.flow) {
    const epic = row !== undefined && data.planning.epics.includes(row.ref);
    return shell(
      `Ticket ${ticket}`,
      <div className="ah-stack" style={{ gap: 8 }}>
        {row?.id && <LinearLink id={row.id} url={row.url} />}
        <EmptyState
          icon="list-todo"
          title={
            epic
              ? `${ticket} is this feature's epic: it has no steps of its own.`
              : `${ticket} is not a ticket of this feature.`
          }
          action={
            <Button size="sm" onClick={onClose}>
              Close panel
            </Button>
          }
        >
          {epic && "Its tickets are listed in the Tickets tab."}
        </EmptyState>
      </div>,
    );
  }
  const flow = row.flow;
  const id = ticketParam(row);
  const ids = data.tickets.map(ticketParam);
  const group = evalHistory(evals, ids, data.planning.epics).find((g) => g.scope === id);
  const newest = group?.evals.find((e) => e.provenance !== "owner");
  const latest = group &&
    newest && {
      record: newest,
      label: runLabels(group.evals).get(newest.path) ?? newest.delivery,
    };
  const waiting = ownerStepsWaiting(evals, ids, data.planning.epics).find((w) => w.scope === id);
  const open = params.has("step") ? (params.get("step") as TicketStepName) : flow.current;
  // The ticket's own open plan change request: the panel's one primary act (U12).
  const asking = records.data?.change_requests.find(
    (request) => request.status === "open" && namesRow(row, request.ticket),
  );
  const setStep = (step: string) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set("step", step);
        return next;
      },
      { replace: true },
    );
  };
  const toggle = (step: TicketStepName) => {
    setStep(step === open ? "" : step);
  };
  const showCurrent = () => {
    setStep(flow.current);
    // The card's button goes away with the card: focus lands on the current step's button.
    requestAnimationFrame(() => {
      body.current
        ?.querySelector<HTMLElement>(`.ah-golden-select[data-step="${flow.current}"]`)
        ?.focus();
    });
  };
  const kind = signalKind(flow);
  const critical =
    data.planning.critical_path.length > 1 && data.planning.critical_path.includes(row.ref);
  const at = flow.steps.findIndex((s) => s.name === flow.current);
  const merged = flow.current === "merged" && flow.steps[at]?.state === "done";
  const total = String(flow.steps.length);
  const stepsSummary = merged ? `${total} of ${total} · merged` : `${String(at + 1)} of ${total}`;

  // What waits on the owner comes first and amber; a hold or a re-run only when nothing does.
  const ownerLines: ReactNode[] = [];
  if (asking) {
    ownerLines.push(
      <div key="asking" className="ah-ticket-callout-line">
        <span>
          <b style={{ fontWeight: 500 }}>
            Waiting for you: plan change request {asking.n}, plan {version(asking.plan_from)} →{" "}
            {version(asking.plan_to)}
          </b>{" "}
          <WaitAge openedAt={asking.opened_at} />
        </span>
        <Button
          size="sm"
          variant="primary"
          icon="arrow-right"
          onClick={() => {
            setStep("preflight");
            // The request's block is drawn once Preflight opens: focus it then (U12).
            requestAnimationFrame(() => {
              document.getElementById(requestAnchor(asking.n))?.focus();
            });
          }}
        >
          Review change request
        </Button>
      </div>,
    );
  } else if (kind === "waiting") {
    // Its own request waits, its record not read yet: the signal's words until it is.
    ownerLines.push(
      <div key="signal" className="ah-ticket-callout-line">
        <b style={{ fontWeight: 500 }}>{flow.signal}</b>
      </div>,
    );
  }
  if (waiting) {
    ownerLines.push(
      <div key="owner-steps" className="ah-ticket-callout-line">
        <b style={{ fontWeight: 500 }}>Waiting for you: {waiting.label} passed with owner steps</b>
        <Link
          to={{ search: evalSearch(params, waiting.record.delivery) }}
          replace
          state={FOCUS_EVAL}
        >
          Settle them in the Eval tab
        </Link>
      </div>,
    );
  }
  let callout: ReactNode = null;
  if (ownerLines.length > 0) {
    callout = (
      <Banner tone="warning" icon="hand" boxed live={false}>
        <div className="ah-stack" style={{ gap: 6 }}>
          {ownerLines}
        </div>
      </Banner>
    );
  } else if (kind === "held" || kind === "stale") {
    callout = (
      <Banner tone="info" icon={kind === "held" ? "circle-pause" : "clock"} boxed live={false}>
        <b style={{ fontWeight: 500 }}>{flow.signal}</b>
      </Banner>
    );
  }

  const heading = (
    <>
      {/* The spaces sit between the spans: a name is read from each span's trimmed text. */}
      <span className="ah-sr">Ticket</span>{" "}
      <span className="ah-ticket-panel-id" data-alone={row.title ? undefined : true}>
        {row.ref}
      </span>
      {row.title && (
        <>
          {" "}
          <span className="ah-sr">·</span>{" "}
          <span className="ah-ticket-panel-title">{row.title}</span>
        </>
      )}
    </>
  );
  return shell(
    heading,
    <div ref={body} className="ah-ticket-panel">
      <div className="ah-ticket-panel-facts">
        <StateBadge row={row} />
        <TicketIdLine row={row} />
        <span className="ah-small ah-ticket-panel-fact">
          <Icon name="user" size="sm" />
          <span className="ah-sr">Assignee: </span>
          <Assignee row={row} />
        </span>
        <TicketPrLinks row={row} />
        {critical && (
          <span
            className="ah-small ah-flow-critical ah-ticket-panel-fact"
            title="On the longest chain of tickets not done"
          >
            Critical path
          </span>
        )}
      </div>
      {callout}
      <Section title="Steps" summary={stepsSummary}>
        <GoldenPathStepper
          steps={flow.steps}
          labels={TICKET_STEP_LABEL}
          label="Steps"
          open={open}
          onSelect={toggle}
          orientation="horizontal"
          detailPlacement="below"
          selectLabel={(name) => {
            const step = flow.steps.find((s) => s.name === name);
            const state = step ? GOLDEN_STATE_TEXT[step.state].toLowerCase() : "";
            // A meta that only repeats the state's word is said once (U8).
            const meta =
              step?.meta && step.meta.toLowerCase() !== state ? `, ${step.meta.toLowerCase()}` : "";
            return `${TICKET_STEP_LABEL[name]}, ${state}${meta}, ${name === open ? "hide" : "show"} details`;
          }}
          detail={(step) => (
            <StepCard
              step={step}
              flow={flow}
              onShowCurrent={showCurrent}
              readiness={
                <ReadinessText
                  row={row}
                  rows={data.tickets}
                  external={data.planning.external_blockers}
                  withIcon
                />
              }
            >
              <StepDetail
                step={step}
                row={row}
                project={project}
                slug={slug}
                latest={latest}
                records={records}
              />
            </StepCard>
          )}
        />
      </Section>
      <Section title="Acceptance criteria" aside={<AcCount row={row} acPasses={acPasses} />}>
        <AcList ids={row.acs} acPasses={acPasses} acRows={acRows} layout="rows" />
      </Section>
      <Dependencies row={row} data={data} onOpen={onOpen} />
      <SessionsSection row={row} project={project} />
    </div>,
  );
}
