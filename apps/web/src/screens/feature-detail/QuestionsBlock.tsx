import { useId, useMemo, useRef, useState } from "react";

import { Button, Icon, Markdown, OptionRow, type IconName } from "../../components";
import { useApi } from "../../lib/api";
import { useBrainNote, useBrainTree } from "../brain/queries";
import {
  openQuestions,
  outcomeOf,
  questionsToShow,
  type Answers,
  type OpenQuestion,
  type Outcome,
} from "./openQuestions";
import { summaryPath, summaryState } from "./RecordSummary";

import "./questions.css";

export const QUESTIONS_ID = "approve-questions";
const MAX_ANSWER_CHARS = 4000;
/** The counter shows from this share of the limit on: below it, it is only noise. */
const COUNT_FROM = 0.8;
const PLACEHOLDER_CHARS = 80;
/** Up to this many questions start open; more start folded (progressive disclosure). */
const OPEN_UP_TO = 3;
/** The radio values of the blank answer (the recommendation or Claude's call) and of "Other". */
const DEFAULT_CHOICE = "\u0000default";
const OTHER_CHOICE = "\u0000other";

const OUTCOME: Record<Outcome, { icon: IconName; label: string }> = {
  answered: { icon: "pencil", label: "Answered" },
  recommended: { icon: "check", label: "Takes the recommendation" },
  claude: { icon: "network", label: "Claude decides" },
};

/** Inline code spans (`…`) of a one-line text as code, the rest as plain text. */
function withCode(text: string) {
  return text
    .split("`")
    .map((part, index) =>
      index % 2 === 1 ? <code key={index}>{part}</code> : <span key={index}>{part}</span>,
    );
}

