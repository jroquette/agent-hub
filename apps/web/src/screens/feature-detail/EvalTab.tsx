import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useId, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import {
  AppLink,
  Banner,
  Button,
  EmptyState,
  Icon,
  IconButton,
  IdChip,
  PathText,
  ProblemError,
  SegmentedControl,
  StatusBadge,
  Time,
  Tooltip,
  type Status,
} from "../../components";
import { ApiProblem, apiCommand, apiKey, apiPost, useApi } from "../../lib/api";
import { brainRoute } from "../../lib/brainLinks";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtDateTime } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useDiscuss, type DiscussReference } from "../../shell/discuss";
import { NoteView } from "../brain/NoteView";
import { VERDICT_STATUS } from "../features/parts";
import { agentSessionHref } from "../sessions-list/control";
import { splitTitle } from "./PlanningView";
import { passOf } from "./CriteriaTab";
import { AcList } from "./TicketsTab";
import { useCreateAgentSession, useHubSessionStart } from "../sessions-list/queries";

type EvalRecord = components["schemas"]["EvalRecord"];
type TicketRow = components["schemas"]["TicketRow"];
type AcRow = components["schemas"]["AcRow"];
type OwnerDecision = NonNullable<components["schemas"]["OwnerSignOffBody"]["decision"]>;
type AgentSessionStatus = components["schemas"]["AgentSessionStatus"];

function Scope({ acs }: { acs: EvalRecord["acs"] }) {
  if (acs === "all") return <span>All ACs</span>;
  if (acs.length === 0) return <span className="ah-subtle">—</span>;
  return (
    <span title={acs.join(", ")}>
      {acs.length} AC{acs.length === 1 ? "" : "s"}
    </span>
  );
}

/** How an eval is named: a legacy single `eval.md` reads as that file, not as "legacy". */
function deliveryLabel(record: EvalRecord): string {
  return record.legacy ? fileName(record.path) : record.delivery;
}

/** Who ran an eval, from its `provenance`, in words; null when the note does not say. */
export function ranBy(provenance: string | null | undefined): string | null {
  if (!provenance) return null;
  const known: Record<string, string> = {
    agent: "Agent",
    "agent-evaluator": "Evaluator agent",
    owner: "You (owner sign-off)",
  };
  return known[provenance] ?? provenance;
}

/**
 * What an eval evaluated: the whole feature (all ACs, no ticket, or only the feature's epics,
 * since evaluating the epic is evaluating the feature), else its tickets.
 */
export function evalScope(record: EvalRecord, epics: readonly string[]): string {
  const own = record.tickets.filter((t) => !epics.includes(t));
  if (record.acs === "all" || own.length === 0) return FEATURE_SCOPE;
  return own.join(", ");
}

/** The evals grouped by scope, the whole feature first, then the tickets in plan order; newest first. */
export function evalHistory(
  evals: readonly EvalRecord[],
  tickets: readonly string[],
  epics: readonly string[],
): { scope: string; evals: EvalRecord[] }[] {
  const groups = new Map<string, EvalRecord[]>();
  for (const e of evals) {
    const scope = evalScope(e, epics);
    groups.set(scope, [...(groups.get(scope) ?? []), e]);
  }
  const rank = (scope: string) => {
    if (scope === FEATURE_SCOPE) return -1;
    const at = tickets.indexOf(scope.split(", ")[0] ?? scope);
    return at === -1 ? tickets.length : at;
  };
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([scope, list]) => ({ scope, evals: [...list].reverse() }));
}

function fileName(path: string): string {
  return path.split("/").pop() ?? path;
}

/**
 * The eval shown below the list: the one `?eval=` names, else the newest by `evaluated_at`, else
 * the last by name (the server sorts by name, so the first row is not the latest).
 */
export function pickEval(
  evals: readonly EvalRecord[],
  asked: string | null,
): EvalRecord | undefined {
  const named = asked === null ? undefined : evals.find((e) => e.delivery === asked);
  if (named) return named;
  const dated = evals.filter((e) => e.evaluated_at);
  if (dated.length > 0) {
    return dated.reduce((a, b) => ((b.evaluated_at ?? "") > (a.evaluated_at ?? "") ? b : a));
  }
  return evals.at(-1);
}

/** Whether two evals name some AC or ticket in common (`all` names every AC). */
function overlaps(a: EvalRecord, b: EvalRecord): boolean {
  if (a.acs === "all" || b.acs === "all") return true;
  const acs = b.acs;
  return a.acs.some((ac) => acs.includes(ac)) || a.tickets.some((t) => b.tickets.includes(t));
}

/** An eval the owner wrote from the app: a sign-off (SHIP) or "more work needed" (NO-SHIP). */
const isOwnerDecision = (e: EvalRecord) =>
  e.provenance === "owner" && (e.verdict === "SHIP" || e.verdict === "NO-SHIP") && !e.problem;

/**
 * The SHIP-WITH-OWNER-STEPS evals the owner settled afterwards, each with the owner's eval that
 * settled it: a sign-off (SHIP, the steps are done) or a "more work needed" (NO-SHIP). The files
 * stay as written (evals are never edited); the first owner decision after an eval that names
 * some of its ACs or tickets settles it, so it reads as handled, not as waiting forever.
 */
