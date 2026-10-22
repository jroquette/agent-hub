import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { useParams, useSearchParams } from "react-router";

import {
  AppLink,
  Banner,
  Button,
  CodeBlock,
  Icon,
  ProblemError,
  RedactionChip,
  Skeleton,
  Time,
  TimelineEvent,
  Toast,
} from "../../components";
import { useNow } from "../../lib/clock";
import { fmtClock, fmtDuration } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useShell } from "../../shell/AppShell";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { GateDecision } from "../approvals/GateDecision";
import type { Approval } from "../approvals/queries";
import { StaleStamp } from "../portfolio/StaleStamp";
import { useRun } from "../run-detail/queries";
import { RunCommands } from "../run-detail/RunCommands";
import { Findings } from "./Findings";
import { answerDone, answerShort, containerProblem, PausedView } from "./Investigation";
import { Page, ScenarioRunBadge, shortId } from "./parts";
import {
  gateNodeOf,
  gateRun,
  scenarioHref,
  useOpenHumanGates,
  useScenario,
  useScenarioRun,
  useScenarioRunStream,
  type Answer,
  type ScenarioRunDetail,
  type ScenarioStep,
} from "./queries";
import {
  divergence,
  investigationGates,
  pausedFacts,
  plural,
  roughDuration,
  stepsDone,
  timelineRows,
} from "./timeline";

/* Scenario run (AGH-350 T13, spec 23 screen 3): where the scenario run got to, why it stopped,
 * and what to decide now. Paused at an investigation: the chat, the options and the answer;
 * waiting on a policy ask: approve or reject here (AM-14, AM-17). */

const MAX_INVESTIGATIONS = 10;
const CREDENTIAL = /^<credential ([A-Za-z0-9_]+)>$/;

function CaptureValue({ value }: { value: unknown }) {
  if (typeof value === "string") {
    const match = CREDENTIAL.exec(value);
    if (match) return <RedactionChip kind={`credential ${match[1] ?? ""}`} />;
    return <span className="ah-mono">{value}</span>;
  }
  return <span className="ah-mono">{JSON.stringify(value)}</span>;
}

function Fact({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "112px 1fr",
        gap: 8,
        padding: "6px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <dt className="ah-small ah-subtle">{k}</dt>
      <dd className="ah-small" style={{ minWidth: 0, overflowWrap: "anywhere", margin: 0 }}>
        {children}
      </dd>
    </div>
  );
}

function modeLabel(mode: string | null): string {
  if (mode === "interactive") return "Interactive";
  if (mode === "regression") return "Regression";
  return "—";
}

function Facts({ run }: { run: ScenarioRunDetail }) {
  const running = run.workarounds.find((w) => w.status === null);
  return (
    <aside className="ah-card" aria-label="Scenario run facts">
      <div className="ah-card-head">
        <b className="ah-small">Scenario run facts</b>
      </div>
      <dl style={{ padding: "4px 16px 12px", margin: 0 }}>
        <Fact k="Scenario">
          <span className="ah-mono">{run.scenario ?? "—"}</span>
          {run.pack && <span className="ah-subtle"> ({run.pack})</span>}
        </Fact>
        <Fact k="Environment">
          <span className="ah-mono">{run.environment ?? "—"}</span>
        </Fact>
        <Fact k="Mode">{modeLabel(run.mode)}</Fact>
        <Fact k="Investigations">
          {run.investigations.length} of at most {MAX_INVESTIGATIONS}
        </Fact>
        <Fact k="Workarounds">
          {running
            ? `Workaround ${String(running.number)} running: option ${running.option}`
            : String(run.workarounds.length)}
        </Fact>
        <Fact k="Captures">
          {run.captures.length === 0 ? (
            "—"
          ) : (
            <span className="ah-stack" style={{ gap: 2 }}>
              {run.captures.map((capture) => (
                <span key={`${capture.node}:${String(capture.attempt)}:${capture.name}`}>
                  <span className="ah-mono">{capture.name}</span> ={" "}
                  <CaptureValue value={(capture as { value: unknown }).value} />
                </span>
              ))}
            </span>
          )}
        </Fact>
      </dl>
    </aside>
  );
}

