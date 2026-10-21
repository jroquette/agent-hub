import { Fragment, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { Link, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  Button,
  EmptyState,
  GOLDEN_STATE_TEXT,
  GoldenPathStepper,
  Icon,
  SidePanel,
  type StepperStep,
} from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { fmtDateTime } from "../../lib/format";
import { GateDecision } from "../approvals/GateDecision";
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
type ChangeRequestView = components["schemas"]["ChangeRequestView"];
type PreflightRun = components["schemas"]["PreflightRun"];

const NOT_REACHED = "Not reached.";

const DRIFT_WORDS: Record<PreflightRun["drift"], string> = {
  none: "no drift",
  local: "local drift",
  plan: "plan drift",
};

const plural = (n: number, word: string) => `${String(n)} ${word}${n === 1 ? "" : "s"}`;

/** Whether `name` is one of `row`'s refs (its key, its tracker id), in any case. */
function namesRow(row: TicketRow, name: string | null | undefined): boolean {
  const upper = name?.toUpperCase();
  return [row.key, row.id, row.ref].some((ref) => ref != null && ref.toUpperCase() === upper);
}

/**
 * The owner's decision on a change request whose run has no open gate (two-level-flows AC-2.14):
 * Approve, or Decline with the note the next preflight follows (AC-2.12), recorded in the hub.
 */
function LostRunDecision({
  project,
  slug,
  request,
}: {
  project: string;
  slug: string;
  request: ChangeRequestView;
}) {
  const decide = useDecideChangeRequest(project, slug, request.n);
  const [note, setNote] = useState("");
  const [needsNote, setNeedsNote] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const fieldId = useId();
  const hintId = useId();
  const send = (decision: "approved" | "declined") => {
    const text = note.trim();
    if (decision === "declined" && !text) {
      setNeedsNote(true);
      field.current?.focus();
      return;
    }
    decide.mutate({ decision, note: text || null });
  };
  return (
    <div className="ah-stack" style={{ gap: 6 }}>
      <span className="ah-small ah-muted">
        Its run has no open gate (abandoned, or its record lost): your decision is recorded in the
        hub, and the next /implement of {request.ticket} reads it.
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
        disabled={decide.isPending}
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
          disabled={decide.isPending}
          onClick={() => {
            send("approved");
          }}
        >
          Approve plan v{request.plan_to}
        </Button>
        <Button
          size="sm"
          variant="danger"
          icon="x"
          disabled={decide.isPending}
          onClick={() => {
            send("declined");
          }}
        >
          Decline
        </Button>
      </div>
      {decide.isError && (
        <span role="alert" className="ah-small">
          Could not record your decision: {decide.error.detail ?? decide.error.title}
        </span>
      )}
    </div>
  );
}

/**
 * A plan change request the ticket asks: while open, its decision (the run's gate when it waits,
 * else the lost-run form); once decided, who decided it, when and with what note.
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
  const name = `Change request ${String(request.n)}`;
  const decision = request.decision;
  if (request.status !== "open" || decision) {
    return (
      <span>
        {decision
          ? `${name} ${decision.decision} by ${decision.decided_by} · ${evaluatedText(decision.decided_at, tz)}${decision.note ? `: ${decision.note}` : ""}`
          : `${name}: ${request.problem ?? "could not be read"}`}
      </span>
    );
  }
  return (
    <div className="ah-stack" style={{ gap: 6 }}>
      <b style={{ fontWeight: 500 }}>
        Plan change request {request.n}: plan v{request.plan_from ?? "?"} → v{request.plan_to}
      </b>
      {request.affected.length > 0 && (
        <span className="ah-small">Affects {request.affected.join(", ")}</span>
      )}
      {request.problem && <span className="ah-small">{request.problem}</span>}
      <Link to={brainRoute(project, request.path)}>Read the request in Brain</Link>
      {request.approval_id ? (
        <GateDecision approvalId={request.approval_id} requireTextFor={["decline"]} />
      ) : (
        <LostRunDecision project={project} slug={slug} request={request} />
      )}
    </div>
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
  const runs = [...(records.preflight?.runs ?? [])].reverse();
  const asked = records.change_requests.filter((request) => namesRow(row, request.ticket));
  const holding = records.change_requests.filter(
    (request) => request.status === "open" && !namesRow(row, request.ticket),
  );
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      {asked.map((request) => (
        <ChangeRequestBlock key={request.n} request={request} project={project} slug={slug} />
      ))}
      {holding.map((request) => (
        <span key={request.n}>
          Held by change request {request.n} from {request.ticket}: it waits until you answer it.
        </span>
      ))}
      {records.preflight?.problem && <span>{records.preflight.problem}</span>}
      {runs.length > 0 && (
        <ol className="ah-stack" style={{ gap: 6, margin: 0, paddingLeft: 18 }}>
          {runs.map((run, index) => (
            <li key={index}>
              {fmtDateTime(run.ran_at, tz)} · checked plan v{run.plan_version} against main at{" "}
              <span className="ah-mono">{run.commit.slice(0, 7)}</span> ·{" "}
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

/** What one step of a ticket says it is, from the records S1 reads (Addendum 1). */
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
  /** Its records from the per-ticket route (A7); undefined until read, or when not read. */
  records?: TicketRecords | undefined;
}) {
  const [params] = useSearchParams();
  const { tz } = usePreferences();
  const unrecorded = step.state === "unrecorded";
  const id = row.id ?? row.ref;
  const discoveries = (records?.preflight?.runs ?? []).filter((run) => run.input === "discovery");
  if (step.name === "preflight" && records && (records.preflight || records.change_requests.length)) {
    return <PreflightDetail row={row} records={records} project={project} slug={slug} />;
  }
  switch (step.name) {
    case "context":
    case "preflight":
      return unrecorded ? (
        <>Not recorded: tickets picked up before /implement have no context brief or preflight.</>
      ) : (
        <>{NOT_REACHED}</>
      );
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
      </div>
      {signalKind(flow) !== null && signalKind(flow) !== "local" && (
        <p className="ah-small" style={{ margin: 0 }}>
          <TicketSignal flow={flow} />
        </p>
      )}
      {waiting && (
        <p className="ah-small ah-row ah-wrap" style={{ gap: 6, margin: 0 }}>
          <Icon name="hand" size="sm" />
          <b style={{ fontWeight: 500 }}>Waiting for you: {waiting.label} passed with owner steps</b>
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
            const meta = step?.meta ? `, ${step.meta.toLowerCase()}` : "";
            return `${TICKET_STEP_LABEL[name]}, ${state}${meta}, ${name === open ? "hide" : "show"} details`;
          }}
          detail={(step) => (
            <StepDetail
              step={step}
              row={row}
              project={project}
              slug={slug}
              latest={latest}
              records={records.data}
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
