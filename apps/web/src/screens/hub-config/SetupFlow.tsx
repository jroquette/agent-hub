import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Button, Icon } from "../../components";
import { cx } from "../../lib/cx";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import type { FlowOrigin } from "./environments";

/* A setup flow: one question at a time, the steps on the left with what was answered, a live
   preview of the result on the right. The step circles mirror the first-run screen's. */

export interface FlowStep {
  title: string;
  /** What the person answered, shown under a done step. */
  summary?: ReactNode;
}

export interface SetupFlowProps {
  project: string;
  /** The page the flow was opened from: Cancel and the breadcrumb lead back there. */
  origin: FlowOrigin;
  /** The page title and the last breadcrumb, e.g. "Add environment". */
  title: string;
  intro: ReactNode;
  steps: readonly FlowStep[];
  index: number;
  onIndex: (index: number) => void;
  /** The current step's question, its help line and its answers. */
  question: ReactNode;
  help?: ReactNode;
  children: ReactNode;
  /** Whether the current answers let the person go on; else ``blocked`` says why. */
  canContinue: boolean;
  blocked?: string | undefined;
  nextLabel?: string;
  onFinish: () => void;
  finishLabel: string;
  pending?: boolean;
  /** A failed save, in words. */
  failure?: string | null;
  preview?: ReactNode;
}

export function SetupFlow({
  project,
  origin,
  title,
  intro,
  steps,
  index,
  onIndex,
  question,
  help,
  children,
  canContinue,
  blocked,
  nextLabel = "Continue",
  onFinish,
  finishLabel,
  pending = false,
  failure,
  preview,
}: SetupFlowProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const last = index === steps.length - 1;
  const back = origin.returnTo;

  useEffect(() => {
    heading.current?.focus();
  }, [index]);

  const next = () => {
    if (!canContinue || pending) return;
    if (last) onFinish();
    else onIndex(index + 1);
  };

  return (
    <div className="ah-page ah-flow" style={{ gap: 16 }}>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: project, href: `/projects/${encodeURIComponent(project)}` },
          { label: origin.returnLabel, href: back },
          { label: title },
        ]}
      />
      <header className="ah-stack" style={{ gap: 4 }}>
        <h1 className="ah-h1">{title}</h1>
        <p className="ah-muted" style={{ margin: 0 }}>
          {intro}
        </p>
      </header>

      <div className="ah-flow-layout">
        <ol className="ah-flow-steps" aria-label="Steps">
          {steps.map((step, position) => {
            const state = position < index ? "done" : position === index ? "open" : "future";
            const label = (
              <>
                <span className="ah-flow-dot" data-state={state} aria-hidden="true">
                  {state === "done" ? <Icon name="check" /> : position + 1}
                </span>
                <span className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
                  <span className="ah-flow-step-title">{step.title}</span>
                  {state === "done" && step.summary && (
                    <span className="ah-small ah-muted ah-flow-step-summary">{step.summary}</span>
                  )}
                </span>
              </>
            );
            return (
              <li
                key={step.title}
                className="ah-flow-step"
                data-state={state}
                aria-current={state === "open" ? "step" : undefined}
              >
                {state === "done" ? (
                  <button
                    type="button"
                    className="ah-flow-step-button"
                    aria-label={`Back to step ${String(position + 1)}: ${step.title}`}
                    onClick={() => {
                      onIndex(position);
                    }}
                  >
                    {label}
                  </button>
                ) : (
                  <div className="ah-flow-step-button">{label}</div>
                )}
              </li>
            );
          })}
        </ol>

        <form
          className="ah-card ah-flow-card"
          aria-labelledby="ah-flow-question"
          onSubmit={(event) => {
            event.preventDefault();
            next();
          }}
        >
          <div className="ah-small ah-muted">
            Step {index + 1} of {steps.length}
          </div>
          <h2 id="ah-flow-question" className="ah-h2 ah-flow-question" tabIndex={-1} ref={heading}>
            {question}
          </h2>
          {help && <p className="ah-muted ah-flow-help">{help}</p>}
          <div className="ah-flow-body">{children}</div>
          {failure && (
            <p role="alert" className="ah-config-error">
              {failure}
            </p>
          )}
          <footer className="ah-flow-footer">
            {index > 0 ? (
              <Button
                icon="chevron-left"
                disabled={pending}
                onClick={() => {
                  onIndex(index - 1);
                }}
              >
                Back
              </Button>
            ) : (
              <span />
            )}
            <span className="ah-grow" />
            {!canContinue && blocked && <span className="ah-small ah-muted">{blocked}</span>}
            <Link to={back} className="ah-btn ah-btn-ghost">
              Cancel
            </Link>
            <Button
              type="submit"
              variant="primary"
              disabled={!canContinue || pending}
              className={cx(last && "ah-flow-finish")}
            >
              {pending ? "Saving…" : last ? finishLabel : nextLabel}
            </Button>
          </footer>
        </form>

        {preview && (
          <aside className="ah-card ah-flow-preview" aria-label="What agents will read">
            <div className="ah-flow-preview-title">
              <Icon name="scan-eye" /> What agents will read
            </div>
            {preview}
          </aside>
        )}
      </div>
    </div>
  );
}

/** A big choice tile: icon, label and one line; a radio underneath for keyboards and readers. */
export function ChoiceTile({
  name,
  icon,
  label,
  hint,
  checked,
  onPick,
}: {
  name: string;
  icon: Parameters<typeof Icon>[0]["name"];
  label: string;
  hint: ReactNode;
  checked: boolean;
  onPick: () => void;
}) {
  return (
    <label className={cx("ah-flow-tile", checked && "ah-flow-tile-checked")}>
      <input
        type="radio"
        name={name}
        className="ah-flow-tile-input"
        checked={checked}
        onChange={onPick}
      />
      <span className="ah-flow-tile-icon">
        <Icon name={icon} />
      </span>
      <span className="ah-flow-tile-label">{label}</span>
      <span className="ah-small ah-muted">{hint}</span>
    </label>
  );
}
