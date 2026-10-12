import type { ReactNode } from "react";

import { cx } from "../lib/cx";
import { fmtDuration, fmtMoney } from "../lib/format";
import { Tooltip } from "./core";
import { Icon, type IconName } from "./Icon";

/* ---------- Status badge: icon + label, never color alone ---------- */
export type Status =
  | "live"
  | "waiting"
  | "done"
  | "failed"
  | "error"
  | "blocked"
  | "stopped"
  | "idle"
  | "stale"
  | "ended"
  | "guard"
  | "running"
  | "queued"
  | "passed"
  | "merged";

interface StatusLook {
  icon: IconName | null;
  label: string;
  tone?: Status;
}

export const STATUS: Record<Status, StatusLook> = {
  live: { icon: null, label: "Live" },
  waiting: { icon: "hand", label: "Waiting for you" },
  done: { icon: "circle-check", label: "Done" },
  failed: { icon: "circle-x", label: "Failed" },
  error: { icon: "circle-x", label: "Error", tone: "failed" },
  blocked: { icon: "octagon-x", label: "Blocked" },
  stopped: { icon: "octagon-x", label: "Stopped", tone: "blocked" },
  idle: { icon: "moon", label: "Idle" },
  stale: { icon: "clock", label: "Stale" },
  ended: { icon: "circle-stop", label: "Ended" },
  guard: { icon: "shield-x", label: "Denied by guard" },
  running: { icon: null, label: "Running", tone: "live" },
  queued: { icon: "circle-dashed", label: "Queued", tone: "idle" },
  passed: { icon: "circle-check", label: "Passed", tone: "done" },
  merged: { icon: "git-merge", label: "Merged", tone: "done" },
};

export interface StatusBadgeProps {
  status: Status;
  label?: string | undefined;
  quiet?: boolean | undefined;
  /** No end event was received: the status is deduced (D14). */
  inferred?: boolean | undefined;
  title?: string | undefined;
}
export function StatusBadge({ status, label, quiet, inferred, title }: StatusBadgeProps) {
  const look = STATUS[status];
  const tone = look.tone ?? status;
  const text = label ?? look.label;
  const live = status === "live" || status === "running";
  return (
    <span
      className={cx(
        "ah-badge",
        `ah-badge-${tone}`,
        quiet && "ah-badge-quiet",
        inferred && "ah-badge-inferred",
      )}
      title={title ?? (inferred ? `${text} (inferred: no end event received)` : undefined)}
    >
      {live || look.icon === null ? (
        <span className="ah-dot ah-pulse" aria-hidden="true" />
      ) : (
        <Icon name={look.icon} />
      )}
      {text}
      {inferred && " · inferred"}
    </span>
  );
}

/* ---------- Stages of a WorkflowRun ---------- */
export type Stage = "PICKED" | "WORKTREE" | "IMPLEMENTING" | "VERIFYING" | "PR_OPEN" | "REPORTED";

export const STAGES: readonly { id: Stage; label: string }[] = [
  { id: "PICKED", label: "Picked" },
  { id: "WORKTREE", label: "Worktree" },
  { id: "IMPLEMENTING", label: "Implementing" },
  { id: "VERIFYING", label: "Verifying" },
  { id: "PR_OPEN", label: "PR open" },
  { id: "REPORTED", label: "Reported" },
];

function stageLabel(stage: string): string {
  return STAGES.find((s) => s.id === stage)?.label ?? stage;
}

export interface StageChipProps {
  stage: Stage;
  state?: "active" | "done" | "waiting" | "pending";
  failed?: boolean | undefined;
}
export function StageChip({ stage, state = "active", failed }: StageChipProps) {
  const label = failed ? `Failed · ${stageLabel(stage)}` : stageLabel(stage);
  const icon: IconName | null = failed
    ? "circle-x"
    : state === "done"
      ? "check"
      : state === "waiting"
        ? "hand"
        : null;
  return (
    <span className={cx("ah-stage", `ah-stage-${failed ? "failed" : state}`)}>
      {icon ? (
        <Icon name={icon} />
      ) : state === "active" ? (
        <span className="ah-dot" aria-hidden="true" style={{ width: 6, height: 6 }} />
      ) : null}
      {label}
    </span>
  );
}