export function settledOwnerSteps(evals: readonly EvalRecord[]): Map<string, EvalRecord> {
  const time = (e: EvalRecord) => (e.evaluated_at ? Date.parse(e.evaluated_at) : Number.NaN);
  const decisions = evals.filter((e) => isOwnerDecision(e) && !Number.isNaN(time(e)));
  const settled = new Map<string, EvalRecord>();
  for (const e of evals) {
    if (e.verdict !== "SHIP-WITH-OWNER-STEPS" || e.problem) continue;
    const at = time(e);
    // An undated eval is older than any owner decision: the decision is always dated.
    const by = decisions
      .filter((s) => (Number.isNaN(at) || time(s) > at) && overlaps(e, s))
      .sort((a, b) => time(a) - time(b))[0];
    if (by) settled.set(e.path, by);
  }
  return settled;
}

/** The verdict of an eval as it reads now: settled owner steps, or a run a newer one replaced. */
function VerdictBadge({
  record,
  settledBy,
  supersededBy,
}: {
  record: EvalRecord;
  settledBy?: EvalRecord | undefined;
  /** The newer run of the same scope that decides its ACs now. */
  supersededBy?: string | undefined;
}) {
  if (!record.verdict) return null;
  if (settledBy) {
    const done = settledBy.verdict === "SHIP";
    return (
      <Tooltip
        label={
          done
            ? `The eval said ${record.verdict}; you signed the owner steps off in ${settledBy.delivery}.`
            : `The eval said ${record.verdict}; you found more work is needed (${settledBy.delivery}). Evaluate again once it is done.`
        }
      >
        <span className="ah-row" style={{ gap: 6 }}>
          <StatusBadge status={done ? "done" : "failed"} label={done ? "SHIP" : "NO-SHIP"} />
          <span className="ah-small ah-muted">
            {done ? "owner steps signed off" : "you found more work"}
          </span>
        </span>
      </Tooltip>
    );
  }
  if (supersededBy && record.verdict === "SHIP-WITH-OWNER-STEPS") {
    return (
      <Tooltip label={`${supersededBy} evaluated this scope again and decides its ACs now.`}>
        <span className="ah-row" style={{ gap: 6 }}>
          <StatusBadge status="idle" label={record.verdict} />
          <span className="ah-small ah-muted">replaced by {supersededBy}</span>
        </span>
      </Tooltip>
    );
  }
  return <StatusBadge status={VERDICT_STATUS[record.verdict]} label={record.verdict} />;
}

/** One eval as a Discuss reference: its verdict and the scope it evaluated. */
export function evalReference(record: EvalRecord): DiscussReference {
  const acs = record.acs === "all" ? "all" : record.acs.join(", ");
  return {
    id: `eval:${record.delivery}`,
    label: record.delivery,
    source: `brain/${record.path}`,
    quote: [
      `Eval ${record.delivery}: ${record.verdict ?? "no verdict"}.`,
      record.tickets.length ? `Tickets: ${record.tickets.join(", ")}.` : "",
      acs ? `ACs: ${acs}.` : "",
      record.commit ? `Commit: ${record.commit}.` : "",
      record.evaluated_at ? `Evaluated at ${record.evaluated_at}.` : "",
    ]
      .filter(Boolean)
      .join("\n"),
  };
}

/* ---------- Run the evaluator ---------- */

const FEATURE_SCOPE = "feature";

interface StoredRun {
  id: string;
  scope: string;
  started_at: string;
  /** The eval paths that existed when the run started: any other one is the run's. */
  known: string[];
}

const runKey = (project: string, slug: string) => `agent-hub:eval-run:${project}:${slug}`;

function readRun(key: string): StoredRun | null {
  try {
    const text = window.localStorage.getItem(key);
    return text ? (JSON.parse(text) as StoredRun) : null;
  } catch {
    return null;
  }
}

function writeRun(key: string, run: StoredRun | null) {
  try {
    if (run === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(run));
  } catch {
    // Without storage the run is only forgotten on reload; its chat stays in Sessions.
  }
}

const scopeLabel = (scope: string) => (scope === FEATURE_SCOPE ? "whole feature" : scope);

/** The whole feature's name, with its epic when it has one: evaluating the epic is evaluating it. */
const featureName = (epics: readonly string[]) =>
  epics.length > 0 ? `Whole feature · ${epics.join(", ")} epic` : "Whole feature";

/** The first message of an evaluator run: the hub-workflow evaluator, one scope, nothing else. */
export function evalPrompt(project: string, slug: string, scope: string): string {
  const what = scope === FEATURE_SCOPE ? "the whole feature" : `ticket ${scope}`;
  return [
    `I am the owner of the agent-hub project "${project}", writing from the agent-hub web app.`,
    `Use the hub-workflow evaluator subagent to evaluate feature \`${slug}\` (its record is in \`brain/features/${slug}/\`). Scope: ${what}.`,
    `It re-runs every verification in scope, the repo gates and the hub doctor, against the spec and the plan, and writes the next free \`brain/features/${slug}/evals/<delivery>.md\` and \`.json\`; never edit an existing eval.`,
    "Then run `./hub validate-output eval <the new .json>` from the hub; when it is missing or fails, re-dispatch the evaluator once with the same scope and every line the command printed.",
    "Do not merge, push, open pull requests or change tickets.",
    "When it hands back, give me the verdict, any AC that does not pass and the owner steps left, in a few lines.",
  ].join("\n");
}

