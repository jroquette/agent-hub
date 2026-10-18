import { useId, useMemo, useState } from "react";

import { Button, Icon, Markdown, type IconName } from "../../components";
import { useBrainNote } from "../brain/queries";
import {
  openQuestions,
  outcomeOf,
  type Answers,
  type OpenQuestion,
  type Outcome,
} from "./openQuestions";

import "./questions.css";

export const QUESTIONS_ID = "approve-questions";
const MAX_ANSWER_CHARS = 4000;
/** Up to this many questions start open; more start folded (progressive disclosure). */
const OPEN_UP_TO = 3;

const OUTCOME: Record<Outcome, { icon: IconName; label: string }> = {
  answered: { icon: "pencil", label: "Answered" },
  recommended: { icon: "check", label: "Takes the recommendation" },
  claude: { icon: "message-square", label: "Claude decides" },
};

/** Inline code spans (`…`) of a one-line text as code, the rest as plain text. */
function withCode(text: string) {
  return text
    .split("`")
    .map((part, index) =>
      index % 2 === 1 ? <code key={index}>{part}</code> : <span key={index}>{part}</span>,
    );
}

/** A text on one line, for the folded row's second line. */
function oneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/**
 * The record's open questions above its Approve bar: each one folds open to its prose, what the
 * record recommends and a box for the owner's answer; a blank answer takes the recommendation,
 * and each row says which outcome it will send. Once sent, the rows read back what went.
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
  const fieldId = useId();
  const recommendationId = useId();
  const counterId = useId();
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
        <p id={recommendationId} className="ah-small ah-muted" style={{ margin: 0 }}>
          {question.recommendation ? (
            <>
              Recommended in the spec: <q>{withCode(question.recommendation)}</q>
            </>
          ) : (
            "No recommendation in the spec. Left blank, Claude decides from its research."
          )}
        </p>
        {changed && (
          <p className="ah-row ah-small ah-muted" style={{ gap: 6, margin: 0 }}>
            <Icon name="triangle-alert" size="sm" />
            This question changed after you wrote the answer.
          </p>
        )}
        <label htmlFor={fieldId} className="ah-small">
          Your answer to {question.id}
        </label>
        <textarea
          id={fieldId}
          className="ah-input ah-aq-input"
          rows={3}
          maxLength={MAX_ANSWER_CHARS}
          value={answer}
          disabled={disabled}
          placeholder={
            question.recommendation
              ? "Leave blank to accept the recommendation"
              : "Leave blank to let Claude decide"
          }
          aria-describedby={`${recommendationId} ${counterId}`}
          onChange={(event) => {
            onAnswer(event.target.value);
          }}
        />
        <div className="ah-row" style={{ gap: 8 }}>
          {answer.trim() && (
            <Button
              size="sm"
              variant="ghost"
              disabled={disabled}
              onClick={(event) => {
                onAnswer("");
                const field = event.currentTarget.closest(".ah-aq-body")?.querySelector("textarea");
                field?.focus();
              }}
            >
              Clear answer
            </Button>
          )}
          <span className="ah-grow" />
          <span id={counterId} className="ah-small ah-subtle ah-num">
            {answer.length.toLocaleString("en-US")} / {MAX_ANSWER_CHARS.toLocaleString("en-US")}
          </span>
        </div>
      </div>
    </details>
  );
}

/**
 * "13 open questions" in the record's header: the block sits at the end of a long record, so this
 * says it is there and takes the owner to it (scrolls to and focuses its heading).
 */
export function QuestionsLink({ project, path }: { project: string; path: string }) {
  const note = useBrainNote(project, path);
  const markdown = note.data?.markdown;
  const count = useMemo(() => (markdown ? openQuestions(markdown).length : 0), [markdown]);
  if (count === 0) return null;
  return (
    <a
      className="ah-small"
      href={`#${QUESTIONS_ID}`}
      onClick={(event) => {
        const block = document.getElementById(QUESTIONS_ID);
        if (!block) return; // No session control: the block is not shown, nothing to reach.
        event.preventDefault();
        block.scrollIntoView({ block: "start" });
        block.querySelector<HTMLElement>("h3")?.focus({ preventScroll: true });
      }}
    >
      {count} open question{count === 1 ? "" : "s"}
    </a>
  );
}
