import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
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
  Tooltip,
  type Status,
} from "../../components";
import { ApiProblem, apiCommand, apiKey, useApi } from "../../lib/api";
import { brainRoute } from "../../lib/brainLinks";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtDateTime } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useDiscuss, type DiscussReference } from "../../shell/discuss";
import { NoteView } from "../brain/NoteView";
import { VERDICT_STATUS } from "../features/parts";
import { agentSessionHref } from "../sessions-list/control";
import { useCreateAgentSession, useHubSessionStart } from "../sessions-list/queries";

type EvalRecord = components["schemas"]["EvalRecord"];
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
}: {
  project: string;
  slug: string;
  tickets: readonly string[];
  evals: readonly EvalRecord[];
  onShow: (delivery: string) => void;
  /** The tab's main action (no eval yet); otherwise re-running is secondary to reading. */
  primary: boolean;
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
  const variant = primary ? "primary" : "default";
  return (
    <section className="ah-stack" style={{ gap: 8 }} aria-label="Evaluate">
      <div className="ah-row ah-wrap" style={{ gap: 10 }}>
        <span className="ah-grow" />
        {tickets.length > 0 && (
          <SegmentedControl
            label="Evaluation scope"
            value={shownScope}
            disabled={inFlight}
            onChange={setScope}
            options={[
              { id: FEATURE_SCOPE, label: "Whole feature" },
              ...tickets.map((t) => ({ id: t, label: t })),
            ]}
          />
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
 * an `owner-signoff` SHIP eval over the ACs that waited, and the Evaluate step turns done.
 */
function OwnerSignOff({
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
  return (
    <section
      className="ah-card ah-pad ah-stack"
      style={{ gap: 10, borderColor: "var(--waiting)" }}
      aria-label="Owner steps"
    >
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <Icon name="hand" size="sm" />
        <b>Waiting on your steps</b>
        <span className="ah-small ah-muted">{reason}</span>
        <span className="ah-grow" />
        {confirming ? (
          <>
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
          </>
        ) : (
          <Button
            variant="primary"
            icon="check"
            onClick={() => {
              setConfirming(true);
            }}
          >
            Mark owner steps done
          </Button>
        )}
      </div>
      <span className="ah-small ah-muted">
        {confirming
          ? "Confirm you did every owner step the eval lists. This writes evals/owner-signoff.md with verdict SHIP, signed by you; existing evals are kept."
          : "Did the manual steps the eval lists? Sign them off and the Evaluate step turns done."}
      </span>
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
    </section>
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
}: {
  project: string;
  record: EvalRecord;
  /** Name the delivery: there are several evals to tell apart. */
  named: boolean;
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
        {record.verdict && (
          <StatusBadge status={VERDICT_STATUS[record.verdict]} label={record.verdict} />
        )}
        {named && <b className="ah-mono">{deliveryLabel(record)}</b>}
        <span className="ah-row ah-wrap ah-small ah-muted" style={{ gap: 6 }}>
          {[
            record.evaluated_at ? `Evaluated ${evaluatedText(record.evaluated_at, tz)}` : null,
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
  /** `FeatureDetail.evals`: one per delivery, as the server orders them. */
  evals: readonly EvalRecord[];
  /** The delivery shown below the list (`pickEval`). */
  selected: EvalRecord | undefined;
  onSelect: (delivery: string) => void;
  /** Why the Evaluate step waits on the owner's steps; null when it does not. */
  ownerWait?: string | null;
}

/**
 * The Eval tab (AC-136.32): a run of the evaluator, every delivery's eval (never only the last
 * one) with its verdict and scope, and the selected eval's note read in place.
 */
export function EvalTab({
  project,
  slug,
  tickets,
  evals,
  selected,
  onSelect,
  ownerWait = null,
}: EvalTabProps) {
  const { tz } = usePreferences();
  const strip = (
    <>
      {ownerWait && (
        <OwnerSignOff project={project} slug={slug} reason={ownerWait} onShow={onSelect} />
      )}
      <EvalRunStrip
        project={project}
        slug={slug}
        tickets={tickets}
        evals={evals}
        onShow={onSelect}
        primary={evals.length === 0 && !ownerWait}
      />
    </>
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
  const columns: { label: string; width?: number; cell: (e: EvalRecord) => ReactNode }[] = [
    {
      label: "Eval",
      cell: (e) => (
        <button
          type="button"
          className="ah-btn ah-btn-sm ah-btn-ghost ah-mono"
          style={{ fontWeight: 500 }}
          aria-label={`${e.delivery}, ${e.verdict ?? "no verdict"}`}
          aria-current={selected?.path === e.path ? "true" : undefined}
          title={`brain/${e.path}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(e.delivery);
          }}
        >
          {deliveryLabel(e)}
        </button>
      ),
    },
    {
      label: "Verdict",
      cell: (e) =>
        e.problem ? (
          <span className="ah-small" style={{ color: "var(--failed)" }}>
            Unreadable: {e.problem}
          </span>
        ) : e.verdict ? (
          <StatusBadge status={VERDICT_STATUS[e.verdict]} label={e.verdict} />
        ) : (
          <span className="ah-subtle">—</span>
        ),
    },
    { label: "Scope", width: 110, cell: (e) => <Scope acs={e.acs} /> },
    {
      label: "Evaluated",
      width: 170,
      cell: (e) =>
        e.evaluated_at ? (
          <span className="ah-small">{evaluatedText(e.evaluated_at, tz)}</span>
        ) : (
          <span className="ah-subtle">—</span>
        ),
    },
  ];
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      {strip}
      {evals.length > 1 && (
        <div className="ah-table-wrap">
          <table className="ah-table" aria-label="Evals">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.label} scope="col" style={c.width ? { width: c.width } : undefined}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {evals.map((e) => (
                <tr
                  key={e.path}
                  aria-selected={selected?.path === e.path}
                  onClick={() => {
                    onSelect(e.delivery);
                  }}
                >
                  {columns.map((c) => (
                    <td key={c.label} style={{ whiteSpace: "normal" }}>
                      {c.cell(e)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="ah-table-foot">
            <span>{evals.length} evals · the latest one that names an AC decides it</span>
          </div>
        </div>
      )}
      {selected && <EvalCard project={project} record={selected} named={evals.length > 1} />}
    </div>
  );
}