export type PipelineState = "done" | "active" | "failed" | "waiting" | "pending";
export interface PipelineStep {
  id: string;
  label: string;
  state: PipelineState;
  /** Seconds. */
  duration?: number | undefined;
  attempts?: number | undefined;
  attempt?: number | undefined;
  maxAttempts?: number | undefined;
  loop?: string | undefined;
  note?: string | undefined;
}
const PIPE_ICON: Record<PipelineState, IconName> = {
  done: "circle-check",
  active: "loader",
  failed: "circle-x",
  waiting: "hand",
  pending: "circle-dashed",
};

function attemptText(step: PipelineStep): string {
  const attempts = step.attempts ?? 0;
  if (attempts <= 1 && !step.attempt) return "";
  const shown = step.attempt ?? attempts;
  const of = step.maxAttempts ?? (attempts || shown);
  return ` · attempt ${String(shown)} of ${String(of)}`;
}

export interface StagePipelineProps {
  steps: PipelineStep[];
  onSelect?: ((id: string) => void) | undefined;
  selected?: string | undefined;
}
export function StagePipeline({ steps, onSelect, selected }: StagePipelineProps) {
  return (
    <div className="ah-pipe" role="list" aria-label="Run stages">
      {steps.map((step) => {
        const content = (
          <>
            <div className="ah-pipe-step-head">
              <Icon name={PIPE_ICON[step.state]} />
              <span>{step.label}</span>
            </div>
            <div className="ah-pipe-step-meta">
              {step.state === "pending" ? "not started" : fmtDuration(step.duration)}
              {attemptText(step)}
            </div>
            {step.loop && (
              <div className="ah-pipe-loop">
                <Icon name="rotate-ccw" size="sm" />
                {step.loop}
              </div>
            )}
            {step.note && (
              <div
                className="ah-small"
                style={{ color: step.state === "failed" ? "var(--failed)" : "var(--text-muted)" }}
              >
                {step.note}
              </div>
            )}
          </>
        );
        return (
          <div
            key={step.id}
            role="listitem"
            className="ah-pipe-step"
            data-state={step.state}
            aria-current={selected === step.id || undefined}
          >
            {onSelect ? (
              <button
                type="button"
                className="ah-pipe-select"
                onClick={() => {
                  onSelect(step.id);
                }}
              >
                {content}
              </button>
            ) : (
              content
            )}
          </div>
        );
      })}
    </div>
  );
}

function positive(n: number | undefined): number | undefined {
  return n !== undefined && n > 0 ? n : undefined;
}

/** Runs in progress per stage, e.g. `{IMPLEMENTING: 1, PR_OPEN: 1}`. */
export interface MiniStageBarProps {
  counts?: Partial<Record<Stage, number>>;
  failed?: number;
  waiting?: Stage | undefined;
}
export function MiniStageBar({ counts = {}, failed = 0, waiting }: MiniStageBarProps) {
  const label =
    STAGES.map((s) => (counts[s.id] ? `${String(counts[s.id])} ${s.label.toLowerCase()}` : null))
      .filter(Boolean)
      .join(", ") || "No runs in progress";
  return (
    <Tooltip block label={label + (failed ? `; ${String(failed)} failed` : "")}>
      <span className="ah-ministage" role="img" aria-label={`Runs in progress: ${label}`}>
        {STAGES.map((s) => (
          <span
            key={s.id}
            data-n={positive(counts[s.id])}
            data-waiting={waiting === s.id ? "" : undefined}
          />
        ))}
        <span data-failed={failed ? "" : undefined} title="Failed" style={{ flex: "0 0 6px" }} />
      </span>
    </Tooltip>
  );
}

