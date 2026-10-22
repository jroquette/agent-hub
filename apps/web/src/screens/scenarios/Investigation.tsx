import { useEffect, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";

import {
  Button,
  CodeBlock,
  ConfirmDialog,
  DataTable,
  OptionRow,
  ProvenanceBadge,
  Skeleton,
} from "../../components";
import { useMutation } from "@tanstack/react-query";

import { apiCommand, type ApiProblem } from "../../lib/api";
import { readStored, writeStored } from "../../lib/storage";
import { DiscussChat } from "../agent-session/DiscussChat";
import { sessionControlUnavailable } from "../sessions-list/control";
import { DraftLine, EffectBadge, PolicyBadge, sentence, WhereText } from "./parts";
import {
  useAnswerInvestigation,
  useOpenInvestigation,
  type Answer,
  type ScenarioOption,
  type ScenarioRunDetail,
} from "./queries";

/* The paused view (AM-1, AM-2, E-15): the investigation chat, which the page starts or rejoins
 * on load, with the agent's limits beside it, and the options with their plans, answered by a
 * pick, a retry or a stop, each behind a confirm. */

const LIMITS_KEY = "ah.scenarios.limits";
const MAX_INVESTIGATIONS = 10;
const ASKS_IN_OPTION = "Picking this option is your approval of this step.";

interface PlannedStep {
  index: number;
  action: string;
  effect: string | null;
  decision: string;
  endpoint: Record<string, unknown>;
}

function plannedSteps(option: ScenarioOption): PlannedStep[] {
  return option.plan.map((step, i) => ({
    index: typeof step.index === "number" ? step.index : i + 1,
    action: typeof step.action === "string" ? step.action : "",
    effect: typeof step.effect === "string" ? step.effect : null,
    decision: typeof step.decision === "string" ? step.decision : "deny",
    endpoint:
      typeof step.endpoint === "object" && step.endpoint !== null && !Array.isArray(step.endpoint)
        ? (step.endpoint as Record<string, unknown>)
        : {},
  }));
}

/** "option o3 cannot be picked: step 1 (…): draft action…" → "Cannot be picked: step 1 (…): …". */
function refusalLine(option: ScenarioOption): string | null {
  if (option.pickable || !option.refusal) return null;
  const prefix = `option ${option.option_id} cannot be picked: `;
  const reason = option.refusal.startsWith(prefix)
    ? option.refusal.slice(prefix.length)
    : option.refusal;
  const changed = /^the plan of step (\d+) \(([^)]+)\) changed since it was shown/.exec(reason);
  if (changed) {
    return `Cannot be picked: the plan of step ${changed[1] ?? ""} (${changed[2] ?? ""}) changed since it was shown. Ask the agent for a new proposal in the chat.`;
  }
  if (reason.startsWith("the investigation is answered")) {
    return "The investigation is answered; its options can no longer be picked.";
  }
  if (reason.startsWith("hub.local.json cannot be read")) {
    return `${sentence(reason)} Run ./hub doctor to see the problem.`;
  }
  return `Cannot be picked: ${/[.!?]$/.test(reason) ? reason : `${reason}.`}`;
}

function LimitsList({ environment, pack }: { environment: string; pack: string }) {
  const [open, setOpen] = useState(() => readStored(LIMITS_KEY) !== "closed");
  return (
    <details
      open={open}
      onToggle={(event) => {
        const next = event.currentTarget.open;
        setOpen(next);
        writeStored(LIMITS_KEY, next ? "open" : "closed");
      }}
    >
      <summary className="ah-small" style={{ cursor: "pointer" }}>
        What the agent can do
      </summary>
      <ul className="ah-small ah-muted" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        <li>Read the hub and its declared repos.</li>
        <li>Run read actions in {environment}.</li>
        <li>Write draft actions in actions/{pack}/.</li>
        <li>It cannot run writes or destroys, read env files, or reach other folders.</li>
        <li>Each file write and ./hub command it is allowed still asks you here.</li>
        <li>These limits hold its tools; they are not a sandbox.</li>
      </ul>
    </details>
  );
}