function Timeline({
  run,
  steps,
}: {
  run: ScenarioRunDetail;
  steps: readonly ScenarioStep[] | undefined;
}) {
  const { tz } = usePreferences();
  const [params, setParams] = useSearchParams();
  const selected = params.get("event");
  const rows = timelineRows(run, steps);
  const select = (id: string) => {
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        copy.set("event", id);
        return copy;
      },
      { replace: true },
    );
  };
  return (
    <section aria-label="Timeline" className="ah-stack" style={{ gap: 8, minWidth: 0 }}>
      <h2 className="ah-h3" style={{ margin: 0 }}>
        Timeline
      </h2>
      <div className="ah-timeline">
        {rows.map((row) => (
          <TimelineEvent
            key={row.id}
            current={selected === row.id}
            onSelect={() => {
              select(row.id);
            }}
            ev={{
              id: row.id,
              time: row.at ? fmtClock(row.at, tz) : "",
              iso: row.at ?? undefined,
              cat: row.cat,
              icon: row.icon,
              actor: { kind: row.actor === "Agent" ? "agent" : "main", label: row.actor },
              text: (
                <>
                  {row.text}
                  {row.captures.map((capture) => (
                    <span key={capture.name}>
                      {" · captured "}
                      {capture.name} = <CaptureValue value={capture.value} />
                    </span>
                  ))}
                </>
              ),
              detail:
                row.detail.length > 0 ? (
                  <ul className="ah-small" style={{ margin: 0, paddingLeft: 18 }}>
                    {row.detail.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                ) : undefined,
            }}
          />
        ))}
      </div>
    </section>
  );
}

function Header({
  run,
  now,
  waiting,
  heading,
}: {
  run: ScenarioRunDetail;
  now: number;
  waiting: boolean;
  heading: RefObject<HTMLHeadingElement>;
}) {
  const started = run.timeline.find((entry) => entry.event === "start")?.at ?? null;
  const end = run.timeline.filter((entry) => entry.event === "end").at(-1)?.at ?? null;
  const seconds = started ? ((end ? Date.parse(end) : now) - Date.parse(started)) / 1000 : null;
  const scenario = run.scenario ?? "";
  return (
    <div className="ah-stack" style={{ gap: 6 }}>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: run.project, href: `/projects/${encodeURIComponent(run.project)}` },
          { label: "Scenarios", href: "/scenarios" },
          { label: scenario, href: scenarioHref(run.project, scenario), mono: true },
          { label: `Scenario run ${shortId(run.run_id)}`, mono: true },
        ]}
      />
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h1 ref={heading} className="ah-h1" tabIndex={-1}>
          Scenario run <span className="ah-mono">{shortId(run.run_id)}</span>
        </h1>
        <ScenarioRunBadge status={run.status} waiting={waiting} />
        <span className="ah-small">
          <AppLink href={scenarioHref(run.project, scenario)} className="ah-mono">
            {scenario}
          </AppLink>{" "}
          · <span className="ah-mono">{run.environment ?? "—"}</span>{" "}
          <span className="ah-badge ah-badge-quiet">{modeLabel(run.mode)}</span>
        </span>
        <span className="ah-grow" />
        <StaleStamp />
      </div>
      <span className="ah-small ah-muted">
        Started {started ? <Time iso={started} absolute /> : "—"}
        {seconds !== null && ` · ${fmtDuration(seconds)}`}
        {run.investigations.length > 0 &&
          ` · investigation ${String(run.investigations.length)} of at most ${String(MAX_INVESTIGATIONS)}`}
      </span>
    </div>
  );
}

