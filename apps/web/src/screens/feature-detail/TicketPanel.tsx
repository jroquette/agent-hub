import { Fragment, type ReactNode, type RefObject } from "react";
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
import { FOCUS_EVAL, evalHistory, evalSearch, ownerStepsWaiting, runLabels } from "./EvalTab";
import {
  LinearLink,
  ReadinessText,
  StateBadge,
  TICKET_STEP_LABEL,
  TicketOpenLink,
  TicketPrLink,
  ticketParam,
  type TicketOpener,
} from "./PlanningView";
import { AcList, TicketSessions } from "./TicketsTab";

type FeatureTickets = components["schemas"]["FeatureTickets"];
type TicketRow = components["schemas"]["TicketRow"];
type TicketStepName = components["schemas"]["TicketStepName"];
type EvalRecord = components["schemas"]["EvalRecord"];
type AcRow = components["schemas"]["AcRow"];

const NOT_REACHED = "Not reached.";

/** What one step of a ticket says it is, from the records S1 reads (Addendum 1). */
function StepDetail({
  step,
  row,
  project,
  slug,
  latest,
}: {
  step: StepperStep<TicketStepName>;
  row: TicketRow;
  project: string;
  slug: string;
  /** The newest eval naming the ticket, with its label ("Eval 1"). */
  latest: { record: EvalRecord; label: string } | undefined;
}) {
  const [params] = useSearchParams();
  const unrecorded = step.state === "unrecorded";
  const id = row.id ?? row.ref;
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
              : NOT_REACHED}
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
          {latest.record.evaluated_at && ` · ${latest.record.evaluated_at}`}.{" "}
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
      {waiting && (
        <p className="ah-small ah-row ah-wrap" style={{ gap: 6, margin: 0 }}>
          <Icon name="hand" size="sm" />
          <b style={{ fontWeight: 500 }}>Waiting on you: {waiting.label} passed with owner steps</b>
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
            <StepDetail step={step} row={row} project={project} slug={slug} latest={latest} />
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