function sessionProblem(
  error: ApiProblem,
  run: ScenarioRunDetail,
): {
  title: string;
  detail?: string;
  command?: string;
} {
  if (error.status === 404 && error.type === "urn:agent-hub:problem:run-control-off") {
    return {
      title: "This scenario run cannot be answered from the agent-hub container",
      detail:
        "Run hub web on your machine to talk with the agent and decide, or answer from a terminal:",
      command: `./hub workflow respond ${run.run_id} --node ${run.paused_step ?? "<step>"}__investigation --choice retry`,
    };
  }
  if (error.type.endsWith("restriction-unavailable")) {
    return {
      title: "The investigation session cannot be reopened with its limits, so it stays closed.",
      detail: "Answer from the options, or ask again with Retry.",
    };
  }
  if (error.code === "workspace_root") {
    return {
      title:
        "No investigation session: the hub or a declared repo sits at / or your home folder, where its reads would reach your own credentials. Move it into a folder of its own.",
    };
  }
  if (error.code === "hub_local_invalid") {
    return {
      title:
        "hub.local.json cannot be read or conflicts with hub.json, so no session starts. Run ./hub doctor, fix the file, then reload.",
    };
  }
  if (error.code === "hub_registry_unreadable") {
    return {
      title: "The hub registry cannot be read, so no session starts. Check Settings › Hubs.",
    };
  }
  const unavailable = sessionControlUnavailable(error, null);
  if (unavailable) return unavailable;
  if (error.status === 429)
    return { title: "Sessions cannot start here", detail: error.detail ?? "" };
  return {
    title: "Could not start the investigation session",
    detail: error.detail ?? error.title,
  };
}

/** The chat: started (or rejoined) once per investigation on load; started again when gone. */
function InvestigationChat({ run, number }: { run: ScenarioRunDetail; number: number }) {
  const open = useOpenInvestigation(run.run_id);
  const asked = useRef<number | null>(null);
  const { mutate } = open;
  useEffect(() => {
    if (asked.current === number) return;
    asked.current = number;
    mutate();
  }, [number, mutate]);
  const session = open.data;
  let body: ReactNode;
  if (open.isError) {
    const problem = sessionProblem(open.error, run);
    body = (
      <div role="status" className="ah-stack" style={{ gap: 4, padding: 12 }}>
        <b style={{ fontWeight: 600 }}>{problem.title}</b>
        {problem.detail && <span className="ah-small ah-muted">{problem.detail}</span>}
        {problem.command && <CodeBlock code={problem.command} />}
      </div>
    );
  } else if (session === undefined) {
    body = (
      <div style={{ padding: 12 }} className="ah-stack">
        <span className="ah-small">Starting the investigation session…</span>
        <Skeleton lines={4} />
      </div>
    );
  } else {
    body = (
      <>
        {session.started && (
          <span className="ah-small ah-muted">
            Opening this page started the session. It reads code and runs read actions, and it costs
            tokens.
          </span>
        )}
        <DiscussChat
          agentSessionId={session.agent_session_id}
          lockMode
          onGone={() => {
            mutate();
          }}
        />
      </>
    );
  }
  return (
    <section
      aria-label="Investigation chat"
      className="ah-card ah-card-body ah-stack"
      style={{ gap: 8, minHeight: 480, minWidth: 0 }}
    >
      <h2 className="ah-h3" style={{ margin: 0 }}>
        Investigation chat
      </h2>
      <span className="ah-small ah-muted">Investigation {number} · read-only agent</span>
      <LimitsList environment={run.environment ?? "—"} pack={run.pack ?? "<pack>"} />
      {body}
    </section>
  );
}