function PauseBanner({
  run,
  steps,
}: {
  run: ScenarioRunDetail;
  steps: readonly ScenarioStep[] | undefined;
}) {
  const step = run.paused_step ?? "";
  const pending = run.investigations.find((item) => item.number === run.open_investigation);
  const type = steps?.find((s) => s.id === step)?.type;
  const facts = pausedFacts(run, step);
  const counted =
    facts.polls > 0
      ? ` (${plural(facts.polls, "poll")}${facts.seconds !== null ? ` in ${roughDuration(facts.seconds)}` : ""})`
      : "";
  return (
    <section
      aria-label={`Paused at ${step}`}
      style={{
        background: "var(--waiting-soft)",
        borderLeft: "4px solid var(--waiting)",
        borderRadius: "var(--radius-lg)",
        padding: "12px 16px",
        display: "grid",
        gridTemplateColumns: "24px 1fr",
        gap: 10,
      }}
    >
      <Icon name="hand" style={{ color: "var(--waiting)", marginTop: 2 }} />
      <div className="ah-stack" style={{ gap: 4 }}>
        <b>
          Paused at <span className="ah-mono">{step}</span>:{" "}
          {divergence(pending?.failure_kind, type ?? (facts.polls > 0 ? "expect" : undefined))}
          {counted}.
        </b>
        <span>Steps that did not depend on it have run.</span>
        <span>Decide below: pick an option, retry the step, or stop the scenario run.</span>
      </div>
    </section>
  );
}

function EndLine({
  run,
  steps,
}: {
  run: ScenarioRunDetail;
  steps: readonly ScenarioStep[] | undefined;
}) {
  const end = run.timeline.filter((entry) => entry.event === "end").at(-1);
  const { tz } = usePreferences();
  const at = end?.at ? fmtClock(end.at, tz) : "—";
  if (run.status === "done") {
    return (
      <div
        className="ah-row ah-small"
        style={{
          gap: 6,
          background: "var(--done-soft)",
          padding: "8px 12px",
          borderRadius: "var(--radius-md)",
        }}
      >
        <Icon name="circle-check" size="sm" style={{ color: "var(--done)" }} />
        <span>
          Done at {at} · {plural(stepsDone(run), "step")} ·{" "}
          {plural(run.workarounds.length, "workaround")}
        </span>
      </div>
    );
  }
  if (run.status === "cancelled") {
    const stop = run.decisions.filter((d) => d.choice === "stop").at(-1);
    const by = stop?.approver ? ` by ${stop.approver}` : "";
    const where = stop?.where === "web" ? " in hub web" : stop?.where ? ` in ${stop.where}` : "";
    return (
      <div
        className="ah-row ah-small"
        style={{
          gap: 6,
          background: "var(--blocked-soft)",
          padding: "8px 12px",
          borderRadius: "var(--radius-md)",
        }}
      >
        <Icon name="octagon-x" size="sm" style={{ color: "var(--blocked)" }} />
        <span>
          Stopped at {at}
          {by}
          {where}. Findings are kept; nothing was rewound.
        </span>
      </div>
    );
  }
  if (run.status === "failed") {
    const failed = run.timeline
      .filter((e) => e.event === "step_end" && e.status === "failed")
      .at(-1);
    const step = failed?.node ?? "";
    const type = steps?.find((s) => s.id === step)?.type;
    const kind =
      run.investigations.filter((item) => item.step === step).at(-1)?.failure_kind ??
      (type === "expect" ? "timeout" : null);
    const tail =
      run.mode === "regression"
        ? " Regression mode: no investigation."
        : run.investigations.length >= MAX_INVESTIGATIONS
          ? ` The investigation limit is reached (${String(MAX_INVESTIGATIONS)} of ${String(MAX_INVESTIGATIONS)}).`
          : "";
    return (
      <section
        aria-label="Failure"
        style={{
          background: "var(--failed-soft)",
          borderLeft: "4px solid var(--failed)",
          borderRadius: "var(--radius-lg)",
          padding: "12px 16px",
        }}
        className="ah-row"
      >
        <Icon name="octagon-x" style={{ color: "var(--failed)" }} />
        <span>
          Failed at {step}: {divergence(kind, type)}.{tail}
        </span>
      </section>
    );
  }
  return null;
}