const RUN_LOOK: Record<AgentSessionStatus, { status: Status; label: string; note?: string }> = {
  running: { status: "running", label: "Evaluating" },
  waiting_permission: {
    status: "waiting",
    label: "Waiting for you",
    note: "Claude asks before running a command. Answer in the chat.",
  },
  idle: {
    status: "idle",
    label: "Finished without a new eval",
    note: "A new eval can take 15 s to show. If none comes, open the chat to see why.",
  },
  ended: { status: "ended", label: "Ended" },
  failed: { status: "failed", label: "Failed" },
};

const IN_FLIGHT: readonly AgentSessionStatus[] = ["running", "waiting_permission"];

function EvalRunStrip({
  project,
  slug,
  tickets,
  evals,
  onShow,
  primary,
  epics,
  caption,
}: {
  project: string;
  slug: string;
  tickets: readonly string[];
  evals: readonly EvalRecord[];
  /** What the row says on its left, before the action: the eval count. */
  caption?: ReactNode;
  onShow: (delivery: string) => void;
  /** The tab's main action (no eval yet); otherwise re-running is secondary to reading. */
  primary: boolean;
  /** The feature's epics: not a scope of their own, they are the whole feature. */
  epics: readonly string[];
}) {
  const key = runKey(project, slug);
  const { tz } = usePreferences();
  const start = useHubSessionStart(project);
  const create = useCreateAgentSession();
  const [stored, setRun] = useState<StoredRun | null>(() => readRun(key));
  const now = useNow(30_000);
  const [scope, setScope] = useState(FEATURE_SCOPE);
  const session = useApi(
    "/api/v1/agent-sessions/{agent_session_id}",
    { path: { agent_session_id: stored?.id ?? "" } },
    {
      enabled: stored !== null,
      retry: false,
      refetchInterval: (query) => {
        const status = query.state.data?.status;
        return status === undefined || IN_FLIGHT.includes(status) ? 3_000 : false;
      },
    },
  );
  const gone = session.error instanceof ApiProblem && session.error.status === 404;
  // A run whose session was deleted is forgotten: its stored id is dropped, not shown.
  const run = gone ? null : stored;
  useEffect(() => {
    if (gone) writeRun(key, null);
  }, [gone, key]);
  const forget = () => {
    writeRun(key, null);
    setRun(null);
  };
  const status = session.data?.status;
  const inFlight = run !== null && (status === undefined || IN_FLIGHT.includes(status));
  const fresh = run ? evals.filter((e) => !run.known.includes(e.path)) : [];
  const look =
    status === "idle" && fresh.length > 0
      ? { status: "done" as const, label: "Finished", note: undefined }
      : status
        ? RUN_LOOK[status]
        : null;
  const waiting = status === "waiting_permission";
  const shownScope = inFlight ? run.scope : scope;
  const blocked = inFlight
    ? "An evaluation is already running. Open its chat to follow it."
    : start.reason;

  const evaluate = async () => {
    if (!start.hubWorkdirId) return;
    const created = await create.mutateAsync({
      project,
      workdir_id: start.hubWorkdirId,
      mode: "acceptEdits",
      fork: false,
      prompt: evalPrompt(project, slug, scope),
    });
    const next: StoredRun = {
      id: created.id,
      scope,
      started_at: new Date().toISOString(),
      known: evals.map((e) => e.path),
    };
    writeRun(key, next);
    setRun(next);
  };

  const action = `Evaluate ${scopeLabel(shownScope)}`;
  const scopes = tickets.filter((t) => !epics.includes(t));
  const variant = primary ? "primary" : "default";
  return (
    <section className="ah-stack" style={{ gap: 8 }} aria-label="Evaluate">
      <div className="ah-row ah-wrap" style={{ gap: 10 }}>
        {caption}
        <span className="ah-grow" />
        {scopes.length > 1 || (scopes.length > 0 && epics.length > 0) ? (
          <SegmentedControl
            label="Evaluation scope"
            value={shownScope}
            disabled={inFlight}
            onChange={setScope}
            options={[
              { id: FEATURE_SCOPE, label: featureName(epics) },
              ...scopes.map((t) => ({ id: t, label: t })),
            ]}
          />
        ) : (
          epics.length > 0 && <span className="ah-small ah-muted">{featureName(epics)}</span>
        )}
        {blocked ? (
          <Tooltip label={blocked}>
            <Button
              variant={variant}
              icon="flask-conical"
              disabled
              aria-label={`${action}. ${blocked}`}
            >
              {action}
            </Button>
          </Tooltip>
        ) : (
          <Tooltip label="Re-runs every check and gate in scope and writes a new eval. Existing evals are kept.">
            <Button
              variant={variant}
              icon="flask-conical"
              disabled={create.isPending}
              onClick={() => void evaluate()}
            >
              {create.isPending ? "Starting…" : action}
            </Button>
          </Tooltip>
        )}
      </div>
      {start.unavailable && (
        <Banner tone="warning" boxed>
          <b>{start.unavailable.title}.</b> {start.unavailable.detail}
        </Banner>
      )}
      {create.error && (
        <ProblemError
          compact
          title="Could not start the evaluator"
          detail={create.error.detail ?? create.error.title}
          status={create.error.status || undefined}
          onRetry={() => void evaluate()}
        />
      )}
      {run && (
        <div className="ah-card ah-pad ah-row ah-wrap ah-small" style={{ gap: 10 }}>
          <span className="ah-row ah-wrap" role="status" style={{ gap: 10 }}>
            <StatusBadge status={look?.status ?? "queued"} label={look?.label ?? "Starting…"} />
            {look?.note && <span className="ah-muted">{look.note}</span>}
          </span>
          <span title={fmtDateTime(run.started_at, tz)}>
            {scopeLabel(run.scope)} · started{" "}
            {fmtAgo(Math.max(0, now - Date.parse(run.started_at)) / 1000)}
          </span>
          {fresh.map((e) => (
            <Button
              key={e.path}
              size="sm"
              variant="ghost"
              icon="file-text"
              onClick={() => {
                onShow(e.delivery);
              }}
            >
              Show {e.delivery}
            </Button>
          ))}
          <span className="ah-grow" />
          <AppLink
            className={waiting ? "ah-btn ah-btn-sm ah-btn-primary" : "ah-btn ah-btn-sm"}
            href={agentSessionHref(run.id)}
          >
            <Icon name={waiting ? "hand" : "message-square"} size="sm" />
            {waiting ? "Answer in chat" : "Open chat"}
          </AppLink>
          {!inFlight && <IconButton size="sm" icon="x" label="Clear this run" onClick={forget} />}
        </div>
      )}
    </section>
  );
}

