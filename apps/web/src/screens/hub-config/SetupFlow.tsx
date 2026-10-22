import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";

import { Button, ConfirmDialog, Icon } from "../../components";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import type { FlowOrigin } from "./environments";

/* A setup flow: one question at a time in a card of fixed width, the steps on the left with what
   was answered, a live preview of the result on the right. The step circles mirror the first-run
   screen's. Every choice is a one-column list of OptionRows, so no count of answers leaves a gap. */

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
  /** What is being made, for the discard question: "environment" or "service". */
  noun: string;
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
  /** Where the preview's line lands, e.g. "In AGENTS.md". */
  previewWhere?: string;
  preview?: ReactNode;
}

export function SetupFlow({
  project,
  origin,
  title,
  intro,
  noun,
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
  previewWhere,
  preview,
}: SetupFlowProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const navigate = useNavigate();
  const [discarding, setDiscarding] = useState(false);
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
  // Past the first step there are answers to lose: ask before leaving.
  const cancel = () => {
    if (index === 0) void navigate(back);
    else setDiscarding(true);
  };

  return (
    <div className="ah-page ah-setup" style={{ gap: 16 }}>
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

      <div className="ah-setup-layout">
        <ol className="ah-setup-steps" aria-label="Steps">
          {steps.map((step, position) => {
            const state = position < index ? "done" : position === index ? "open" : "future";
            const label = (
              <>
                <span className="ah-setup-dot" data-state={state} aria-hidden="true">
                  {state === "done" ? <Icon name="check" /> : position + 1}
                </span>
                <span className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
                  <span className="ah-setup-step-title">{step.title}</span>
                  {state === "done" && step.summary && (
                    <span className="ah-small ah-muted ah-setup-step-summary">{step.summary}</span>
                  )}
                </span>
              </>
            );
            return (
              <li
                key={step.title}
                className="ah-setup-step"
                data-state={state}
                aria-current={state === "open" ? "step" : undefined}
              >
                {state === "done" ? (
                  <button
                    type="button"
                    className="ah-setup-step-button"
                    aria-label={`Back to step ${String(position + 1)}: ${step.title}`}
                    onClick={() => {
                      onIndex(position);
                    }}
                  >
                    {label}
                  </button>
                ) : (
                  <div className="ah-setup-step-button">{label}</div>
                )}
              </li>
            );
          })}
        </ol>

        <form
          className="ah-card ah-setup-card"
          aria-labelledby="ah-setup-question"
          onSubmit={(event) => {
            event.preventDefault();
            next();
          }}
        >
          <h2
            id="ah-setup-question"
            className="ah-h2 ah-setup-question"
            tabIndex={-1}
            ref={heading}
          >
            <span className="ah-sr">
              Step {index + 1} of {steps.length}:{" "}
            </span>
            {question}
          </h2>
          {help && <p className="ah-muted ah-setup-help">{help}</p>}
          <div className="ah-setup-body">{children}</div>
          {failure && (
            <p role="alert" className="ah-config-error">
              {failure}
            </p>
          )}
          <footer className="ah-setup-footer">
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
            <Button variant="ghost" disabled={pending} onClick={cancel}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={!canContinue || pending}>
              {pending ? "Saving…" : last ? finishLabel : nextLabel}
            </Button>
          </footer>
        </form>

        {preview && (
          <aside className="ah-card ah-setup-preview" aria-label="What agents will read">
            <div className="ah-setup-preview-title">
              <Icon name="scan-eye" /> What agents will read
            </div>
            {previewWhere && <div className="ah-small ah-muted">{previewWhere}</div>}
            {preview}
          </aside>
        )}
      </div>

      {discarding && (
        <ConfirmDialog
          title={`Discard this ${noun}?`}
          confirmLabel="Discard answers"
          cancelLabel="Keep editing"
          consequences={["Your answers are not saved."]}
          onCancel={() => {
            setDiscarding(false);
          }}
          onConfirm={() => {
            void navigate(back);
          }}
        />
      )}
    </div>
  );
}
