import {
  Fragment,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
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
  LinearLink,
  ReadinessText,
  StateBadge,
  TICKET_STEP_LABEL,
  TicketOpenLink,
  TicketPrLink,
  TicketSignal,
  signalKind,
  ticketParam,
  ticketSearch,
  type TicketOpener,
} from "./PlanningView";
import { useDecideChangeRequest, useTicketRecords } from "./queries";
import { AcList, TicketSessions } from "./TicketsTab";

type FeatureTickets = components["schemas"]["FeatureTickets"];
type TicketRow = components["schemas"]["TicketRow"];
type TicketStepName = components["schemas"]["TicketStepName"];
type EvalRecord = components["schemas"]["EvalRecord"];
type AcRow = components["schemas"]["AcRow"];
type TicketRecords = components["schemas"]["TicketRecords"];
type TicketRecordsQuery = ReturnType<typeof useTicketRecords>;
type ChangeRequestView = components["schemas"]["ChangeRequestView"];
type PreflightRun = components["schemas"]["PreflightRun"];

const NOT_REACHED = "Not reached.";

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
      return <>{step.state === "pending" ? NOT_REACHED : (step.meta ?? NOT_REACHED)}</>;
    case "implement":
      return (
        <>
          {step.state === "done"
            ? "A review round exists."
            : unrecorded
              ? "Not recorded."
              : (step.meta ?? NOT_REACHED)}
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
          {step.meta ?? "Approved"}.{" "}
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
      return row.pr_url ? <TicketPrLink row={row} /> : <>No PR recorded.</>;
    case "merged":
      if (step.state === "done") return <>Done in Linear.</>;
      return (
        <>{step.state === "unknown" ? (step.meta ?? GOLDEN_STATE_TEXT.unknown) : NOT_REACHED}</>
      );
  }
}

/** Other tickets named by `refs`, each opening its own panel in place; plain text otherwise. */
function TicketRefs({
  refs,
  rows,
  onOpen,
}: {
  refs: readonly string[];
  rows: readonly TicketRow[];
  onOpen: TicketOpener;
}) {
  if (refs.length === 0) return <span className="ah-subtle">—</span>;
  return (
    <>
      {refs.map((ref, i) => {
        const row = rows.find((r) => r.ref === ref);
        return (
          <Fragment key={ref}>
            {i > 0 && ", "}
            {row ? (
              <TicketOpenLink row={row} onOpen={onOpen} className="ah-mono">
                {ref}
              </TicketOpenLink>
            ) : (
              <span className="ah-mono">{ref}</span>
            )}
          </Fragment>
        );
      })}
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="ah-stack" style={{ gap: 6 }}>
      <h3 className="ah-small ah-muted" style={{ margin: 0, fontWeight: 500 }}>
        {title}
      </h3>
      {children}
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
 * The ticket panel (two-level-flows AC-1.10, ux-new-ticket-panel.md Addendum 1): one ticket's
 * seven steps (the current one, or `?step=`, disclosed), its ACs, blockers and sessions, read from
 * the tickets route (A7). Its one signal points to the Eval tab when a ticket eval waits on owner
 * steps. No Start: Start stays once per view, on the card or the row (A15).
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
  const shell = (title: string, children: ReactNode) => (
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
  const toggle = (step: TicketStepName) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set("step", step === open ? "" : step);
        return next;
      },
      { replace: true },
    );
  };
  const title = `Ticket ${row.ref}${row.title ? ` · ${row.title}` : ""}`;
  return shell(
    title,
    <div className="ah-stack" style={{ gap: 16 }}>
      <div className="ah-stack" style={{ gap: 6 }}>
        <span className="ah-row ah-wrap ah-small" style={{ gap: 8 }}>
          {row.id && <LinearLink id={row.id} url={row.url} />}
          <StateBadge row={row} />
          {row.assignee && <span>{row.assignee}</span>}
        </span>
        <ReadinessText row={row} rows={data.tickets} external={data.planning.external_blockers} />
        {asking && (
          <span>
            <Button
              size="sm"
              variant="primary"
              icon="arrow-right"
              onClick={() => {
                setParams(
                  (current) => {
                    const next = new URLSearchParams(current);
                    next.set("step", "preflight");
                    return next;
                  },
                  { replace: true },
                );
                // The request's block is drawn once Preflight opens: focus it then (U12).
                requestAnimationFrame(() => {
                  document.getElementById(requestAnchor(asking.n))?.focus();
                });
              }}
            >
              Review change request
            </Button>
          </span>
        )}
      </div>
      {signalKind(flow) !== null && signalKind(flow) !== "local" && (
        <p className="ah-small" style={{ margin: 0 }}>
          <TicketSignal flow={flow} />
        </p>
      )}
      {waiting && (
        <p className="ah-small ah-row ah-wrap" style={{ gap: 6, margin: 0 }}>
          <Icon name="hand" size="sm" />
          <b style={{ fontWeight: 500 }}>
            Waiting for you: {waiting.label} passed with owner steps
          </b>
          <Link
            to={{ search: evalSearch(params, waiting.record.delivery) }}
            replace
            state={FOCUS_EVAL}
          >
            Settle them in the Eval tab
          </Link>
        </p>
      )}
      <Section title="Steps">
        <GoldenPathStepper
          steps={flow.steps}
          labels={TICKET_STEP_LABEL}
          label="Steps"
          open={open}
          onSelect={toggle}
          selectLabel={(name) => {
            const step = flow.steps.find((s) => s.name === name);
            const state = step ? GOLDEN_STATE_TEXT[step.state].toLowerCase() : "";
            // A meta that only repeats the state's word is said once (U8).
            const meta =
              step?.meta && step.meta.toLowerCase() !== state ? `, ${step.meta.toLowerCase()}` : "";
            return `${TICKET_STEP_LABEL[name]}, ${state}${meta}, ${name === open ? "hide" : "show"} details`;
          }}
          detail={(step) => (
            <StepDetail
              step={step}
              row={row}
              project={project}
              slug={slug}
              latest={latest}
              records={records}
            />
          )}
        />
      </Section>
      <Section title="Acceptance criteria">
        <AcList ids={row.acs} acPasses={acPasses} acRows={acRows} />
      </Section>
      <Section title="Blocked by">
        <span>
          <TicketRefs refs={row.blocked_by.map((e) => e.ref)} rows={data.tickets} onOpen={onOpen} />
        </span>
      </Section>
      <Section title="Blocks">
        <span>
          <TicketRefs refs={row.blocks} rows={data.tickets} onOpen={onOpen} />
        </span>
      </Section>
      <Section title="Sessions">
        <TicketSessions row={row} project={project} />
      </Section>
    </div>,
  );
}
