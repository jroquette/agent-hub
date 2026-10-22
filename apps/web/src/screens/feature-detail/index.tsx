import {
  Fragment,
  useEffect,
  useId,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Banner,
  Button,
  DerivedLabel,
  EmptyState,
  GoldenPathStepper,
  Icon,
  ProblemError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Tabs,
  Tooltip,
} from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useCollectorState } from "../../shell/GlobalStream";
import {
  DiscussButton,
  useDiscuss,
  useDiscussTarget,
  type DiscussTarget,
} from "../../shell/discuss";
import { FeatureNameField, RenameButton, useFeatureNames } from "../features/names";
import { AcBar, PHASES, VERDICT_STATUS } from "../features/parts";
import { ApproveRecord, sessionName } from "./ApproveRecord";
import { QuestionsLink } from "./QuestionsBlock";
import { NoteView } from "../brain/NoteView";
import { NotFoundBody } from "../not-found";
import { CriteriaTab, passOf } from "./CriteriaTab";
import {
  EvalTab,
  FOCUS_EVAL,
  evalHistory,
  evalSearch,
  ownerStepsWaiting,
  pickEval,
  runLabels,
  signableLine,
} from "./EvalTab";
import { RecordSummary, summaryRequest } from "./RecordSummary";
import { StateBadge, ticketSearch } from "./PlanningView";
import { TicketsTab } from "./TicketsTab";
import { WaitAge } from "./TicketPanel";
import { useFeature, useFeatureSession, useFeatureTickets } from "./queries";

type Detail = components["schemas"]["FeatureDetail"];
type AgentSession = components["schemas"]["AgentSession"];
type AcRow = components["schemas"]["AcRow"];

export { acReference, allCommands } from "./CriteriaTab";
type TicketRow = components["schemas"]["TicketRow"];

type RecordName = components["schemas"]["FeatureRecordName"];
type PlanView = components["schemas"]["PlanView"];

/** The record tabs read from `brain/features/<slug>/<name>.md` (D3), in golden-path order. */
const RECORDS: Readonly<
  Partial<Record<string, { name: RecordName; label: string; missing: string }>>
> = {
  spec: { name: "spec", label: "Spec", missing: "Specs are written by /feature in the hub." },
  research: {
    name: "research",
    label: "Research",
    missing: "Allowed for size spike. Research is written by /research in the hub.",
  },
  plan: { name: "plan", label: "Plan", missing: "Plans are written by /create-plan in the hub." },
};

type FeaturePhase = components["schemas"]["FeaturePhase"];

/**
 * The tab where each phase's work is: a record while it is being written (UX designs sit beside
 * the spec), the tickets while they are built, the criteria once it is accepted or shipped. It is
 * the tab a feature opens on, and the one a golden path step opens.
 */
const PHASE_TAB: Record<FeaturePhase, string> = {
  spec: "spec",
  ux_design: "spec",
  research: "research",
  plan: "plan",
  tickets: "tickets",
  build: "tickets",
  acceptance: "acs",
  shipped: "acs",
};

/** The step's tab when the golden path opens it: Acceptance shows its eval records. */
const STEP_TAB: Record<FeaturePhase, string> = { ...PHASE_TAB, acceptance: "eval" };

/** The tab of `?doc=`: a record, `eval`, `tickets` or Criteria (`acs`); else the phase's tab. */
function tabOf(doc: string | null, phase: FeaturePhase | undefined): string {
  if (doc === "issues") return "tickets"; // the old Issues tab's deep links (AC-136.28)
  if (doc === "acs" || doc === "eval" || doc === "tickets" || (doc !== null && RECORDS[doc])) {
    return doc;
  }
  return phase ? PHASE_TAB[phase] : "acs";
}

/**
 * The feature's ticket ids, bare and once each: a spec may note prose beside an id
 * ("AGH-200 (provisional id: …)"), which is not part of the id.
 */
export function ticketIds(issues: readonly string[]): string[] {
  const ids = issues.map((issue) => /^[A-Z][A-Z0-9]*-\d+/.exec(issue.trim())?.[0] ?? issue.trim());
  return [...new Set(ids.filter(Boolean))];
}