/* ---------- Progress against budget: amber at 80 %, red at 100 % ---------- */
export interface BudgetBarProps {
  spent: number;
  budget: number;
  label?: string;
  projection?: string | undefined;
}
export function BudgetBar({ spent, budget, label = "Budget", projection }: BudgetBarProps) {
  const pct = budget ? spent / budget : 0;
  const level = pct >= 1 ? "over" : pct >= 0.8 ? "warn" : "ok";
  return (
    <div
      className="ah-budget"
      data-level={level}
      title={`${fmtMoney(spent, 4)} of ${fmtMoney(budget)} (${String(Math.round(pct * 100))} %)`}
    >
      <div className="ah-budget-label">
        <span>{label}</span>
        <span>
          <b>{fmtMoney(spent)}</b> / {fmtMoney(budget)}
        </span>
      </div>
      <div
        className="ah-budget-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={budget}
        aria-valuenow={spent}
        aria-label={`${label}: ${fmtMoney(spent)} of ${fmtMoney(budget)}`}
      >
        <div className="ah-budget-fill" style={{ width: `${String(Math.min(100, pct * 100))}%` }} />
      </div>
      {projection && (
        <div
          className="ah-budget-label"
          style={{ color: level === "ok" ? undefined : "var(--waiting)" }}
        >
          <span>{projection}</span>
        </div>
      )}
    </div>
  );
}

/* ---------- Trust labels ---------- */

/**
 * A value removed by redaction before storage. It has no reveal control: the value never
 * reached agent-hub (AC-200.46).
 */
export function RedactionChip({ kind = "secret" }: { kind?: string }) {
  return (
    <Tooltip
      label={`A ${kind} was removed before storage. The value never reached agent-hub and cannot be revealed.`}
    >
      {/* Focusable so keyboard users reach the explanation in its tooltip. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <span className="ah-redacted" tabIndex={0} role="note" aria-label={`Redacted ${kind}`}>
        <Icon name="eye-off" />
        [redacted: {kind}]
      </span>
    </Tooltip>
  );
}

export interface DerivedLabelProps {
  children?: ReactNode;
  how?: string | undefined;
}
export function DerivedLabel({ children = "Derived", how }: DerivedLabelProps) {
  return (
    <Tooltip label={how ?? "Computed by agent-hub from recorded events; not recorded directly."}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <span className="ah-derived" tabIndex={0}>
        <Icon name="circle-dashed" />
        {children}
      </span>
    </Tooltip>
  );
}

export type Provenance = "human" | "agent" | "agent-from-code" | "agent-from-external";
const PROV: Record<Provenance, { icon: IconName; tip: string }> = {
  human: { icon: "user", tip: "Written by a person." },
  agent: { icon: "cpu", tip: "Proposed by an agent from its own session." },
  "agent-from-code": { icon: "braces", tip: "Written by an agent from reading the code." },
  "agent-from-external": {
    icon: "triangle-alert",
    tip: "Written by an agent from outside content (web, issue, PR comment). Verify before accepting.",
  },
};
export function ProvenanceBadge({ provenance }: { provenance: Provenance }) {
  const look = PROV[provenance];
  return (
    <Tooltip label={look.tip}>
      <span
        // Focusable so keyboard users reach the explanation in its tooltip.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
        className={cx("ah-prov", provenance === "agent-from-external" && "ah-prov-external")}
      >
        <Icon name={look.icon} />
        {provenance}
      </span>
    </Tooltip>
  );
}

export function ExternalLabel({ source = "External content" }: { source?: string }) {
  return (
    <span className="ah-external">
      <Icon name="globe" />
      {source} · not verified
    </span>
  );
}

export interface ExpiredContentProps {
  date: string;
  what?: string;
}
export function ExpiredContent({ date, what = "Content" }: ExpiredContentProps) {
  return (
    <div className="ah-expired" role="note">
      <Icon name="clock" />
      <div>
        <b style={{ color: "var(--text)", fontWeight: 500 }}>
          {what} expired {date}.
        </b>{" "}
        The raw transcript was deleted by the retention policy. The summary and structured events
        remain.
      </div>
    </div>
  );
}

export interface AsOfStampProps {
  /** Clock time of the data shown, e.g. "14:02". */
  time: string;
  stale?: boolean | undefined;
  source?: string | undefined;
}
export function AsOfStamp({ time, stale, source }: AsOfStampProps) {
  return (
    <span
      className={cx("ah-asof", !stale && "ah-asof-fresh")}
      title={source ? `Last update from ${source}` : undefined}
    >
      <Icon name={stale ? "clock" : "refresh-cw"} />
      {stale ? `Stale · as of ${time}` : `Updated ${time}`}
    </span>
  );
}
