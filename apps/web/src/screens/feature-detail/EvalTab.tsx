import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import {
  AppLink,
  Banner,
  Button,
  EmptyState,
  Icon,
  ProblemError,
  SegmentedControl,
  StatusBadge,
  Tooltip,
  type Status,
} from "../../components";
import { ApiProblem, useApi } from "../../lib/api";
import { brainRoute } from "../../lib/brainLinks";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useDiscuss, type DiscussReference } from "../../shell/discuss";
import { NoteView } from "../brain/NoteView";
import { VERDICT_STATUS } from "../features/parts";
import { agentSessionHref } from "../sessions-list/control";
import { useCreateAgentSession, useHubSessionStart } from "../sessions-list/queries";

type EvalRecord = components["schemas"]["EvalRecord"];
type AgentSessionStatus = components["schemas"]["AgentSessionStatus"];

function Ids({ ids }: { ids: readonly string[] }) {
  if (ids.length === 0) return <span className="ah-subtle">—</span>;
  return <span className="ah-mono ah-small">{ids.join(", ")}</span>;
}

function Scope({ acs }: { acs: EvalRecord["acs"] }) {
  if (acs === "all") return <span>All ACs</span>;
  if (acs.length === 0) return <span className="ah-subtle">—</span>;
  return (
    <span title={acs.join(", ")}>
      {acs.length} AC{acs.length === 1 ? "" : "s"}
    </span>
  );
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
  idle: { status: "done", label: "Finished", note: "The new eval shows in the list within 15 s." },
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
}: {
  project: string;
  slug: string;
  tickets: readonly string[];
  evals: readonly EvalRecord[];
  onShow: (delivery: string) => void;
}) {
  const key = runKey(project, slug);
  const { tz } = usePreferences();
  const start = useHubSessionStart(project);
  const create = useCreateAgentSession();
  const [run, setRun] = useState<StoredRun | null>(() => readRun(key));
  const [scope, setScope] = useState(FEATURE_SCOPE);
  const session = useApi(
    "/api/v1/agent-sessions/{agent_session_id}",
    { path: { agent_session_id: run?.id ?? "" } },
    {
      enabled: run !== null,
      retry: false,
      refetchInterval: (query) => {
        const status = query.state.data?.status;
        return status === undefined || IN_FLIGHT.includes(status) ? 3_000 : false;
      },
    },
  );
  const gone = session.error instanceof ApiProblem && session.error.status === 404;
  if (gone && run) {
    writeRun(key, null);
    setRun(null);
  }
  const status = session.data?.status;
  const inFlight = run !== null && (status === undefined || IN_FLIGHT.includes(status));
  const look = status ? RUN_LOOK[status] : null;
  const fresh = run ? evals.filter((e) => !run.known.includes(e.path)) : [];
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
  return (
    <section className="ah-card ah-pad ah-stack" style={{ gap: 10 }} aria-label="Evaluate">
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <b>Evaluate</b>
        <span className="ah-small ah-muted">Scope</span>
        <span
          style={inFlight ? { pointerEvents: "none", opacity: "var(--disabled-opacity, 0.5)" } : {}}
          aria-disabled={inFlight || undefined}
        >
          <SegmentedControl
            label="Evaluation scope"
            value={shownScope}
            onChange={(id) => {
              if (!inFlight) setScope(id);
            }}
            options={[
              { id: FEATURE_SCOPE, label: "Whole feature" },
              ...tickets.map((t) => ({ id: t, label: t })),
            ]}
          />
        </span>
        <span className="ah-grow" />
        {blocked ? (
          <Tooltip label={blocked}>
            <Button
              variant="primary"
              icon="flask-conical"
              disabled
              aria-label={`${action}. ${blocked}`}
            >
              {action}
            </Button>
          </Tooltip>
        ) : (
          <Button
            variant="primary"
            icon="flask-conical"
            disabled={create.isPending}
            onClick={() => void evaluate()}
          >
            {create.isPending ? "Starting…" : action}
          </Button>
        )}
      </div>
      <span className="ah-small ah-muted">
        Re-runs every check and gate in scope and writes a new eval. Existing evals are kept.
      </span>
      {start.unavailable && (
        <Banner tone="warning" boxed>
          <b>{start.unavailable.title}.</b> {start.unavailable.detail}
        </Banner>
      )}
      {create.error instanceof ApiProblem && (
        <ProblemError
          compact
          title="Could not start the evaluator"
          detail={create.error.detail ?? create.error.title}
          status={create.error.status}
          onRetry={() => void evaluate()}
        />
      )}
      {run && (
        <div className="ah-row ah-wrap ah-small" role="status" style={{ gap: 10 }}>
          <StatusBadge status={look?.status ?? "queued"} label={look?.label ?? "Starting…"} />
          <span>
            {scopeLabel(run.scope)} · started {fmtClock(run.started_at, tz)}
          </span>
          {look?.note && <span className="ah-muted">{look.note}</span>}
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
          <AppLink className="ah-btn ah-btn-sm" href={agentSessionHref(run.id)}>
            <Icon name="message-square" size="sm" />
            Open chat
          </AppLink>
        </div>
      )}
    </section>
  );
}