/** The open gates of the run a person answers here: every one but the investigation's (the
 * run's record and the open-gates read name it, never its id, E-10). */
function useOpenPolicyAsks(run: ScenarioRunDetail): Approval[] {
  const gates = useOpenHumanGates(run.project);
  if (run.status !== null) return [];
  const investigations = investigationGates(run);
  return (gates.data?.items ?? []).filter(
    (gate) =>
      gateRun(gate) === run.run_id &&
      gate.gate_kind !== "investigation" &&
      !investigations.has(gateNodeOf(gate)),
  );
}

function PolicyAsks({ asks }: { asks: readonly Approval[] }) {
  if (asks.length === 0) return null;
  return (
    <section
      aria-label="Waiting for you"
      className="ah-card ah-stack"
      style={{ gap: 12, padding: 16 }}
    >
      <div className="ah-row" style={{ gap: 6 }}>
        <Icon name="stamp" size="sm" style={{ color: "var(--waiting)" }} />
        <span className="ah-overline">Waiting for you</span>
      </div>
      {asks.map((gate) => (
        <div key={gate.id} className="ah-stack" style={{ gap: 6 }}>
          <span className="ah-small">
            <span className="ah-mono">{gateNodeOf(gate)}</span> waits for your approval since{" "}
            <Time iso={gate.requested_at} />. Reject cancels the scenario run.
          </span>
          <GateDecision approvalId={gate.id} />
        </div>
      ))}
    </section>
  );
}

const ENDED_WORDS: Readonly<Record<string, string>> = {
  done: "Scenario run done",
  failed: "Scenario run failed",
  cancelled: "Scenario run cancelled",
};

function RunBody({ run, refetch }: { run: ScenarioRunDetail; refetch: () => void }) {
  const ended = run.status !== null;
  const now = useNow(ended ? 60_000 : 1000);
  useScenarioRunStream(run.run_id, !ended);
  const scenario = useScenario(run.project, run.scenario ?? "");
  const workflowRun = useRun(run.run_id);
  const steps = scenario.data?.steps;
  const paused = run.open_investigation !== null;
  const asks = useOpenPolicyAsks(run);
  const heading = useRef<HTMLHeadingElement>(null);
  // An answer recorded here: its toast, and a resuming line until the record moves on (B3).
  const [answered, setAnswered] = useState<{ answer: Answer; step: string; mark: number } | null>(
    null,
  );
  const onAnswered = useCallback(
    (answer: Answer) => {
      setAnswered({ answer, step: run.paused_step ?? "", mark: run.timeline.length });
    },
    [run.paused_step, run.timeline.length],
  );
  const moved = answered !== null && (run.timeline.length > answered.mark || ended);
  if (moved) {
    // The record moved on: the resuming line and the toast end (state adjusted while rendering).
    setAnswered(null);
  }
  // The paused view leaves after an answer: focus goes to the page's heading.
  const wasPaused = useRef(paused);
  useEffect(() => {
    if (wasPaused.current && !paused) heading.current?.focus();
    wasPaused.current = paused;
  }, [paused]);
  const announcement =
    answered !== null
      ? "Answer recorded"
      : run.status !== null
        ? (ENDED_WORDS[run.status] ?? "")
        : paused
          ? `Scenario run paused at ${run.paused_step ?? ""}`
          : "";
  // Run control is off in the container: the reads stay, every answer and write is off.
  const [controlOff, setControlOff] = useState(false);
  const markControlOff = useCallback(() => {
    setControlOff(true);
  }, []);
  const container = containerProblem(run);
  const findings = <Findings run={run} ended={ended} actionsOff={controlOff} />;
  return (
    <Page>
      <div className="ah-row ah-wrap" style={{ gap: 12, alignItems: "flex-start" }}>
        <div className="ah-grow">
          <Header run={run} now={now} waiting={paused || asks.length > 0} heading={heading} />
        </div>
        {workflowRun.data?.status === "running" && !paused && (
          <RunCommands run={workflowRun.data} noun="scenario run" only={["cancel"]} />
        )}
      </div>
      {controlOff && (
        <Banner tone="info" boxed live={false}>
          <span className="ah-stack" style={{ gap: 4 }}>
            <b>{container.title}</b>
            <span>{container.detail}</span>
            {container.command && <CodeBlock code={container.command} />}
          </span>
        </Banner>
      )}
      <div data-announcer="" className="ah-sr" aria-live="polite">
        {announcement}
      </div>
      {paused && <PauseBanner run={run} steps={steps} />}
      {!paused && answered !== null && (
        <div role="status" className="ah-row ah-small" style={{ gap: 6 }}>
          <Icon name="rotate-ccw" size="sm" />
          {answerDone(answered.answer, answered.step)}
        </div>
      )}
      {answered !== null && <Toast>{answerShort(answered.answer, answered.step)}</Toast>}
      <EndLine run={run} steps={steps} />
      <PolicyAsks asks={asks} />
      {paused ? (
        <PausedView
          run={run}
          controlOff={controlOff}
          onControlOff={markControlOff}
          onAnswered={onAnswered}
          onRefetch={refetch}
          findings={findings}
        />
      ) : (
        findings
      )}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 340px",
          gap: 16,
          alignItems: "start",
        }}
      >
        <Timeline run={run} steps={steps} />
        <Facts run={run} />
      </div>
    </Page>
  );
}