/** A one-line text cut at `max` characters with an ellipsis. */
function clipLine(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

/** A text on one line, for the folded row's second line. */
function oneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/**
 * A record's open questions as the owner reads them: from its human summary while that summary is
 * current (its plain-words questions carry the context the record leaves to its AC and decision
 * ids), else from the record. `recordPath` is under `brain/`.
 */
export function useOpenQuestions(project: string, recordPath: string): readonly OpenQuestion[] {
  const record = useBrainNote(project, recordPath);
  const path = summaryPath(recordPath);
  const tree = useBrainTree(project);
  const listed = tree.data?.entries.some((entry) => entry.path === path) === true;
  const summary = useBrainNote(project, path, listed);
  return useMemo(() => {
    const markdown = record.data?.markdown;
    if (!markdown) return [];
    const own = openQuestions(markdown);
    const current = summary.data && summaryState(summary.data, record.data) === "fresh";
    return current ? questionsToShow(own, openQuestions(summary.data.markdown)) : own;
  }, [record.data, summary.data]);
}

/**
 * The record's open questions above its Approve bar: each one folds open to its prose and its
 * answers as choices, as Claude's questions in the chat: the options the record lists (the
 * recommended one tagged), "Take the recommendation" or "Let Claude decide" when none is marked,
 * and "Other" with a box for the owner's own answer. The default choice sends a blank answer, and
 * each row says which outcome it will send. Once sent, the rows read back what went.
 */
export function OpenQuestions({
  questions,
  answers,
  changed,
  onAnswer,
  disabled,
  sent,
}: {
  questions: readonly OpenQuestion[];
  answers: Answers;
  changed: ReadonlySet<string>;
  onAnswer: (question: OpenQuestion, text: string) => void;
  disabled: boolean;
  sent: boolean;
}) {
  const headingId = useId();
  const [open, setOpen] = useState<ReadonlySet<string>>(
    () => new Set(questions.length <= OPEN_UP_TO ? questions.map((q) => q.id) : []),
  );
  const allOpen = questions.every((q) => open.has(q.id));
  const toggle = (id: string, isOpen: boolean) => {
    setOpen((current) => {
      const next = new Set(current);
      if (isOpen) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  return (
    <section id={QUESTIONS_ID} className="ah-aq-block" aria-labelledby={headingId}>
      <div className="ah-row" style={{ gap: 8 }}>
        <h3 id={headingId} className="ah-h3" tabIndex={-1}>
          Open questions
        </h3>
        <span className="ah-grow" />
        {!sent && questions.length > 1 && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setOpen(new Set(allOpen ? [] : questions.map((q) => q.id)));
            }}
          >
            {allOpen ? "Collapse all" : "Expand all"}
          </Button>
        )}
      </div>
      {!sent && (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          Answer only what you want to decide. A blank answer accepts the recommendation.
        </p>
      )}
      <div className="ah-aq-list">
        {questions.map((question) => (
          <Question
            key={question.id}
            question={question}
            answer={answers[question.id] ?? ""}
            changed={changed.has(question.id)}
            open={sent || open.has(question.id)}
            onToggle={(isOpen) => {
              toggle(question.id, isOpen);
            }}
            onAnswer={(text) => {
              onAnswer(question, text);
            }}
            disabled={disabled}
            sent={sent}
          />
        ))}
      </div>
    </section>
  );
}

function Question({
  question,
  answer,
  changed,
  open,
  onToggle,
  onAnswer,
  disabled,
  sent,
}: {
  question: OpenQuestion;
  answer: string;
  changed: boolean;
  open: boolean;
  onToggle: (open: boolean) => void;
  onAnswer: (text: string) => void;
  disabled: boolean;
  sent: boolean;
}) {
  const choiceName = useId();
  const counterId = useId();
  const field = useRef<HTMLTextAreaElement>(null);
  const [writing, setWriting] = useState(false);
  const recommendedOption = question.options.find((option) => option.recommended);
  const trimmed = answer.trim();
  const pickedOption = question.options.find(
    (option) => option !== recommendedOption && option.label === trimmed,
  );
  // A blank answer is the recommendation (or Claude's call); an option's label picks that option;
  // any other text is the owner's own answer.
  const choice =
    writing || (trimmed && !pickedOption) ? OTHER_CHOICE : (pickedOption?.label ?? DEFAULT_CHOICE);
  const choose = (next: string) => {
    if (next === OTHER_CHOICE) {
      if (pickedOption) onAnswer("");
      setWriting(true);
      requestAnimationFrame(() => field.current?.focus());
      return;
    }
    setWriting(false);
    onAnswer(next === DEFAULT_CHOICE ? "" : next);
  };
  const showCount = answer.length >= MAX_ANSWER_CHARS * COUNT_FROM;
  const outcome = outcomeOf(question, { [question.id]: answer });
  const { icon, label } = OUTCOME[outcome];
  const glimpse =
    outcome === "answered"
      ? oneLine(answer)
      : outcome === "recommended"
        ? (question.recommendation ?? "").replaceAll("`", "")
        : null;

  if (sent) {
    return (
      <div className="ah-aq">
        <div className="ah-aq-summary" style={{ cursor: "default" }}>
          <span className="ah-aq-id ah-mono ah-small ah-subtle">{question.id}</span>
          <b className="ah-aq-title">{question.title}</b>
          <span className="ah-aq-outcome ah-small">
            <Icon name={icon} size="sm" />
            {label}
          </span>
        </div>
        {outcome === "answered" && <p className="ah-aq-sent ah-small">{answer.trim()}</p>}
      </div>
    );
  }

  return (
    <details
      className="ah-aq"
      open={open}
      onToggle={(event) => {
        onToggle(event.currentTarget.open);
      }}
    >
      <summary className="ah-aq-summary">
        <Icon name="chevron-right" size="sm" className="ah-aq-chevron" />
        <span className="ah-aq-id ah-mono ah-small ah-subtle">{question.id}</span>
        <span className="ah-aq-head">
          <b className="ah-aq-title">{question.title}</b>
          {!open && glimpse && <span className="ah-aq-glimpse ah-small ah-muted">{glimpse}</span>}
        </span>
        <span className="ah-aq-outcome ah-small">
          <Icon name={icon} size="sm" />
          {label}
        </span>
      </summary>
      <div className="ah-aq-body">
        {question.body && <Markdown source={question.body} className="ah-aq-prose ah-small" />}
        {changed && (
          <p className="ah-row ah-small ah-muted" style={{ gap: "var(--space-2)", margin: 0 }}>
            <Icon name="triangle-alert" size="sm" />
            This question changed after you wrote the answer.
          </p>
        )}
        <fieldset className="ah-aq-choices" disabled={disabled}>
          <legend className="ah-small">Your answer to {question.id}</legend>
          <div className="ah-options">
            {!recommendedOption && (
              <OptionRow
                type="radio"
                name={choiceName}
                label={question.recommendation ? "Take the recommendation" : "Let Claude decide"}
                recommended={Boolean(question.recommendation)}
                description={
                  question.recommendation
                    ? withCode(question.recommendation)
                    : "No recommendation in the spec: Claude decides from its research."
                }
                checked={choice === DEFAULT_CHOICE}
                onToggle={() => {
                  choose(DEFAULT_CHOICE);
                }}
              />
            )}
            {question.options.map((option) => (
              <OptionRow
                key={option.label}
                type="radio"
                name={choiceName}
                label={option.label}
                recommended={option.recommended}
                description={option.description ? withCode(option.description) : null}
                checked={choice === (option === recommendedOption ? DEFAULT_CHOICE : option.label)}
                onToggle={() => {
                  choose(option === recommendedOption ? DEFAULT_CHOICE : option.label);
                }}
              />
            ))}
            <OptionRow
              type="radio"
              name={choiceName}
              label="Other"
              description={choice === OTHER_CHOICE ? null : "Write your own answer"}
              checked={choice === OTHER_CHOICE}
              onToggle={() => {
                choose(OTHER_CHOICE);
              }}
            >
              {choice === OTHER_CHOICE && (
                <>
                  <textarea
                    ref={field}
                    className="ah-input ah-aq-input"
                    rows={3}
                    maxLength={MAX_ANSWER_CHARS}
                    value={answer}
                    aria-label={`Your own answer to ${question.id}`}
                    placeholder={
                      question.recommendation
                        ? `Blank: ${clipLine(question.recommendation.replaceAll("`", ""), PLACEHOLDER_CHARS)}`
                        : "Blank: Claude decides"
                    }
                    aria-describedby={showCount ? counterId : undefined}
                    onChange={(event) => {
                      onAnswer(event.target.value);
                    }}
                  />
                  {showCount && (
                    <span id={counterId} className="ah-small ah-subtle ah-num">
                      {answer.length.toLocaleString("en-US")} /{" "}
                      {MAX_ANSWER_CHARS.toLocaleString("en-US")}
                    </span>
                  )}
                </>
              )}
            </OptionRow>
          </div>
        </fieldset>
      </div>
    </details>
  );
}

/**
 * "13 open questions" in the record's header: the block sits at the end of a long record, so this
 * says it is there and takes the owner to it (scrolls to and focuses its heading).
 */
export function QuestionsLink({ project, path }: { project: string; path: string }) {
  const count = useOpenQuestions(project, path).length;
  // The block shows only with session control (ApproveRecord): without it, nothing to reach.
  const sessions = useApi("/api/v1/agent-sessions", { query: { project } }, { retry: false });
  if (count === 0 || !sessions.isSuccess) return null;
  return (
    <a
      className="ah-small"
      href={`#${QUESTIONS_ID}`}
      onClick={(event) => {
        const block = document.getElementById(QUESTIONS_ID);
        if (!block) return;
        event.preventDefault();
        block.scrollIntoView({ block: "start" });
        block.querySelector<HTMLElement>("h3")?.focus({ preventScroll: true });
      }}
    >
      {count} open question{count === 1 ? "" : "s"}
    </a>
  );
}
