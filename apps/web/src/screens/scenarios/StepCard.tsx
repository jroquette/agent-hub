import type { ReactNode } from "react";

import { Button, CopyButton, Icon, PathText } from "../../components";
import { BreakId, DraftLine, EffectBadge, WhereText } from "./parts";
import type {
  ScenarioAction,
  ScenarioMode,
  ScenarioPlan,
  ScenarioPlanRow,
  ScenarioStep,
} from "./queries";
import {
  actionOf,
  givesLine,
  keptLines,
  kindLook,
  pace,
  stopLines,
  valueLines,
  whatItDoes,
  type StopLine,
} from "./story";

/* The storyline of a scenario (scenario detail): one card per step, read in place, saying what
 * the step does, the action and script it runs, the values it passes, what it keeps and every
 * place it can stop. A current plan lays over the same cards (its summary, the endpoint and the
 * decision) instead of a separate table. */

export interface StepStatus {
  node: ReactNode;
}

/** A breakpoint before block `address` (a scenario written as blocks, ADR 0049): a toggle whose
 * name stays the same, its state in `aria-pressed`; Tab reaches it, Space or Enter presses it.
 * While `busy` (a change on its way) a press does nothing, and the toggle keeps focus
 * (`aria-disabled`, not `disabled`). */
export function BreakpointToggle({
  address,
  on,
  busy,
  onToggle,
}: {
  address: string;
  on: boolean;
  busy?: boolean | undefined;
  onToggle: () => void;
}) {
  return (
    <Button
      size="sm"
      variant="ghost"
      icon={on ? "circle-dot" : "circle"}
      className={on ? "sc-break sc-break-on" : "sc-break"}
      aria-pressed={on}
      aria-label={`Breakpoint before block ${address}`}
      title={
        on
          ? `The scenario run pauses before block ${address}. Press to remove the breakpoint.`
          : `Press to pause the scenario run before block ${address}.`
      }
      aria-disabled={busy === true || undefined}
      onClick={() => {
        if (!busy) onToggle();
      }}
    >
      Breakpoint
    </Button>
  );
}

const TONE_COLOR: Readonly<Record<StopLine["tone"], string>> = {
  ok: "var(--done)",
  ask: "var(--waiting)",
  deny: "var(--failed)",
  info: "var(--text-muted)",
};

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="sc-card-section">
      <span className="sc-card-label">{label}</span>
      <div className="ah-stack" style={{ gap: 4, minWidth: 0 }}>
        {children}
      </div>
    </div>
  );
}

function Calls({
  action,
  step,
  row,
  onOpenAction,
}: {
  action: ScenarioAction | null;
  step: ScenarioStep;
  row: ScenarioPlanRow | null;
  onOpenAction: (ref: string) => void;
}) {
  const ref = step.action ?? "";
  return (
    <Section label="Calls">
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <span
          className="ah-row"
          style={{ gap: 6 }}
          title={row ? `Pinned when the scenario run starts: ${row.content_hash}` : undefined}
        >
          <Icon name="circle-play" size="sm" />
          <BreakId id={ref} />
        </span>
        {action?.effect && <EffectBadge effect={action.effect} />}
        {action && !action.problem && (
          <span className="ah-small ah-subtle">{action.draft ? "draft" : "committed"}</span>
        )}
        <span className="ah-grow" />
        {action && !action.problem && (
          <Button
            size="sm"
            variant="ghost"
            icon="book-open"
            aria-label={`Open action ${ref}`}
            onClick={() => {
              onOpenAction(ref);
            }}
          >
            Open action
          </Button>
        )}
      </div>
      {action?.description && <span className="ah-small ah-muted">{action.description}</span>}
      {action?.script && (
        <span className="ah-row ah-small ah-muted" style={{ gap: 6 }}>
          <Icon name="terminal" size="sm" />
          <span>{action.runtime}</span>
          <span aria-hidden>·</span>
          <span className="ah-mono">
            <PathText path={action.script} max={64} dimDir />
          </span>
          <CopyButton text={action.script} label={`Copy the path of ${action.script}`} compact />
        </span>
      )}
      {step.type === "action" && step.timeout && action?.timeout && (
        <span className="ah-small ah-subtle">
          Timeout {pace(step.timeout)} (the action allows {pace(action.timeout)})
        </span>
      )}
      {(() => {
        const command = row?.needs_acceptance
          ? row.accept_command
          : action?.draft
            ? action.accept_command
            : null;
        return command ? (
          <DraftLine commands={[command]} action={row?.action ?? ref} then="plan again" />
        ) : null;
      })()}
    </Section>
  );
}