function OptionPlan({ option, environment }: { option: ScenarioOption; environment: string }) {
  return (
    <DataTable
      caption={`Plan of option ${option.option_id}`}
      density="compact"
      rows={plannedSteps(option)}
      rowKey={(step) => String(step.index)}
      columns={[
        {
          id: "step",
          label: "Step",
          render: (step) => <span className="ah-mono ah-small">{step.action}</span>,
        },
        { id: "effect", label: "Effect", render: (step) => <EffectBadge effect={step.effect} /> },
        {
          id: "where",
          label: "Where",
          render: (step) => <WhereText endpoints={step.endpoint} environment={environment} />,
        },
        {
          id: "policy",
          label: "Policy",
          render: (step) => <PolicyBadge decision={step.decision} asksTooltip={ASKS_IN_OPTION} />,
        },
      ]}
    />
  );
}

type Asking = { kind: "pick"; option: ScenarioOption } | { kind: "retry" } | { kind: "stop" };

function answerDone(answer: Answer, step: string): string {
  if (answer.choice === "pick") {
    return `Answer recorded: option ${answer.option ?? ""} picked. The scenario run resumes; its events update this page.`;
  }
  if (answer.choice === "retry") return `Answer recorded: ${step} runs again.`;
  return "Answer recorded: the scenario run is stopping.";
}

function ResumeButton({ runId }: { runId: string }) {
  const resume = useMutation<unknown, ApiProblem>({
    mutationFn: () =>
      apiCommand("/api/v1/workflow-runs/{run_id}/resume", { path: { run_id: runId } }),
  });
  return (
    <span className="ah-row" style={{ gap: 8 }}>
      <Button
        size="sm"
        icon="rotate-ccw"
        disabled={resume.isPending || resume.isSuccess}
        onClick={() => {
          resume.mutate();
        }}
      >
        Resume scenario run
      </Button>
      {resume.isSuccess && (
        <span role="status">
          Resume sent. The scenario run resumes; its events update this page.
        </span>
      )}
      {resume.isError && <span role="alert">{resume.error.detail ?? resume.error.title}</span>}
    </span>
  );
}

function AnswerProblem({
  error,
  answer,
  run,
  gate,
}: {
  error: ApiProblem;
  answer: Answer;
  run: ScenarioRunDetail;
  gate: string;
}) {
  let title = "The answer was refused";
  let lines: ReactNode[] = [error.detail ?? error.title, "Nothing was recorded."];
  if (error.code === "pick_refused") {
    title = `Option ${answer.option ?? ""} was not picked`;
  } else if (error.code === "not_paused") {
    title = "This investigation is no longer open";
    lines = ["It was answered or closed elsewhere. The page now shows where the scenario run is."];
  } else if (error.code === "in_use") {
    title = "The scenario run's process is still running";
    lines = ["Wait for it to pause, then answer again. Nothing was recorded."];
  } else if (error.type.endsWith("decision-unknown")) {
    title = "The answer may have been recorded";
    lines = [
      "hub workflow decide did not finish in 60 s. Reload to see the scenario run's state before you answer again.",
    ];
  } else if (error.type.endsWith("resume-failed")) {
    title = "Your answer is recorded, but the scenario run did not resume";
    lines = [<ResumeButton key="resume" runId={run.run_id} />];
  } else if (error.status === 502 || error.status === 0) {
    title = "Could not record the answer";
    const text = answer.option ? ` --text ${answer.option}` : "";
    lines = [
      "hub web could not start hub workflow decide. Answer from a terminal:",
      <CodeBlock
        key="cmd"
        code={`./hub workflow respond ${run.run_id} --node ${gate} --choice ${answer.choice}${text}`}
      />,
    ];
  }
  return (
    <div
      role="alert"
      className="ah-stack"
      style={{
        gap: 2,
        border: "1px solid var(--failed)",
        borderLeft: "3px solid var(--failed)",
        borderRadius: "var(--radius-md)",
        padding: "8px 12px",
      }}
    >
      <b style={{ fontWeight: 600 }}>{title}</b>
      {lines.map((line, i) => (
        <span key={i} className="ah-small">
          {line}
        </span>
      ))}
    </div>
  );
}

