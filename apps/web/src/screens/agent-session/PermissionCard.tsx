import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import type { components } from "../../api/schema";
import { Button, Icon, Markdown } from "../../components";
import { ApiProblem } from "../../lib/api";
import { cx } from "../../lib/cx";
import { goSequencePending } from "../../shell/goSequence";
import { fmtClock } from "../../lib/format";
import { StoredCopyLabel } from "./SessionStatus";
import {
  modeLabel,
  ruleLabel,
  asArray,
  asObject,
  str,
  type JsonObject,
  type PermissionDecisionView,
  type PermissionView,
} from "./transcript";

/** The request the chat's chords answer: the oldest pending one (AC-234.29). */
export const OldestPendingContext = createContext<string | undefined>(undefined);
export const ALLOW_KEYS = "Control+Alt+Enter Meta+Alt+Enter";
export const DENY_KEYS = "Control+Alt+Backspace Meta+Alt+Backspace";

/** Whether focus is in a text field holding text: a card arriving then leaves it there. */
function typingText(element: Element | null): boolean {
  return (
    (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement) &&
    element.value !== ""
  );
}

/** The body of `POST /{id}/permissions/{request_id}` (E7). */
export type PermissionAnswer = components["schemas"]["PermissionDecision"];

/** The longest deny message the API takes (2 KiB, plan "Inputs, bounds and budget"). */
export const MAX_DENY_MESSAGE = 2048;
/** The only destination "Always allow" may write to (D5). */
export const ALWAYS_DESTINATION = "localSettings";

export interface PermissionCardProps {
  request: PermissionView;
  /** Posts the answer; a rejection re-enables the card and shows why. */
  onAnswer?: ((answer: PermissionAnswer) => Promise<unknown> | undefined) | undefined;
  /** Move focus to the card when it arrives (default: while it is pending). */
  autoFocus?: boolean | undefined;
}

interface Question {
  question: string;
  header: string | null;
  options: { label: string; description: string | null }[];
  multiSelect: boolean;
}

function questionsOf(input: JsonObject | null): Question[] {
  return asArray(input?.questions).flatMap((item) => {
    const q = asObject(item);
    const question = q ? str(q, "question") : null;
    if (!q || question === null) return [];
    return [
      {
        question,
        header: str(q, "header"),
        multiSelect: q.multiSelect === true,
        options: asArray(q.options).flatMap((value) => {
          const option = asObject(value);
          const label = option ? str(option, "label") : null;
          return option && label !== null
            ? [{ label, description: str(option, "description") }]
            : [];
        }),
      },
    ];
  });
}

function outcomeText(decision: PermissionDecisionView): string {
  if (decision.decision === "allow") return "Allowed once";
  if (decision.decision === "always") return "Always allowed";
  if (decision.by === "timeout") return "Denied: no answer before the deadline";
  if (decision.by === "closed") return "Denied: the session closed";
  return decision.message ? `Denied: ${decision.message}` : "Denied";
}

const HEADING: Record<PermissionView["requestKind"], (tool: string) => string> = {
  tool: (tool) => `Claude wants to use ${tool}`,
  ask_user_question: () => "Claude has a question",
  plan_approval: () => "Claude finished a plan",
};

function problemText(error: unknown): string {
  if (error instanceof ApiProblem)
    return error.detail ? `${error.title}: ${error.detail}` : error.title;
  return "Could not send the answer. Try again.";
}

/** One question of an `AskUserQuestion`: option buttons plus "Other" with free text. */
function QuestionField({
  question,
  value,
  disabled,
  onChange,
}: {
  question: Question;
  value: string[];
  disabled: boolean;
  onChange: (value: string[]) => void;
}) {
  const [other, setOther] = useState<string | null>(null);
  const otherId = useId();
  const pick = (label: string) => {
    setOther(null);
    if (!question.multiSelect) onChange([label]);
    else onChange(value.includes(label) ? value.filter((v) => v !== label) : [...value, label]);
  };
  return (
    <fieldset className="as-question" disabled={disabled}>
      <legend>
        {question.header && <span className="as-question-header">{question.header}</span>}{" "}
        {question.question}
      </legend>
      <div className="ah-row ah-wrap" style={{ gap: 6 }}>
        {question.options.map((option) => (
          <Button
            key={option.label}
            size="sm"
            aria-pressed={other === null && value.includes(option.label)}
            title={option.description ?? undefined}
            onClick={() => {
              pick(option.label);
            }}
          >
            {option.label}
          </Button>
        ))}
        <Button
          size="sm"
          aria-pressed={other !== null}
          onClick={() => {
            setOther("");
            onChange([]);
          }}
        >
          Other
        </Button>
      </div>
      {other !== null && (
        <div className="ah-stack" style={{ gap: 4 }}>
          <label htmlFor={otherId} className="ah-small">
            Your answer
          </label>
          <input
            id={otherId}
            className="ah-input"
            value={other}
            maxLength={1024}
            onChange={(event) => {
              setOther(event.target.value);
              const text = event.target.value.trim();
              onChange(text ? [text] : []);
            }}
          />
        </div>
      )}
    </fieldset>
  );
}