/* ---------- The owner's sign-off ---------- */

/**
 * The owner confirms the owner steps of a SHIP-WITH-OWNER-STEPS eval are done: the server writes
 * an `owner-signoff` SHIP eval over the ACs that waited, and the Evaluate step turns done. It is
 * the page's one "waiting on you" place, above the tabs.
 */
export function OwnerSignOff({
  project,
  slug,
  reason,
  onShow,
}: {
  project: string;
  slug: string;
  reason: string;
  onShow: (delivery: string) => void;
}) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const path = { path: { project, slug } };
  const signOff = useMutation<EvalRecord, ApiProblem>({
    mutationFn: () => apiCommand("/api/v1/features/{project}/{slug}/owner-signoff", path),
    onSuccess: (written) => {
      setConfirming(false);
      onShow(written.delivery);
      for (const key of [
        apiKey("/api/v1/features"),
        apiKey("/api/v1/features/{project}/{slug}", path),
        apiKey("/api/v1/features/{project}/{slug}/tickets", path),
      ]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
  const action = confirming ? (
    <span className="ah-row" style={{ gap: 8 }}>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          setConfirming(false);
        }}
      >
        Cancel
      </Button>
      <Button
        size="sm"
        variant="primary"
        icon="check"
        disabled={signOff.isPending}
        onClick={() => {
          signOff.mutate();
        }}
      >
        {signOff.isPending ? "Signing off…" : "Yes, I did them"}
      </Button>
    </span>
  ) : (
    <Button
      size="sm"
      variant="primary"
      icon="check"
      onClick={() => {
        setConfirming(true);
      }}
    >
      Mark owner steps done
    </Button>
  );
  return (
    <section aria-label="Owner steps">
      <Banner tone="warning" boxed icon="hand" action={action}>
        <span className="ah-stack" style={{ gap: 2 }}>
          <span>
            <b>Waiting on you</b>
            <span className="ah-muted">
              {" "}
              · {reason.replace(/\s*\(SHIP-WITH-OWNER-STEPS\)/, "")}
            </span>
          </span>
          {confirming && (
            <span className="ah-small ah-muted">
              Confirm you did every owner step the eval lists. This writes evals/owner-signoff.md
              with verdict SHIP, signed by you; existing evals are kept.
            </span>
          )}
          {signOff.error && (
            <ProblemError
              compact
              title="Could not sign off the owner steps"
              detail={signOff.error.detail ?? signOff.error.title}
              status={signOff.error.status || undefined}
              onRetry={() => {
                signOff.mutate();
              }}
            />
          )}
        </span>
      </Banner>
    </section>
  );
}

/* ---------- The owner's decision on one eval ---------- */

const DECISION: Record<OwnerDecision, { action: string; title: string; detail: string }> = {
  done: {
    action: "Mark owner steps done",
    title: "Mark the owner steps done",
    detail: "Writes an owner sign-off eval (SHIP) over its waiting ACs. This eval is kept.",
  },
  more_work: {
    action: "Needs more work",
    title: "Record that more work is needed",
    detail:
      "Writes an owner eval (NO-SHIP) over its waiting ACs: they stay open until the next eval.",
  },
};

/**
 * The latest eval of a scope waits on owner steps no one settled: a "Waiting on you" callout
 * under its row (principle 2), where the owner says the steps are done or that more work is
 * needed, with an optional note. The same banner as the page's owner sign-off.
 */
function OwnerStepsCallout({
  project,
  slug,
  record,
  label,
  ownerAcs,
  onShow,
}: {
  project: string;
  slug: string;
  record: EvalRecord;
  /** How the eval reads in the table ("DEMO-1562 · Eval 1"). */
  label: string;
  /** The eval's ACs that are manual owner steps, to name them. */
  ownerAcs: readonly string[];
  onShow: (delivery: string) => void;
}) {
  const client = useQueryClient();
  const formId = useId();
  const [decision, setDecision] = useState<OwnerDecision | null>(null);
  const [note, setNote] = useState("");
  const path = { path: { project, slug } };
  const settle = useMutation<EvalRecord, ApiProblem, OwnerDecision>({
    mutationFn: (chosen) =>
      apiPost(
        "/api/v1/features/{project}/{slug}/owner-signoff",
        { delivery: record.delivery, decision: chosen, note: note.trim() || null },
        path,
      ),
    onSuccess: (written) => {
      onShow(written.delivery);
      setDecision(null);
      for (const key of [
        apiKey("/api/v1/features"),
        apiKey("/api/v1/features/{project}/{slug}", path),
        apiKey("/api/v1/features/{project}/{slug}/tickets", path),
      ]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
  const choose = (chosen: OwnerDecision) => (
    <Button
      size="sm"
      variant={chosen === "done" ? "primary" : "default"}
      icon={chosen === "done" ? "check" : "rotate-ccw"}
      onClick={() => {
        setDecision(chosen);
      }}
    >
      {DECISION[chosen].action}
    </Button>
  );
  const action = decision ? (
    <span className="ah-row" style={{ gap: 8, alignSelf: "flex-end" }}>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          setDecision(null);
        }}
      >
        Cancel
      </Button>
      <Button
        size="sm"
        variant="primary"
        type="submit"
        form={formId}
        icon={decision === "done" ? "check" : "rotate-ccw"}
        disabled={settle.isPending}
      >
        {settle.isPending ? "Saving…" : DECISION[decision].action}
      </Button>
    </span>
  ) : (
    <span className="ah-row" style={{ gap: 8 }}>
      {choose("more_work")}
      {choose("done")}
    </span>
  );
  return (
    <Banner tone="warning" boxed icon="hand" action={action}>
      {decision ? (
        <form
          id={formId}
          className="ah-eval-decision ah-stack"
          aria-label={`${DECISION[decision].title}: ${label}`}
          onSubmit={(event) => {
            event.preventDefault();
            settle.mutate(decision);
          }}
        >
          <span className="ah-stack" style={{ gap: 2 }}>
            <b>
              {DECISION[decision].title} · {label}
            </b>
            <span className="ah-small ah-muted">{DECISION[decision].detail}</span>
          </span>
          <label className="ah-stack ah-small" style={{ gap: 4 }}>
            <span>Note (optional)</span>
            <textarea
              className="ah-input ah-eval-note"
              rows={2}
              maxLength={2000}
              value={note}
              placeholder={decision === "done" ? "What you did" : "What is still left to do"}
              onChange={(event) => {
                setNote(event.target.value);
              }}
            />
          </label>
          {settle.error && (
            <ProblemError
              compact
              title="Could not record your decision"
              detail={settle.error.detail ?? settle.error.title}
              status={settle.error.status || undefined}
            />
          )}
        </form>
      ) : (
        <span className="ah-stack" style={{ gap: 2 }}>
          <span>
            <b>Waiting on you</b>
            <span className="ah-muted"> · {label} passed with owner steps. Did you do them?</span>
          </span>
          {ownerAcs.length > 0 && (
            <span className="ah-small ah-muted">
              Owner step{ownerAcs.length === 1 ? "" : "s"}:{" "}
              <span className="ah-mono">{ownerAcs.join(", ")}</span>
            </span>
          )}
        </span>
      )}
    </Banner>
  );
}

/* ---------- The selected eval ---------- */

/** A frontmatter time as the app writes times; a bare date (no time) stays as it is. */
function evaluatedText(value: string, tz: ReturnType<typeof usePreferences>["tz"]): string {
  return value.includes("T") && !Number.isNaN(Date.parse(value)) ? fmtDateTime(value, tz) : value;
}

function EvalCard({
  project,
  record,
  named,
  settledBy,
}: {
  project: string;
  record: EvalRecord;
  /** Name the delivery: there are several evals to tell apart. */
  named: boolean;
  /** The owner's sign-off that settled this eval's owner steps, if any. */
  settledBy?: EvalRecord | undefined;
}) {
  const { addReference, references } = useDiscuss();
  const { tz } = usePreferences();
  const pointed = references.some((r) => r.id === `eval:${record.delivery}`);
  return (
    <article
      className="ah-card ah-pad ah-stack"
      style={{ gap: 12 }}
      aria-label={`Eval ${record.delivery}`}
    >
      <div className="ah-row ah-wrap" style={{ gap: 10 }}>
        <VerdictBadge record={record} settledBy={settledBy} />
        {named && <b className="ah-mono">{deliveryLabel(record)}</b>}
        <span className="ah-row ah-wrap ah-small ah-muted" style={{ gap: 6 }}>
          {[
            record.evaluated_at ? `Evaluated ${evaluatedText(record.evaluated_at, tz)}` : null,
            ranBy(record.provenance) ? `by ${String(ranBy(record.provenance))}` : null,
            record.tickets.length > 0 ? record.tickets.join(", ") : null,
            record.acs === "all" || record.acs.length > 0 ? <Scope acs={record.acs} /> : null,
            record.prs.length > 0 ? record.prs.join(", ") : null,
          ]
            .filter((part) => part !== null)
            .map((part, i) => (
              <span key={i}>
                {i > 0 && "· "}
                {part}
              </span>
            ))}
        </span>
        {record.commit && <IdChip id={record.commit} short={record.commit.slice(0, 7)} />}
        <span className="ah-grow" />
        <Button
          size="sm"
          icon="message-square"
          aria-pressed={pointed}
          onClick={() => {
            addReference(evalReference(record));
          }}
        >
          {pointed ? `${record.delivery} is in the next message` : "Discuss this eval"}
        </Button>
        <Link className="ah-small" to={brainRoute(project, record.path)}>
          Open in Brain
        </Link>
      </div>
      {record.problem ? (
        <ProblemError title="This eval could not be read" detail={record.problem} />
      ) : (
        <NoteView
          key={record.path}
          project={project}
          path={record.path}
          missing={`No ${fileName(record.path)} yet.`}
          foldFrontmatter={{
            lead: (
              <span className="ah-small ah-muted">
                <PathText path={`brain/${record.path}`} max={80} dimDir />
              </span>
            ),
          }}
        />
      )}
    </article>
  );
}

/* ---------- The tab ---------- */

export interface EvalTabProps {
  project: string;
  slug: string;
  /** The feature's tickets: the scopes a run can take besides the whole feature. */
  tickets: readonly string[];
  /** The feature's epics (`planning.epics`): evaluating one is evaluating the whole feature. */
  epics?: readonly string[];
  /** `FeatureDetail.evals`: one per delivery, as the server orders them. */
  evals: readonly EvalRecord[];
  /** The delivery shown below the list (`pickEval`). */
  selected: EvalRecord | undefined;
  onSelect: (delivery: string) => void;
  /** The feature's tickets as the Tickets tab reads them: each group's title. */
  ticketRows?: readonly TicketRow[] | undefined;
  /** The feature's ACs, for each AC's text and status in an eval's AC list. */
  acRows?: readonly AcRow[] | undefined;
}

/** What a table row shows besides the eval itself. */
interface RowFacts {
  /** "Eval 3", "Owner sign-off". */
  label: string;
  /** The newest agent eval of its scope, when there are several. */
  current: boolean;
  /** The label of the newer eval of its scope that decides its ACs now. */
  supersededBy: string | undefined;
}

/** Whether the evals list is folded, kept on this machine. */
const LIST_KEY = "agent-hub:eval-list-open";

function readListOpen(): boolean {
  try {
    return window.localStorage.getItem(LIST_KEY) !== "false";
  } catch {
    return true;
  }
}

function writeListOpen(open: boolean) {
  try {
    window.localStorage.setItem(LIST_KEY, String(open));
  } catch {
    // Without storage the list only opens again on reload.
  }
}

/** The AC ids an eval names, `all` read as every AC of the feature. */
function evalAcs(e: EvalRecord, allAcs: readonly string[]): readonly string[] {
  return e.acs === "all" ? allAcs : e.acs;
}

/**
 * One scope's evals as the table reads them: each one's label, the agent evals newest first, the
 * newest of them, and that one when it waits on owner steps no owner decision settled yet.
 */
function groupFacts(evals: readonly EvalRecord[], settled: ReadonlyMap<string, EvalRecord>) {
  const runs = evals.filter((e) => e.provenance !== "owner");
  const current = runs[0];
  const waits =
    current?.verdict === "SHIP-WITH-OWNER-STEPS" && !current.problem && !settled.has(current.path);
  return { labels: runLabels(evals), runs, current, waiting: waits ? current : undefined };
}

/** The evals that wait on the owner: the newest of each scope, owner steps not settled. */
export function ownerStepsWaiting(
  evals: readonly EvalRecord[],
  tickets: readonly string[],
  epics: readonly string[],
): { scope: string; record: EvalRecord; label: string }[] {
  const settled = settledOwnerSteps(evals);
  return evalHistory(evals, tickets, epics).flatMap((group) => {
    const { labels, waiting } = groupFacts(group.evals, settled);
    return waiting
      ? [
          {
            scope: group.scope,
            record: waiting,
            label: labels.get(waiting.path) ?? waiting.delivery,
          },
        ]
      : [];
  });
}

/** How a row names its eval: "Eval 3" for an agent's eval, the owner's decisions by what they are. */
export function runLabels(evals: readonly EvalRecord[]): Map<string, string> {
  const labels = new Map<string, string>();
  let run = 0;
  for (const e of [...evals].reverse()) {
    if (e.legacy) labels.set(e.path, fileName(e.path));
    else if (e.provenance === "owner") {
      labels.set(e.path, e.verdict === "NO-SHIP" ? "Owner: more work" : "Owner sign-off");
    } else labels.set(e.path, `Eval ${String((run += 1))}`);
  }
  return labels;
}

/** A group's title: the ticket's title (without its epic tag), or the whole feature's name. */
function groupTitle(scope: string, rows: readonly TicketRow[]): string | null {
  if (scope === FEATURE_SCOPE) return null;
  const ids = scope.split(", ");
  const found = ids.length === 1 ? rows.find((r) => r.id === ids[0] || r.ref === ids[0]) : null;
  return found?.title ? splitTitle(found.title).text : null;
}

/** When an eval ran: the date and time, with how long ago under it; a bare date as it is. */
function EvaluatedCell({ value }: { value: string | null }) {
  const now = useNow(60_000);
  if (!value) return <span className="ah-subtle">—</span>;
  if (!value.includes("T") || Number.isNaN(Date.parse(value))) {
    return <span className="ah-small ah-num">{value}</span>;
  }
  return (
    <span className="ah-eval-when">
      <span className="ah-small">
        <Time iso={value} absolute />
      </span>
      <span className="ah-small ah-subtle">
        {fmtAgo(Math.max(0, now - Date.parse(value)) / 1000)}
      </span>
    </span>
  );
}

/**
 * The Eval tab (AC-136.32): a run of the evaluator, every delivery's eval (never only the last
 * one) with its verdict and scope, and the selected eval's note read in place.
 */
export function EvalTab({
  project,
  slug,
  tickets,
  epics = [],
  evals,
  selected,
  onSelect,
  ticketRows = [],
  acRows = [],
}: EvalTabProps) {
  const [listOpen, setListOpen] = useState(readListOpen);
  const history = evalHistory(evals, tickets, epics);
  const selectedScope = history.find((g) => g.evals.some((e) => e.path === selected?.path))?.scope;
  // A group the owner opened or closed stays so; any other is open when it holds the selected
  // eval (one shown from elsewhere too: a finished run, the sign-off) or is the only one.
  const [folded, setFolded] = useState<ReadonlyMap<string, boolean>>(() => new Map());
  const isOpen = (scope: string) =>
    folded.get(scope) ?? (history.length === 1 || scope === selectedScope);
  const toggleList = () => {
    writeListOpen(!listOpen);
    setListOpen(!listOpen);
  };
  const strip = (
    <EvalRunStrip
      project={project}
      slug={slug}
      tickets={tickets}
      evals={evals}
      onShow={onSelect}
      primary={evals.length === 0}
      epics={epics}
      caption={
        evals.length > 0 && (
          <span className="ah-row" style={{ gap: 8 }}>
            <Button
              size="sm"
              variant="ghost"
              icon={listOpen ? "chevron-down" : "chevron-right"}
              aria-expanded={listOpen}
              aria-controls="eval-list"
              onClick={toggleList}
            >
              {listOpen ? "Hide list" : "Show list"}
            </Button>
            <Tooltip label="Newest first per scope. The latest eval that names an AC decides it.">
              {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
              <span className="ah-small ah-muted" tabIndex={0}>
                {evals.length} eval{evals.length === 1 ? "" : "s"} · newest first
              </span>
            </Tooltip>
          </span>
        )
      }
    />
  );
  if (evals.length === 0) {
    return (
      <div className="ah-stack" style={{ gap: 12 }}>
        {strip}
        <div className="ah-card">
          <EmptyState icon="flask-conical" title="No evals yet.">
            The evaluator agent writes one note per delivery in{" "}
            <span className="ah-mono">evals/&lt;delivery&gt;.md</span>. Press Evaluate whole feature
            to write the first one.
          </EmptyState>
        </div>
      </div>
    );
  }
  const settled = settledOwnerSteps(evals);
  const acById = new Map(acRows.map((ac) => [ac.id, ac]));
  const acPasses = Object.fromEntries(acRows.map((ac) => [ac.id, ac.passes]));
  const allAcs = acRows.map((ac) => ac.id);
  const toggleGroup = (scope: string) => {
    setFolded((current) => new Map(current).set(scope, !isOpen(scope)));
  };
  const columns: {
    label: string;
    width?: number;
    cell: (e: EvalRecord, row: RowFacts) => ReactNode;
  }[] = [
    {
      label: "Eval",
      width: 190,
      cell: (e, row) => (
        <span className="ah-row" style={{ gap: 6, flexWrap: "nowrap" }}>
          <button
            type="button"
            className="ah-btn ah-btn-sm ah-btn-ghost"
            style={{ fontWeight: 500 }}
            aria-label={`${e.delivery}, ${e.verdict ?? "no verdict"}`}
            aria-current={selected?.path === e.path ? "true" : undefined}
            title={`brain/${e.path}`}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(e.delivery);
            }}
          >
            {row.label}
          </button>
          {row.current && <span className="ah-fm-chip">latest</span>}
        </span>
      ),
    },
    {
      label: "Verdict",
      cell: (e, row) =>
        e.problem ? (
          <span className="ah-small" style={{ color: "var(--failed)" }}>
            Unreadable: {e.problem}
          </span>
        ) : e.verdict ? (
          <VerdictBadge
            record={e}
            settledBy={settled.get(e.path)}
            supersededBy={row.supersededBy}
          />
        ) : (
          <span className="ah-subtle">—</span>
        ),
    },
    {
      label: "ACs",
      width: 150,
      cell: (e) =>
        e.acs === "all" && allAcs.length === 0 ? (
          <Scope acs={e.acs} />
        ) : (
          <AcList
            ids={evalAcs(e, allAcs)}
            acPasses={acRows.length > 0 ? acPasses : undefined}
            acRows={acById}
          />
        ),
    },
    {
      label: "Ran by",
      width: 150,
      cell: (e) => {
        const who = ranBy(e.provenance);
        return who ? (
          <span className="ah-small" title={e.provenance ?? undefined}>
            {who}
          </span>
        ) : (
          <span className="ah-subtle">—</span>
        );
      },
    },
    {
      label: "Evaluated",
      width: 150,
      cell: (e) => <EvaluatedCell value={e.evaluated_at} />,
    },
  ];
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      {strip}
      {listOpen && (
        <div className="ah-table-wrap" id="eval-list">
          <table className="ah-table ah-eval-table" aria-label="Evals">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.label} scope="col" style={c.width ? { width: c.width } : undefined}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>

            {history.map((group) => {
              const { labels, runs, current, waiting } = groupFacts(group.evals, settled);
              const latest = group.evals[0];
              const open = isOpen(group.scope);
              const title = groupTitle(group.scope, ticketRows);
              const name = group.scope === FEATURE_SCOPE ? featureName(epics) : group.scope;
              const facts = (e: EvalRecord): RowFacts => ({
                label: labels.get(e.path) ?? e.delivery,
                current: e === current && runs.length > 1,
                supersededBy:
                  e.provenance !== "owner" && current && e !== current
                    ? labels.get(current.path)
                    : undefined,
              });
              const callout = waiting && (
                <tr className="ah-eval-owner-row">
                  <td colSpan={columns.length}>
                    <OwnerStepsCallout
                      project={project}
                      slug={slug}
                      record={waiting}
                      label={`${group.scope === FEATURE_SCOPE ? "The whole feature" : group.scope} · ${labels.get(waiting.path) ?? waiting.delivery}`}
                      ownerAcs={evalAcs(waiting, allAcs).filter((id) => {
                        const ac = acById.get(id);
                        return ac ? passOf(ac) === "owner" : false;
                      })}
                      onShow={onSelect}
                    />
                  </td>
                </tr>
              );
              return (
                <tbody key={group.scope}>
                  <tr className="ah-eval-group" data-open={open || undefined}>
                    <th scope="colgroup" colSpan={columns.length}>
                      <button
                        type="button"
                        className="ah-eval-group-toggle"
                        aria-expanded={open}
                        aria-label={`${name}${title ? ` ${title}` : ""} · ${String(group.evals.length)} eval${group.evals.length === 1 ? "" : "s"}`}
                        onClick={() => {
                          toggleGroup(group.scope);
                        }}
                      >
                        <Icon name={open ? "chevron-down" : "chevron-right"} size="sm" />
                        <span className="ah-mono">{name}</span>
                        {title && <span className="ah-eval-group-title">{title}</span>}
                        <span className="ah-subtle">
                          · {group.evals.length} eval{group.evals.length === 1 ? "" : "s"}
                        </span>
                        <span className="ah-grow" />
                        {!open && latest?.verdict && (
                          <VerdictBadge record={latest} settledBy={settled.get(latest.path)} />
                        )}
                        {!open && latest?.evaluated_at && (
                          <span className="ah-small ah-subtle">
                            <Time iso={latest.evaluated_at} absolute />
                          </span>
                        )}
                      </button>
                    </th>
                  </tr>
                  {!open && callout}
                  {open &&
                    group.evals.map((e) => {
                      const row = facts(e);
                      return (
                        <Fragment key={e.path}>
                          <tr
                            aria-selected={selected?.path === e.path}
                            onClick={() => {
                              onSelect(e.delivery);
                            }}
                          >
                            {columns.map((c) => (
                              <td key={c.label} style={{ whiteSpace: "normal" }}>
                                {c.cell(e, row)}
                              </td>
                            ))}
                          </tr>
                          {e === waiting && callout}
                        </Fragment>
                      );
                    })}
                </tbody>
              );
            })}
          </table>
        </div>
      )}
      {selected && (
        <EvalCard
          project={project}
          record={selected}
          named
          settledBy={settled.get(selected.path)}
        />
      )}
    </div>
  );
}