function OptionsColumn({
  run,
  step,
  gate,
  controlOff,
  onRefetch,
  children,
}: {
  run: ScenarioRunDetail;
  step: string;
  gate: string;
  controlOff: boolean;
  onRefetch: () => void;
  children?: ReactNode;
}) {
  const [params, setParams] = useSearchParams();
  const selected = params.get("option");
  const answer = useAnswerInvestigation(run.run_id);
  const [asking, setAsking] = useState<Asking | null>(null);
  const environment = run.environment ?? "—";
  const options = run.proposal?.options ?? [];
  const chosen = options.find((option) => option.option_id === selected && option.pickable);
  const number = run.open_investigation ?? 1;
  const select = (id: string) => {
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        copy.set("option", id);
        return copy;
      },
      { replace: true },
    );
  };
  const send = (body: Answer) => {
    setAsking(null);
    answer.mutate(body, {
      onError: (error) => {
        if (error.code === "pick_refused") onRefetch();
      },
    });
  };
  const busy = answer.isPending || controlOff || answer.isSuccess;
  return (
    <section
      aria-label="Options from the agent"
      className="ah-card ah-card-body ah-stack"
      style={{ gap: 10, minWidth: 0 }}
    >
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <h2 id="options-title" className="ah-h3" style={{ margin: 0 }}>
          Options from the agent
        </h2>
        {run.proposal && (
          <span className="ah-small ah-muted">proposal {run.proposal.proposal}</span>
        )}
        <ProvenanceBadge provenance="agent" />
      </div>
      {options.length === 0 ? (
        <span className="ah-small ah-muted">
          No options yet. The agent is investigating; its findings and options appear here when it
          records them.
        </span>
      ) : (
        <>
          <span className="ah-small ah-muted">
            Pick one, retry the step, or stop. Nothing runs before you decide.
          </span>
          <div
            role="radiogroup"
            aria-labelledby="options-title"
            className="ah-options ah-stack"
            style={{ gap: 10 }}
          >
            {options.map((option) => {
              const refusal = refusalLine(option);
              return (
                <div key={option.option_id} className="ah-stack" style={{ gap: 6 }}>
                  <OptionRow
                    type="radio"
                    name="scenario-option"
                    label={`${option.option_id} · ${option.summary}`}
                    description={refusal}
                    checked={selected === option.option_id}
                    disabled={!option.pickable}
                    onToggle={() => {
                      select(option.option_id);
                    }}
                  />
                  <OptionPlan option={option} environment={environment} />
                  {option.needs_acceptance && option.accept_commands.length > 0 && (
                    <DraftLine
                      commands={option.accept_commands}
                      action={
                        plannedSteps(option).find((s) => s.decision === "deny")?.action ??
                        option.option_id
                      }
                      then="check again"
                    >
                      <Button size="sm" icon="refresh-cw" onClick={onRefetch}>
                        Check again
                      </Button>
                    </DraftLine>
                  )}
                </div>
              );
            })}
          </div>
          <span className="ah-small ah-subtle">
            Want other options? Ask in the chat; a new proposal replaces these.
          </span>
        </>
      )}
      <div
        className="ah-row ah-wrap"
        style={{
          gap: 8,
          position: "sticky",
          bottom: 0,
          background: "var(--surface)",
          paddingTop: 8,
        }}
      >
        <Button
          variant="primary"
          disabled={busy || chosen === undefined}
          onClick={() => {
            if (chosen) setAsking({ kind: "pick", option: chosen });
          }}
        >
          {chosen ? `Pick option ${chosen.option_id}` : "Pick an option"}
        </Button>
        <Button
          disabled={busy}
          onClick={() => {
            setAsking({ kind: "retry" });
          }}
        >
          Retry {step}
        </Button>
        <Button
          variant="danger"
          disabled={busy}
          onClick={() => {
            setAsking({ kind: "stop" });
          }}
        >
          Stop scenario run
        </Button>
      </div>
      {answer.isPending && (
        <span role="status" className="ah-small">
          Recording your answer and resuming the scenario run…
        </span>
      )}
      {answer.isSuccess && (
        <span role="status" className="ah-small">
          {answerDone(answer.variables, step)}
        </span>
      )}
      {answer.isError && (
        <AnswerProblem error={answer.error} answer={answer.variables} run={run} gate={gate} />
      )}
      {asking?.kind === "pick" && (
        <ConfirmDialog
          title={`Pick option ${asking.option.option_id} and run it in ${environment}?`}
          confirmLabel={`Pick option ${asking.option.option_id}`}
          cancelLabel="Back to options"
          tone="primary"
          onCancel={() => {
            setAsking(null);
          }}
          onConfirm={() => {
            send({ choice: "pick", option: asking.option.option_id });
          }}
        >
          {pickBody(asking.option, environment, step)}
        </ConfirmDialog>
      )}
      {asking?.kind === "retry" && (
        <ConfirmDialog
          title={`Retry ${step} in ${environment}?`}
          confirmLabel={`Retry ${step}`}
          cancelLabel="Back to options"
          tone="primary"
          onCancel={() => {
            setAsking(null);
          }}
          onConfirm={() => {
            send({ choice: "retry" });
          }}
        >
          It runs the step again as it is, with no workaround. If it diverges again, a new
          investigation opens ({Math.min(number + 1, MAX_INVESTIGATIONS)} of at most{" "}
          {MAX_INVESTIGATIONS}).
        </ConfirmDialog>
      )}
      {asking?.kind === "stop" && (
        <ConfirmDialog
          title="Stop this scenario run?"
          confirmLabel="Stop scenario run"
          cancelLabel="Keep scenario run"
          tone="danger"
          onCancel={() => {
            setAsking(null);
          }}
          onConfirm={() => {
            send({ choice: "stop" });
          }}
        >
          It ends cancelled. Its findings are kept, nothing is rewound, and it cannot be resumed.
        </ConfirmDialog>
      )}
      {children}
    </section>
  );
}