/** An AC description as a sentence, so the callout's next sentence reads on. */
function ownerLine(text: string | undefined): string {
  if (!text) return "";
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

/** How a record tab shows its record: its human summary, or the file the agents read. */
type RecordView = "humans" | "agent";

/**
 * A record tab (Spec, Research, Plan): it opens on the record's human summary, the one-minute
 * version people read; Agent markdown shows the record itself, read through the brain route (D3).
 */
function RecordTab({
  detail,
  tab,
  view,
  onView,
}: {
  detail: Detail;
  tab: string;
  view: RecordView;
  onView: (view: RecordView, anchor?: string) => void;
}) {
  const meta = RECORDS[tab];
  if (!meta) return null;
  const file = `${meta.name}.md`;
  const record = detail.records.find((r) => r.name === meta.name);
  if (!record?.present) {
    return (
      <div className="ah-card">
        <EmptyState icon="file-text" title={`No ${file} yet.`}>
          {meta.missing}
        </EmptyState>
      </div>
    );
  }
  return (
    <div className="ah-card ah-pad ah-stack" style={{ gap: 12 }}>
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <Icon name="file-text" size="sm" />
        <span className="ah-mono ah-small">brain/{record.path}</span>
        <span className="ah-grow" />
        <QuestionsLink project={detail.project} path={record.path} />
        <SegmentedControl
          label="Show the record"
          value={view}
          onChange={(id) => {
            onView(id === "agent" ? "agent" : "humans");
          }}
          options={[
            {
              id: "humans",
              label: "For humans",
              icon: "book-open",
              title: "A short summary of the record, written for people",
            },
            {
              id: "agent",
              label: "Agent markdown",
              icon: "file-text",
              title: "The whole record, as the agents write and read it",
            },
          ]}
        />
        <Link className="ah-small" to={brainRoute(detail.project, record.path)}>
          Open in Brain
        </Link>
      </div>
      {meta.name === "plan" && detail.plan && <PlanVersionLine plan={detail.plan} />}
      <ApproveRecord
        project={detail.project}
        slug={detail.slug}
        record={meta.name}
        path={`brain/${record.path}`}
        tickets={ticketIds(detail.issues)}
      >
        {view === "humans" ? (
          <RecordSummary
            key={record.path}
            project={detail.project}
            record={meta.name}
            recordPath={record.path}
            onReadRecord={(anchor) => {
              onView("agent", anchor);
            }}
          />
        ) : (
          <NoteView
            key={record.path}
            project={detail.project}
            path={record.path}
            missing={`No ${file} yet.`}
          />
        )}
      </ApproveRecord>
    </div>
  );
}

/**
 * The plan's version (AC-1.4): v1 plus one per amendment, each amendment a link to the section it
 * is in, in the record as the agents wrote it; the reason when the version could not be read.
 */
function PlanVersionLine({ plan }: { plan: PlanView }) {
  const [params] = useSearchParams();
  if (plan.version == null) {
    return (
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        {plan.problem}
      </p>
    );
  }
  const agent = new URLSearchParams(params);
  agent.set("view", "agent");
  const amendments = plan.amendments;
  return (
    <p className="ah-small" style={{ margin: 0 }}>
      Plan v{String(plan.version)} · {amendments.length === 0 ? "no amendments" : "amendments "}
      {amendments.map((a, i) => (
        <Fragment key={a.id}>
          {i > 0 && ", "}
          <Link
            to={{ search: `?${agent.toString()}`, hash: `#${encodeURIComponent(a.anchor)}` }}
            replace
            title={`${a.id} (${a.date}, ${a.who}): ${a.title}`}
          >
            {a.id}
          </Link>
        </Fragment>
      ))}
    </p>
  );
}

/** One header chip: it opens the ticket's panel; where it goes is its description (UX F6). */
function TicketChip({
  id,
  row,
  search,
  openerRef,
}: {
  id: string;
  row: TicketRow | undefined;
  search: string;
  openerRef: MutableRefObject<HTMLElement | null>;
}) {
  const tipId = useId();
  return (
    <span className="ah-row" style={{ gap: 6 }}>
      <Tooltip id={tipId} label={`${id}${row?.title ? ` · ${row.title}` : ""} · show its steps`}>
        <Link
          className="ah-issue"
          to={{ search }}
          replace
          aria-describedby={tipId}
          onClick={(event) => {
            openerRef.current = event.currentTarget;
          }}
        >
          {id}
        </Link>
      </Tooltip>
      {row?.state && <StateBadge row={row} />}
    </span>
  );
}

/**
 * The feature's tickets as header chips: each id opens the Tickets tab with its ticket panel
 * (two-level-flows AC-1.10; the Linear link is in the panel), its title on hover and its status in
 * Linear once the tickets route answered (its cached answer).
 */
function TicketChips({
  ids,
  rows,
  openerRef,
}: {
  ids: readonly string[];
  rows: readonly TicketRow[];
  openerRef: MutableRefObject<HTMLElement | null>;
}) {
  const [params] = useSearchParams();
  if (ids.length === 0) return null;
  return (
    <span
      className="ah-row ah-wrap"
      style={{ gap: 12 }}
      role="group"
      aria-label="Tickets of this feature"
    >
      {ids.map((id) => (
        <TicketChip
          key={id}
          id={id}
          row={rows.find((r) => r.id === id || r.ref === id)}
          search={ticketSearch(params, id)}
          openerRef={openerRef}
        />
      ))}
    </span>
  );
}

function Loading() {
  return (
    <div style={{ padding: "16px 32px" }} className="ah-stack" aria-busy="true">
      <Skeleton width={320} height={28} />
      <Skeleton width={620} />
      <div className="ah-row" style={{ gap: 0, margin: "16px 0" }}>
        {PHASES.map((p) => (
          <div key={p.id} className="ah-grow ah-stack">
            <Skeleton width={16} height={16} radius={8} />
            <Skeleton width="60%" />
          </div>
        ))}
      </div>
      {Array.from({ length: 10 }, (_, i) => (
        <Skeleton key={i} height={28} />
      ))}
    </div>
  );
}

const TAB_LABEL: Readonly<Record<string, string>> = {
  spec: "spec",
  research: "research",
  plan: "plan",
  eval: "eval",
  acs: "acceptance criteria",
  tickets: "ticket plan",
};

/**
 * What the Discuss panel talks about on this screen: one conversation per feature, opened with the
 * panel on arrival. Claude reads every record of the feature before answering, and the brief adds
 * what the screen shows on top of the files: the phase, the criteria not passing, the tickets.
 */
function featureDiscussTarget(
  detail: Detail | undefined,
  tab: string,
  evalPath: string | undefined,
  owner: AgentSession | null,
): DiscussTarget | null {
  if (!detail) return null;
  const folder = `brain/features/${detail.slug}`;
  const record = detail.records.find((r) => r.name === RECORDS[tab]?.name && r.present);
  const path = record
    ? `brain/${record.path}`
    : tab === "acs"
      ? `${folder}/features.json`
      : tab === "eval" && evalPath
        ? `brain/${evalPath}`
        : null;
  const files = [
    ...detail.records.filter((r) => r.present).map((r) => `brain/${r.path}`),
    `${folder}/features.json`,
    ...detail.evals.map((e) => `brain/${e.path}`),
  ];
  const open = detail.ac_rows.filter((ac) => !ac.passes);
  const describe = (ac: AcRow) => `${ac.id}${ac.manual ? " (owner step)" : ""}: ${ac.description}`;
  return {
    key: `feature:${detail.project}:${detail.slug}`,
    project: detail.project,
    kind: `Feature ${TAB_LABEL[tab] ?? tab}`,
    title: detail.slug,
    path,
    openOnArrive: true,
    ownerSession: owner ? { id: owner.id, name: sessionName(owner) } : null,
    starters: record
      ? [
          {
            label: `Write the human summary of ${record.name}`,
            message: summaryRequest(detail.slug, record.name),
          },
        ]
      : undefined,
    brief: [
      `The whole feature record lives in \`${folder}/\`. Before answering, read all of it: ${[...new Set(files)].join(", ")}.`,
      detail.problem ? `The problem it solves: ${detail.problem}` : "",
      `Size: ${detail.size ?? "not set"}. Repos: ${detail.repos.join(", ") || "none"}. Current phase: ${detail.phase}.`,
      detail.acs
        ? `Acceptance criteria: ${String(detail.acs.passing)} of ${String(detail.acs.total)} passing.${open.length ? ` Not passing yet: ${open.map(describe).join("; ")}.` : ""}`
        : "",
      detail.issues.length ? `Its Linear tickets: ${ticketIds(detail.issues).join(", ")}.` : "",
      `I am looking at its ${TAB_LABEL[tab] ?? tab} tab.`,
      "When a change touches several records (spec, plan, criteria), keep them consistent with each other.",
    ]
      .filter(Boolean)
      .join(" "),
  };
}

/**
 * The session responsible for the feature (the one that wrote its spec, research and plan): one
 * click talks with it in the side panel.
 */
function FeatureSessionChip({ session }: { session: AgentSession }) {
  const { setOpen } = useDiscuss();
  const name = sessionName(session);
  return (
    <span className="ah-row" style={{ gap: 6 }}>
      <Icon name="square-terminal" size="sm" />
      <span className="ah-muted">Session</span>
      <Button
        size="sm"
        variant="ghost"
        title={`Talk with the session that wrote this feature's records: ${name}`}
        onClick={() => {
          setOpen(true);
        }}
      >
        {name}
      </Button>
    </span>
  );
}

/** Feature detail (spec 17, D23): golden path, owner steps, acceptance criteria. */
/** The feature's nickname as the title, the slug beside it; the pencil renames it. */
function FeatureHeading({ project, slug }: { project: string; slug: string }) {
  const nameOf = useFeatureNames();
  const [editing, setEditing] = useState(false);
  const name = nameOf({ project, slug });
  if (editing) {
    return (
      <FeatureNameField
        feature={{ project, slug }}
        name={name}
        className="fd-name-input"
        onDone={() => {
          setEditing(false);
        }}
      />
    );
  }
  return (
    <span className="ah-row" style={{ gap: 8, flexWrap: "nowrap", minWidth: 0 }}>
      <h1 className={name ? "ah-h1" : "ah-h1 ah-mono"}>{name ?? slug}</h1>
      {name && <span className="ah-mono ah-small ah-subtle">{slug}</span>}
      <RenameButton
        slug={slug}
        named={name !== null}
        onClick={() => {
          setEditing(true);
        }}
      />
    </span>
  );
}

/** How the acceptance eval reads in its group ("Eval 2"); null without one. */
function acceptanceLabel(
  detail: Detail,
  tickets: readonly string[],
  epics: readonly string[],
): string | null {
  const delivery = detail.acceptance_eval?.delivery;
  const group = evalHistory(detail.evals, tickets, epics).find((g) =>
    g.evals.some((e) => e.delivery === delivery),
  );
  const record = group?.evals.find((e) => e.delivery === delivery);
  return (record && group && runLabels(group.evals).get(record.path)) ?? null;
}

/** One thing only the owner can settle, as the page banner signposts it. */
interface OwnerWait {
  delivery: string;
  /** The eval's label in its group ("Eval 2"). */
  label: string;
  text: string;
  /** A sign-off the app cannot record (A10, A19): a signpost with no button. */
  byHand?: boolean;
}

/**
 * Every wait on the owner, the Acceptance wait first (the server's rule, only while a sign-off can
 * be recorded, A15), then each other eval waiting on owner steps (AGH-384) in plan order.
 */
function ownerWaits(
  detail: Detail,
  tickets: readonly string[],
  epics: readonly string[],
): OwnerWait[] {
  const acceptance = detail.acceptance_eval;
  const first: OwnerWait[] = [];
  if (acceptance?.owner_wait?.state === "sign_off") {
    const label = acceptanceLabel(detail, tickets, epics) ?? acceptance.delivery;
    const n = acceptance.owner_wait.acs.length;
    first.push({
      delivery: acceptance.delivery,
      label,
      text: `Acceptance: sign off ${String(n)} AC${n === 1 ? "" : "s"} (${label})`,
    });
  } else if (acceptance?.owner_wait?.state === "no_acs") {
    // A19: a sign-off the owner writes by hand waits too; its callout says what to write.
    const label = acceptanceLabel(detail, tickets, epics) ?? acceptance.delivery;
    first.push({
      delivery: acceptance.delivery,
      label,
      text: `Acceptance: sign off by hand · no ACs listed (${label})`,
      byHand: true,
    });
  }
  const others = ownerStepsWaiting(detail.evals, tickets, epics)
    .filter((w) => w.record.delivery !== acceptance?.delivery)
    .map((w) => ({
      delivery: w.record.delivery,
      label: w.label,
      text: `${w.scope === "feature" ? "Whole feature" : w.scope}: ${w.label} passed with owner steps`,
    }));
  return [...first, ...others];
}

type ChangeRequestView = components["schemas"]["ChangeRequestView"];

/** An open plan change request as the banner names it (two-level-flows AC-2.8). */
function changeText(request: ChangeRequestView): string {
  const affects = request.affected.length ? ` · affects ${request.affected.join(", ")}` : "";
  const version = (n: number | null) => (n == null ? "—" : `v${String(n)}`);
  const versions = `plan ${version(request.plan_from)} → ${version(request.plan_to)}`;
  return `Plan change request ${String(request.n)} from ${request.ticket ?? "?"}: ${versions}${affects}`;
}

/**
 * The page's one "Waiting for you" banner (A18): a signpost for every wait, one line each, the
 * open plan change requests first (AC-2.8), each line after the first a link to where it is
 * settled; the button opens the first: a request's ticket panel at its Preflight (AC-1.10, A8), or
 * an eval's prompt. The decisions are in the ticket panel and on the Eval tab's prompts
 * (ux-change-waiting-prompts.md).
 */
function WaitingBanner({
  changes,
  waits,
  onEval,
  onOpen,
  onTicket,
}: {
  changes: readonly ChangeRequestView[];
  waits: readonly OwnerWait[];
  /** The Eval tab is shown: its prompts are below, so no button for an eval. */
  onEval: boolean;
  onOpen: (delivery: string) => void;
  /** Opens the ticket panel of `ticket` at its Preflight; `opener` takes focus back on close. */
  onTicket: (ticket: string, opener: HTMLElement) => void;
}) {
  const [params] = useSearchParams();
  const [change, ...moreChanges] = changes;
  const [first, ...rest] = waits;
  if (!change && !first) return null;
  const ticketLink = (request: ChangeRequestView) => {
    const next = new URLSearchParams(ticketSearch(params, request.ticket ?? ""));
    next.set("step", "preflight");
    return (
      <Link
        to={{ search: `?${next.toString()}` }}
        replace
        onClick={(event) => {
          event.preventDefault();
          onTicket(request.ticket ?? "", event.currentTarget);
        }}
      >
        {changeText(request)}
      </Link>
    );
  };
  let action: ReactNode = null;
  if (change) {
    action = (
      <Button
        size="sm"
        variant="primary"
        icon="arrow-right"
        aria-label={`Review change request ${String(change.n)} from ${change.ticket ?? ""}`}
        onClick={(event) => {
          onTicket(change.ticket ?? "", event.currentTarget);
        }}
      >
        Review change request
      </Button>
    );
  } else if (first && !onEval && !first.byHand) {
    action = (
      <Button
        size="sm"
        variant="primary"
        icon="arrow-right"
        aria-label={`Review owner steps of ${first.label}`}
        onClick={() => {
          onOpen(first.delivery);
        }}
      >
        Review owner steps
      </Button>
    );
  }
  return (
    <Banner tone="warning" boxed icon="hand" action={action}>
      <b>Waiting for you</b>
      {onEval && waits.length > 0 && (
        <span className="ah-muted">
          {change ? " · Settle the eval waits below." : " · Settle each one below."}
        </span>
      )}
      <ul className="ah-small" style={{ margin: "2px 0 0", paddingLeft: 18 }}>
        {change && (
          <li>
            {changeText(change)} · <WaitAge openedAt={change.opened_at} />
          </li>
        )}
        {moreChanges.map((request) => (
          <li key={request.n}>
            {ticketLink(request)} · <WaitAge openedAt={request.opened_at} />
          </li>
        ))}
        {first &&
          (change || first.byHand ? (
            <li>
              <Link to={{ search: evalSearch(params, first.delivery) }} replace state={FOCUS_EVAL}>
                {first.text}
              </Link>
            </li>
          ) : (
            <li>{first.text}</li>
          ))}
        {rest.map((wait) => (
          <li key={wait.delivery}>
            <Link to={{ search: evalSearch(params, wait.delivery) }} replace state={FOCUS_EVAL}>
              {wait.text}
            </Link>
          </li>
        ))}
      </ul>
    </Banner>
  );
}

/**
 * Says once, politely, each plan change request that arrives while the page is open (U5): those
 * open at the first read are the banner's, not news.
 */
function NewRequestAnnouncer({ requests }: { requests: readonly ChangeRequestView[] }) {
  const seen = useRef<Set<number> | null>(null);
  const [said, setSaid] = useState("");
  useEffect(() => {
    if (seen.current === null) {
      seen.current = new Set(requests.map((request) => request.n));
      return;
    }
    const known = seen.current;
    const fresh = requests.filter((request) => !known.has(request.n));
    for (const request of fresh) known.add(request.n);
    if (fresh.length > 0) {
      setSaid(
        fresh
          .map((r) => `${r.ticket ?? ""} waits for you: plan change request ${String(r.n)}.`)
          .join(" "),
      );
    }
  }, [requests]);
  return (
    <div className="ah-sr" role="status" aria-live="polite">
      {said}
    </div>
  );
}

export function FeatureDetailScreen() {
  const { project = "", slug = "" } = useParams();
  const feature = useFeature(project, slug);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();
  const tab = tabOf(params.get("doc"), feature.data?.phase);
  // The element that opened the ticket panel (a header chip, a card title, a row): focus returns there.
  const openerRef = useRef<HTMLElement | null>(null);
  const tickets = useFeatureTickets(
    project,
    slug,
    (tab === "tickets" || tab === "eval") && feature.isSuccess,
  );
  const selectedEval = pickEval(feature.data?.evals ?? [], params.get("eval"));
  const owner = useFeatureSession(project, slug);
  useDiscussTarget(featureDiscussTarget(feature.data, tab, selectedEval?.path, owner));

  if (feature.isError) {
    if (feature.error.status === 404) {
      return <NotFoundBody line={`No feature ${slug} in ${project}.`} query={slug} />;
    }
    return (
      <div style={{ padding: "16px 32px" }} className="ah-stack">
        <h1 className="ah-h1 ah-mono">{slug}</h1>
        <div style={{ maxWidth: 720 }}>
          <ProblemError
            title={feature.error.title}
            detail={feature.error.detail}
            status={feature.error.status}
            onRetry={() => void feature.refetch()}
          />
        </div>
      </div>
    );
  }
  if (feature.isPending) return <Loading />;

  const detail = feature.data;
  const owners = detail.ac_rows.filter((ac) => passOf(ac) === "owner");
  const issueIds = ticketIds(detail.issues);
  const epics = tickets.data?.planning.epics ?? [];
  const waits = ownerWaits(detail, issueIds, epics);
  const changes = detail.change_requests.filter(
    (request) => request.status === "open" && request.ticket,
  );
  const wait = detail.acceptance_eval?.owner_wait;
  const accepted = detail.acceptance_eval && acceptanceLabel(detail, issueIds, epics);
  const setTab = (id: string) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (id === PHASE_TAB[detail.phase]) next.delete("doc");
        else next.set("doc", id);
        // The ticket panel belongs to the Tickets tab: another tab closes it.
        next.delete("ticket");
        next.delete("step");
        return next;
      },
      { replace: true },
    );
  };
  const openTicket = (ticket: string, opener: HTMLElement) => {
    openerRef.current = opener;
    setParams(
      (current) => {
        const next = new URLSearchParams(ticketSearch(current, ticket));
        next.set("step", "preflight");
        return next;
      },
      { replace: true },
    );
  };
  const openEval = (delivery: string) => {
    setParams((current) => evalSearch(current, delivery), { replace: true, state: FOCUS_EVAL });
  };
  const tabs = [
    ...Object.entries(RECORDS).map(([id, meta]) => ({ id, label: meta?.label ?? id })),
    { id: "eval", label: "Eval" },
    {
      id: "acs",
      label: "Acceptance criteria",
      icon: "list-checks" as const,
      count: detail.acs?.total,
    },
    {
      id: "tickets",
      label: "Tickets",
      count: tickets.data?.tickets.length ?? issueIds.length,
    },
  ];
  let body: ReactNode;
  if (tab === "tickets") {
    body = (
      <TicketsTab
        project={project}
        slug={detail.slug}
        data={tickets.data}
        error={tickets.isError ? tickets.error : null}
        onRefresh={() => void tickets.refetch()}
        refreshing={tickets.isFetching}
        acPasses={Object.fromEntries(detail.ac_rows.map((ac) => [ac.id, ac.passes]))}
        acRows={detail.ac_rows}
        evals={detail.evals}
        openerRef={openerRef}
      />
    );
  } else if (tab === "eval") {
    body = (
      <EvalTab
        project={detail.project}
        slug={detail.slug}
        tickets={issueIds}
        epics={tickets.data?.planning.epics ?? []}
        evals={detail.evals}
        ticketRows={tickets.data?.tickets}
        acRows={detail.ac_rows}
        acceptance={detail.acceptance_eval}
        selected={selectedEval}
        onSelect={(delivery) => {
          setParams(
            (current) => {
              const next = new URLSearchParams(current);
              next.set("eval", delivery);
              return next;
            },
            { replace: true },
          );
        }}
      />
    );
  } else if (RECORDS[tab]) {
    body = (
      <RecordTab
        detail={detail}
        tab={tab}
        view={params.get("view") === "agent" ? "agent" : "humans"}
        onView={(view, anchor) => {
          const next = new URLSearchParams(params);
          if (view === "agent") next.set("view", "agent");
          else next.delete("view");
          void navigate(
            { search: `?${next.toString()}`, hash: anchor ? `#${encodeURIComponent(anchor)}` : "" },
            { replace: true },
          );
        }}
      />
    );
  } else body = <CriteriaTab detail={detail} />;

  return (
    <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <div className="ah-stack" style={{ gap: 6 }}>
        <div className="ah-row ah-wrap" style={{ gap: 12 }}>
          <FeatureHeading project={detail.project} slug={detail.slug} />
          {detail.verdict && (
            <StatusBadge
              status={VERDICT_STATUS[detail.verdict]}
              label={detail.verdict}
              title="Verdict of the latest whole-feature eval"
            />
          )}
          {detail.size && <span className="ah-fm-chip">{detail.size}</span>}
          <span className="ah-small ah-muted">
            {detail.project}
            {detail.repos.length && detail.repos.join(",") !== detail.project
              ? ` · ${detail.repos.join(", ")}`
              : ""}
          </span>
          <span className="ah-grow" />
          <DiscussButton />
          {state === "offline" && <AsOfStamp stale time={fmtClock(asOf, tz)} />}
        </div>
        <div className="ah-row ah-wrap ah-small" style={{ gap: 14 }}>
          {owner && <FeatureSessionChip session={owner} />}
          <TicketChips ids={issueIds} rows={tickets.data?.tickets ?? []} openerRef={openerRef} />
          {detail.acs && (
            <>
              {issueIds.length > 0 && (
                <span style={{ width: 1, height: 16, background: "var(--border)" }} />
              )}
              <AcBar acs={detail.acs} width={180} ownerIds={owners.map((ac) => ac.id)} />
            </>
          )}
        </div>
      </div>
      <section
        className="ah-stack"
        style={{ gap: 10, marginTop: 8 }}
        aria-label="Where the feature is"
      >
        <div className="ah-row" style={{ gap: 8 }}>
          <b className="ah-small">Golden path</b>
          <DerivedLabel how="Each step is derived from the record files, the tickets' status in Linear when it was read, and the review and eval records; Shipped needs GitHub, not connected in this version. Hover a step for its details." />
        </div>
        <GoldenPathStepper
          steps={detail.golden_path.steps.map((step) =>
            // A future-dated wait reads as its prompt does, in the page's time zone (AGH-330 Q4).
            step.name === "acceptance" && wait?.state === "future"
              ? { ...step, meta: signableLine(wait, tz) }
              : step,
          )}
          onSelect={(step) => {
            // Acceptance opens its own eval, where its prompt is (A15).
            if (step === "acceptance" && detail.acceptance_eval) {
              openEval(detail.acceptance_eval.delivery);
            } else setTab(STEP_TAB[step]);
          }}
          selectLabel={(step) =>
            step === "acceptance" && accepted
              ? `Open ${accepted}, the acceptance eval`
              : `Open the ${TAB_LABEL[STEP_TAB[step]] ?? step} of ${step}`
          }
        />
      </section>
      {waits.length > 0 || changes.length > 0 ? (
        <WaitingBanner
          changes={changes}
          waits={waits}
          onEval={tab === "eval"}
          onOpen={openEval}
          onTicket={openTicket}
        />
      ) : (
        !detail.acceptance_eval &&
        owners.length > 0 && (
          <Banner tone="warning" boxed icon="hand">
            <b>
              Waiting for you: {owners.length} owner step{owners.length === 1 ? "" : "s"} left
            </b>
            <span className="ah-muted">
              {" "}
              · {owners.map((ac) => ac.id).join(", ")}. {ownerLine(owners[0]?.description)}
            </span>
          </Banner>
        )
      )}
      <NewRequestAnnouncer requests={changes} />
      <Tabs tabs={tabs} value={tab} onChange={setTab} label="Feature record" />
      <div style={{ paddingTop: 4 }}>{body}</div>
    </div>
  );
}