/* ---------- The selected eval ---------- */

function EvalCard({ project, record }: { project: string; record: EvalRecord }) {
  const { addReference, references } = useDiscuss();
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
        <b className="ah-mono">{record.delivery}</b>
        <span className="ah-small ah-muted">
          {[
            record.tickets.join(", "),
            record.acs === "all"
              ? "all ACs"
              : `${String(record.acs.length)} AC${record.acs.length === 1 ? "" : "s"}`,
            record.commit ? `commit ${record.commit.slice(0, 7)}` : "",
            record.evaluated_at ?? "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
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
      <span className="ah-mono ah-small ah-muted">brain/{record.path}</span>
      {record.problem ? (
        <ProblemError title="This eval could not be read" detail={record.problem} />
      ) : (
        <NoteView
          key={record.path}
          project={project}
          path={record.path}
          missing={`No ${fileName(record.path)} yet.`}
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
}

/**
 * The Eval tab (AC-136.32): a run of the evaluator, every delivery's eval (never only the last
 * one) with its verdict and scope, and the selected eval's note read in place.
 */
export function EvalTab({ project, slug, tickets, evals, selected, onSelect }: EvalTabProps) {
  const strip = (
    <EvalRunStrip project={project} slug={slug} tickets={tickets} evals={evals} onShow={onSelect} />
  );
  if (evals.length === 0) {
    return (
      <div className="ah-stack" style={{ gap: 12 }}>
        {strip}
        <div className="ah-card">
          <EmptyState icon="flask-conical" title="No evals yet.">
            The evaluator agent writes one note per delivery in{" "}
            <span className="ah-mono">evals/&lt;delivery&gt;.md</span>.
          </EmptyState>
        </div>
      </div>
    );
  }
  const columns: { label: string; width?: number; cell: (e: EvalRecord) => ReactNode }[] = [
    {
      label: "Delivery",
      width: 150,
      cell: (e) => (
        <span className="ah-stack" style={{ gap: 2 }}>
          <button
            type="button"
            className="ah-btn ah-btn-sm ah-btn-ghost ah-mono"
            style={{ fontWeight: 500 }}
            aria-label={`${e.delivery}, ${e.verdict ?? "no verdict"}`}
            aria-current={selected?.path === e.path ? "true" : undefined}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(e.delivery);
            }}
          >
            {e.delivery}
          </button>
          {e.legacy && <span className="ah-small ah-muted">legacy</span>}
        </span>
      ),
    },
    {
      label: "Verdict",
      width: 200,
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
    { label: "Tickets", cell: (e) => <Ids ids={e.tickets} /> },
    { label: "ACs", width: 90, cell: (e) => <Scope acs={e.acs} /> },
    { label: "PRs", cell: (e) => <Ids ids={e.prs} /> },
    {
      label: "Commit",
      width: 90,
      cell: (e) =>
        e.commit ? (
          <span className="ah-mono ah-small" title={e.commit}>
            {e.commit.slice(0, 7)}
          </span>
        ) : (
          <span className="ah-subtle">—</span>
        ),
    },
    {
      label: "Evaluated",
      width: 110,
      cell: (e) =>
        e.evaluated_at ? (
          <span className="ah-small">{e.evaluated_at}</span>
        ) : (
          <span className="ah-subtle">—</span>
        ),
    },
    {
      label: "Note",
      width: 140,
      cell: (e) => (
        <Link
          className="ah-mono ah-small"
          to={brainRoute(project, e.path)}
          aria-label={`${fileName(e.path)}, the eval of ${e.delivery}`}
          title={`brain/${e.path}`}
          onClick={(event) => {
            event.stopPropagation();
          }}
        >
          {fileName(e.path)}
        </Link>
      ),
    },
  ];
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      {strip}
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
          <span>
            {evals.length} eval{evals.length === 1 ? "" : "s"} · the latest eval that names an AC
            decides it · select one to read it below
          </span>
        </div>
      </div>
      {selected && <EvalCard project={project} record={selected} />}
    </div>
  );
}