function Values({
  step,
  action,
  row,
  environment,
}: {
  step: ScenarioStep;
  action: ScenarioAction | null;
  row: ScenarioPlanRow | null;
  environment: string | null;
}) {
  const lines = valueLines(step, action, row?.args ?? null);
  if (lines.length === 0) return null;
  return (
    <Section label="With">
      <dl className="sc-values">
        {lines.map((line) => (
          <div key={line.name} className="sc-value">
            <dt className="ah-mono">{line.name}</dt>
            <dd>
              <span
                className={line.title ? "ah-mono ah-subtle" : line.literal ? "ah-mono" : undefined}
                title={line.title}
              >
                {line.value}
              </span>
              {line.note && <span className="ah-subtle"> ({line.note})</span>}
            </dd>
          </div>
        ))}
      </dl>
      {row && environment && Object.keys(row.endpoints).length > 0 && (
        <span className="ah-small ah-muted ah-row" style={{ gap: 6 }}>
          In {environment}: <WhereText endpoints={row.endpoints} environment={environment} />
        </span>
      )}
    </Section>
  );
}

function Stops({ lines }: { lines: StopLine[] }) {
  if (lines.length === 0) return null;
  return (
    <Section label="Where it can stop">
      <ul className="ah-stack" style={{ gap: 4, margin: 0, padding: 0, listStyle: "none" }}>
        {lines.map((line) => (
          <li
            key={line.key}
            className="ah-row ah-small"
            style={{ gap: 6, alignItems: "flex-start" }}
            title={line.title}
          >
            <Icon
              name={line.icon}
              size="sm"
              style={{ color: TONE_COLOR[line.tone], flex: "none", marginTop: 2 }}
            />
            <span>{line.text}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function ScenarioStepCard({
  step,
  index,
  steps,
  actions,
  mode,
  plan,
  status,
  breakpoint,
  onOpenAction,
}: {
  step: ScenarioStep;
  index: number;
  steps: readonly ScenarioStep[];
  actions: readonly ScenarioAction[];
  mode: ScenarioMode;
  plan: ScenarioPlan | null;
  status?: ReactNode;
  /** The card's breakpoint toggle, beside its status (a scenario written as blocks). */
  breakpoint?: ReactNode;
  onOpenAction: (ref: string) => void;
}) {
  const action = actionOf(step, actions);
  const look = kindLook(step.type);
  const row = plan?.rows.find((item) => item.step === step.id) ?? null;
  const previous = index > 0 ? steps[index - 1] : undefined;
  const afterOthers =
    step.depends_on.length > 0 &&
    !(step.depends_on.length === 1 && step.depends_on[0] === previous?.id);
  const together = step.depends_on.length === 0 && index > 0;
  const kept = keptLines(step, steps);
  const gives = givesLine(action);
  const calls = step.type === "action" || step.type === "expect";
  return (
    <article
      id={`step-${step.id}`}
      className="ah-card sc-card"
      aria-label={`Step ${String(index + 1)}: ${step.id}`}
    >
      <header className="sc-card-head">
        <span className="ah-num ah-subtle sc-card-num">{index + 1}</span>
        <span className="ah-badge ah-badge-quiet">
          <Icon name={look.icon} />
          {look.label}
        </span>
        <h3 className="ah-mono sc-card-title">
          <BreakId id={step.id} />
        </h3>
        {afterOthers && (
          <span className="ah-small ah-subtle">After: {step.depends_on.join(", ")}</span>
        )}
        {together && <span className="ah-small ah-subtle">Starts at the beginning</span>}
        <span className="ah-grow" />
        {status}
        {breakpoint}
      </header>
      <div className="ah-stack" style={{ gap: 2 }}>
        {step.description && <span>{step.description}</span>}
        <span className={step.description ? "ah-muted" : undefined}>
          {whatItDoes(step, action)}
        </span>
        {row && plan && (
          <span className="ah-small">
            <span className="ah-muted">In {plan.environment}: </span>
            {row.plan === "runs with values known at run time"
              ? "runs with values known at run time."
              : row.plan}
          </span>
        )}
        {step.type === "expect" && step.until_when && (
          <span className="ah-small ah-subtle">
            Condition as written: <span className="ah-mono">{step.until_when}</span>
          </span>
        )}
      </div>
      {calls && <Calls action={action} step={step} row={row} onOpenAction={onOpenAction} />}
      {calls && (
        <Values step={step} action={action} row={row} environment={plan?.environment ?? null} />
      )}
      {(gives !== null || kept.length > 0) && (
        <Section label="Gives">
          {gives !== null && <span className="ah-small">{gives}</span>}
          {kept.map((item) => (
            <span key={item.name} className="ah-small">
              Kept for later as <span className="ah-mono">$CTX.{item.name}</span> ={" "}
              <span className="ah-mono">{item.from}</span>
              {item.usedBy.length > 0 && (
                <span className="ah-muted"> · used by {item.usedBy.join(", ")}</span>
              )}
            </span>
          ))}
        </Section>
      )}
      {step.retry && step.retry.max_attempts > 0 && (
        <Section label="Retry">
          <span className="ah-small">
            On {step.retry.on_error === "all" ? "any" : "a transient"} error it tries again up to{" "}
            {step.retry.max_attempts} {step.retry.max_attempts === 1 ? "time" : "times"}, waiting{" "}
            {pace(step.retry.delay)} first, then twice as long each time.
          </span>
        </Section>
      )}
      <Stops
        lines={stopLines(step, action, mode, plan ? { row, environment: plan.environment } : null)}
      />
    </article>
  );
}

/** The steps in document order, a connector saying what each one waits for. */
export function Storyline({
  name,
  steps,
  actions,
  mode,
  plan,
  statusOf,
  breakpointOf,
  onOpenAction,
}: {
  name: string;
  steps: readonly ScenarioStep[];
  actions: readonly ScenarioAction[];
  mode: ScenarioMode;
  plan: ScenarioPlan | null;
  statusOf?: (step: ScenarioStep) => ReactNode;
  breakpointOf?: ((step: ScenarioStep) => ReactNode) | undefined;
  onOpenAction: (ref: string) => void;
}) {
  return (
    <ol className="sc-story" aria-label={`Steps of ${name}`}>
      {steps.map((step, index) => {
        const previous = index > 0 ? steps[index - 1] : undefined;
        const chained =
          previous !== undefined &&
          step.depends_on.length === 1 &&
          step.depends_on[0] === previous.id;
        return (
          <li key={step.id} className="ah-stack" style={{ gap: 0 }}>
            {index > 0 && (
              <div className="sc-connector" aria-hidden={!chained}>
                <Icon name="arrow-down" size="sm" />
                {chained && <span className="ah-small ah-subtle">after {previous.id}</span>}
              </div>
            )}
            <ScenarioStepCard
              step={step}
              index={index}
              steps={steps}
              actions={actions}
              mode={mode}
              plan={plan}
              status={statusOf?.(step)}
              breakpoint={breakpointOf?.(step)}
              onOpenAction={onOpenAction}
            />
          </li>
        );
      })}
    </ol>
  );
}