function NotFound({ runId }: { runId: string }) {
  const { openPalette } = useShell();
  return (
    <Page>
      <h1 className="ah-h2">Scenario run {shortId(runId)} not found</h1>
      <p className="ah-muted" style={{ margin: 0 }}>
        No scenario run has the id {runId} in the registered hubs. It may belong to a hub that is no
        longer registered.
      </p>
      <div className="ah-row" style={{ gap: 8 }}>
        <Button
          icon="search"
          onClick={() => {
            openPalette(runId);
          }}
        >
          Search with Ctrl K
        </Button>
        <AppLink className="ah-btn" href="/scenarios">
          Go to Scenarios
        </AppLink>
      </div>
    </Page>
  );
}

/** `/scenarios/:project/:name/runs/:runId`: one scenario run. */
export function ScenarioRunScreen() {
  const { runId = "" } = useParams();
  const run = useScenarioRun(runId, true);
  if (run.isPending) {
    return (
      <Page>
        <Skeleton width={420} height={28} />
        <Skeleton width={560} height={14} />
        <Skeleton height={64} />
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} height={40} />
        ))}
      </Page>
    );
  }
  if (run.isError) {
    const error = run.error;
    if (error.status === 404) return <NotFound runId={runId} />;
    if (error.status === 422) {
      const large = error.code === "record_too_large";
      return (
        <Page>
          <Banner tone="error" boxed>
            <span className="ah-stack" style={{ gap: 6 }}>
              <b>
                {large
                  ? "This scenario run's record is too large to read here"
                  : "This scenario run's record cannot be read"}
              </b>
              {large ? (
                <>
                  <span>hub web reads records up to 8 MiB. List its findings from a terminal:</span>
                  <CodeBlock code={`./hub scenario findings ${runId}`} />
                </>
              ) : (
                <span>
                  A line before its last is not valid JSON. The record is .agent-runs/workflows/
                  {runId}/records.jsonl in the hub.
                </span>
              )}
            </span>
          </Banner>
        </Page>
      );
    }
    return (
      <Page>
        <ProblemError
          title="Could not load the scenario run"
          detail={error.detail}
          status={error.status}
          onRetry={() => void run.refetch()}
        />
      </Page>
    );
  }
  return (
    <RunBody
      run={run.data}
      refetch={() => {
        void run.refetch();
      }}
    />
  );
}