/**
 * A permission request inline in the transcript (D5, AC-165.44): tool, input summary and Claude's
 * suggestions, answered with Allow once, Deny (with a message) or Always allow, offered only for
 * `localSettings` suggestions. An `AskUserQuestion` shows its options plus "Other"; a plan approval
 * shows the plan and the mode to continue in. Focus moves to the card when it arrives; one answer
 * is posted, then the card is disabled.
 */
export function PermissionCard({ request, onAnswer, autoFocus }: PermissionCardProps) {
  const card = useRef<HTMLElement>(null);
  const posting = useRef(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [planMode, setPlanMode] = useState<"default" | "acceptEdits">("default");
  const titleId = useId();
  const messageId = useId();
  const modeId = useId();
  const pending = request.decision === null;
  const focus = autoFocus ?? pending;
  // The keys answer tool permissions only, never a question or a plan (AC-234.29).
  const keyed = request.requestKind === "tool";
  const oldest = useContext(OldestPendingContext) === request.requestId;
  const chords = keyed && oldest;

  useEffect(() => {
    if (focus && !typingText(document.activeElement)) card.current?.focus();
    // Only on arrival: answering keeps the focus where it is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const disabled = !pending || sent || !onAnswer;
  const submit = (answer: PermissionAnswer) => {
    if (posting.current || !onAnswer) return;
    posting.current = true;
    setSent(true);
    // The buttons are disabled, then gone once answered: the keyboard stays on the card.
    card.current?.focus({ preventScroll: true });
    setError(null);
    void Promise.resolve()
      .then(() => onAnswer(answer))
      .catch((reason: unknown) => {
        posting.current = false;
        setSent(false);
        setError(problemText(reason));
      });
  };
  const deny = () => {
    const text = message.trim();
    submit(text ? { decision: "deny", message: text } : { decision: "deny" });
  };
  // `a` / `d` while the card itself has focus, not a field or button inside it.
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget || disabled || !keyed) return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    // The second key of a `g` sequence is the shell's: `g a` goes to Approvals, never allows.
    if (goSequencePending()) return;
    if (event.key === "a") submit({ decision: "allow" });
    else if (event.key === "d") deny();
    else return;
    event.preventDefault();
  };

  const questions = request.requestKind === "ask_user_question" ? questionsOf(request.input) : [];
  const allAnswered = questions.every((q) => (answers[q.question] ?? []).length > 0);
  const plan =
    request.requestKind === "plan_approval" && typeof request.input?.plan === "string"
      ? request.input.plan
      : null;
  const always = request.suggestions.filter((s) => s.destination === ALWAYS_DESTINATION);

  return (
    // The card takes focus (tabIndex -1) and then answers to `a` / `d` (AC-234.29).
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <section
      ref={card}
      className={cx("as-perm", pending ? "as-perm-pending" : "as-perm-done")}
      data-request-id={request.requestId}
      aria-labelledby={titleId}
      tabIndex={-1}
      onKeyDown={onKeyDown}
    >
      <header className="as-perm-head">
        <Icon name={pending ? "hand" : "shield-check"} />
        <h3 id={titleId} className="as-perm-title">
          {HEADING[request.requestKind](request.tool)}
        </h3>
        {request.redacted && <StoredCopyLabel />}
      </header>

      {request.requestKind === "tool" && (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        <pre className="as-pre" tabIndex={0} aria-label="What it will run">
          {request.summary}
        </pre>
      )}
      {plan !== null && <Markdown source={plan} className="as-plan" />}
      {request.requestKind === "ask_user_question" && questions.length === 0 && (
        <p>{request.summary}</p>
      )}

      {!pending && request.decision && (
        <p className="as-perm-outcome" role="status">
          {outcomeText(request.decision)}
        </p>
      )}

      {pending && (
        <div className="ah-stack" style={{ gap: 8 }}>
          {questions.map((question) => (
            <QuestionField
              key={question.question}
              question={question}
              value={answers[question.question] ?? []}
              disabled={disabled}
              onChange={(value) => {
                setAnswers((before) => ({ ...before, [question.question]: value }));
              }}
            />
          ))}
          {plan !== null && (
            <label htmlFor={modeId} className="ah-row ah-small" style={{ gap: 6 }}>
              Then continue in
              <select
                id={modeId}
                className="ah-input as-select"
                value={planMode}
                disabled={disabled}
                onChange={(event) => {
                  setPlanMode(event.target.value === "acceptEdits" ? "acceptEdits" : "default");
                }}
              >
                <option value="default">{modeLabel("default")}</option>
                <option value="acceptEdits">{modeLabel("acceptEdits")}</option>
              </select>
            </label>
          )}
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={messageId} className="ah-small ah-muted">
              Message to Claude if you deny (optional)
            </label>
            <input
              id={messageId}
              className="ah-input"
              value={message}
              maxLength={MAX_DENY_MESSAGE}
              disabled={disabled}
              onChange={(event) => {
                setMessage(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && message.trim()) {
                  event.preventDefault();
                  deny();
                }
              }}
            />
          </div>
          <div className="ah-row ah-wrap as-perm-actions">
            {request.requestKind === "tool" && (
              <>
                <Button
                  variant="primary"
                  disabled={disabled}
                  data-shortcut="allow"
                  aria-keyshortcuts={chords ? ALLOW_KEYS : undefined}
                  onClick={() => {
                    submit({ decision: "allow" });
                  }}
                >
                  Allow once
                </Button>
                {always.map((suggestion) => (
                  <Button
                    key={suggestion.index}
                    disabled={disabled}
                    onClick={() => {
                      submit({ decision: "always", suggestion: suggestion.index });
                    }}
                  >
                    Always allow {ruleLabel(suggestion.rule)}
                  </Button>
                ))}
              </>
            )}
            {request.requestKind === "ask_user_question" && questions.length > 0 && (
              <Button
                variant="primary"
                disabled={disabled || !allAnswered}
                onClick={() => {
                  submit({
                    decision: "allow",
                    answers: Object.fromEntries(
                      questions.map((q) => [q.question, (answers[q.question] ?? []).join(", ")]),
                    ),
                  });
                }}
              >
                Send answers
              </Button>
            )}
            {request.requestKind === "plan_approval" && (
              <Button
                variant="primary"
                disabled={disabled}
                onClick={() => {
                  submit({ decision: "allow", mode: planMode });
                }}
              >
                Approve plan
              </Button>
            )}
            <Button
              variant="danger"
              disabled={disabled}
              data-shortcut={keyed ? "deny" : undefined}
              aria-keyshortcuts={chords ? DENY_KEYS : undefined}
              onClick={deny}
            >
              {request.requestKind === "plan_approval" ? "Keep planning" : "Deny"}
            </Button>
          </div>
          {request.deadlineAt && (
            <p className="ah-small ah-subtle">
              Denied automatically at {fmtClock(request.deadlineAt, "local")} if unanswered.
            </p>
          )}
          {sent && (
            <p className="ah-small" role="status">
              Sending your answer…
            </p>
          )}
          {error && (
            <p className="ah-small as-error" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/** Posts a request's answer by its id; without it a card is read-only. */
export type AnswerPermission =
  ((requestId: string, answer: PermissionAnswer) => Promise<unknown> | undefined) | undefined;

/** The card of `request` in the transcript, answering through `onAnswerPermission`. */
export function RequestCard({
  request,
  onAnswerPermission,
}: {
  request: PermissionView;
  onAnswerPermission: AnswerPermission;
}) {
  return (
    <PermissionCard
      request={request}
      onAnswer={
        onAnswerPermission ? (answer) => onAnswerPermission(request.requestId, answer) : undefined
      }
    />
  );
}