function pickBody(option: ScenarioOption, environment: string, step: string): string {
  const steps = plannedSteps(option);
  const list = steps.map((s) => `${s.action}${s.effect ? ` (${s.effect})` : ""}`).join(", ");
  const n = steps.length;
  return `Its ${String(n)} ${n === 1 ? "step runs" : "steps run"} in ${environment} as a workaround by the agent: ${list}. Picking it is your approval of ${n === 1 ? "that step" : "those steps"}. Then ${step} runs again. Nothing is rewound.`;
}

/** The paused view's two columns: the chat, then the options and the answer bar. */
export function PausedView({
  run,
  controlOff,
  onRefetch,
  findings,
}: {
  run: ScenarioRunDetail;
  controlOff: boolean;
  onRefetch: () => void;
  findings: ReactNode;
}) {
  const number = run.open_investigation ?? 1;
  const step = run.paused_step ?? "";
  const gate = run.investigations.find((item) => item.number === number)?.gate ?? step;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) minmax(0, 480px)",
        gap: 16,
        alignItems: "start",
      }}
    >
      {controlOff ? (
        <section aria-label="Investigation chat" className="ah-card ah-card-body">
          <span className="ah-small ah-muted">The chat needs hub web on your machine.</span>
        </section>
      ) : (
        <InvestigationChat run={run} number={number} />
      )}
      <OptionsColumn
        run={run}
        step={step}
        gate={gate}
        controlOff={controlOff}
        onRefetch={onRefetch}
      >
        {findings}
      </OptionsColumn>
    </div>
  );
}
