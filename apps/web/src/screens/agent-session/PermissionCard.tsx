import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import type { components } from "../../api/schema";
import { Button, Icon, Markdown, type IconName } from "../../components";
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
} from "./model";

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

/** The icon of a pending card: a terminal for a shell command, else what is being asked. */
function headIcon(request: PermissionView): IconName {
  if (request.requestKind === "plan_approval") return "clipboard-list";
  if (request.requestKind === "ask_user_question") return "list-checks";
  return request.tool === "Bash" ? "terminal" : "hand";
}

function problemText(error: unknown): string {
  if (error instanceof ApiProblem)
    return error.detail ? `${error.title}: ${error.detail}` : error.title;
  return "Could not send the answer. Try again.";
}

/** The card's own key for a button, shown only while the card itself has focus (CSS). */
function KeyHint({ letter }: { letter: string }) {
  return (
    <kbd className="ah-kbd as-perm-kbd" aria-hidden="true">
      {letter}
    </kbd>
  );
}

/** Claude marks its preferred option with a trailing "(Recommended)" in the label. */
const RECOMMENDED = /\s*\(recommended\)\s*$/i;

/** One choice of a question: a radio or checkbox row with its label and, below it, its description. */
function OptionRow({
  type,
  name,
  label,
  description,
  checked,
  onToggle,
  children,
}: {
  type: "radio" | "checkbox";
  name: string;
  label: string;
  description: string | null;
  checked: boolean;
  onToggle: () => void;
  children?: ReactNode;
}) {
  const labelId = useId();
  const descriptionId = useId();
  const recommended = RECOMMENDED.test(label);
  return (
    <label className={cx("as-option", checked && "as-option-checked")}>
      <input
        type={type}
        name={name}
        className="ah-check"
        checked={checked}
        aria-labelledby={labelId}
        aria-describedby={description ? descriptionId : undefined}
        onChange={onToggle}
      />
      <span className="as-option-body">
        <span className="as-option-label">
          <span id={labelId}>{label.replace(RECOMMENDED, "")}</span>
          {recommended && <span className="as-option-tag">Recommended</span>}
        </span>
        {description && (
          <span id={descriptionId} className="ah-small ah-muted">
            {description}
          </span>
        )}
        {children}
      </span>
    </label>
  );
}

/**
 * One question of an `AskUserQuestion`: its options as radio rows (checkboxes when several may be
 * chosen), each with its description in view, plus "Other" with free text.
 */
function QuestionField({
  question,
  disabled,
  onChange,
}: {
  question: Question;
  disabled: boolean;
  onChange: (value: string[]) => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [other, setOther] = useState<string | null>(null);
  const otherInput = useRef<HTMLInputElement>(null);
  const name = useId();
  const type = question.multiSelect ? "checkbox" : "radio";
  const emit = (nextPicked: string[], nextOther: string | null) => {
    setPicked(nextPicked);
    setOther(nextOther);
    const text = nextOther?.trim();
    onChange(text ? [...nextPicked, text] : nextPicked);
  };
  const pick = (label: string) => {
    if (!question.multiSelect) emit([label], null);
    else
      emit(picked.includes(label) ? picked.filter((v) => v !== label) : [...picked, label], other);
  };
  const toggleOther = () => {
    if (other !== null && question.multiSelect) emit(picked, null);
    else {
      emit(question.multiSelect ? picked : [], other ?? "");
      requestAnimationFrame(() => otherInput.current?.focus());
    }
  };
  return (
    <fieldset className="as-question" disabled={disabled}>
      <legend>
        {question.header && <span className="as-question-header">{question.header}</span>}{" "}
        <span className="as-question-text">{question.question}</span>
      </legend>
      {question.multiSelect && <p className="ah-small ah-muted as-question-hint">Choose any</p>}
      <div className="as-options">
        {question.options.map((option) => (
          <OptionRow
            key={option.label}
            type={type}
            name={name}
            label={option.label}
            description={option.description}
            checked={picked.includes(option.label)}
            onToggle={() => {
              pick(option.label);
            }}
          />
        ))}
        <OptionRow
          type={type}
          name={name}
          label="Other"
          description={other === null ? "Write your own answer" : null}
          checked={other !== null}
          onToggle={toggleOther}
        >
          {other !== null && (
            <input
              ref={otherInput}
              className="ah-input"
              aria-label="Your answer"
              placeholder="Your answer"
              value={other}
              maxLength={1024}
              onChange={(event) => {
                emit(picked, event.target.value);
              }}
            />
          )}
        </OptionRow>
      </div>
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
    // The second key of a `g` sequence is the shell's: `g a` never allows.
    if (goSequencePending()) return;
    if (event.key === "a") submit({ decision: "allow" });
    else if (event.key === "d") deny();
    else return;
    event.preventDefault();
  };

  const questions = request.requestKind === "ask_user_question" ? questionsOf(request.input) : [];
  const answeredCount = questions.filter((q) => (answers[q.question] ?? []).length > 0).length;
  const allAnswered = answeredCount === questions.length;
  // A question card is answered by its options and "Other": no deny message, no red refusal.
  const asking = request.requestKind === "ask_user_question" && questions.length > 0;
  const plan =
    request.requestKind === "plan_approval" && typeof request.input?.plan === "string"
      ? request.input.plan
      : null;
  const always = request.suggestions.filter((s) => s.destination === ALWAYS_DESTINATION);
  // What Claude says the call is for (Bash's `description`), shown above the raw command.
  const purpose =
    request.requestKind === "tool" && typeof request.input?.description === "string"
      ? request.input.description.trim() || null
      : null;

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
        <span className={cx("as-perm-icon", `as-perm-icon-${request.requestKind}`)}>
          <Icon name={pending ? headIcon(request) : "shield-check"} />
        </span>
        <div className="as-perm-heading">
          <h3 id={titleId} className="as-perm-title">
            {HEADING[request.requestKind](request.tool)}
          </h3>
          {purpose && <p className="as-perm-purpose">{purpose}</p>}
        </div>
        {request.redacted && <StoredCopyLabel />}
        {pending && (
          <span className="as-perm-badge">
            <span className="as-perm-dot" aria-hidden="true" />
            Waiting for you
          </span>
        )}
      </header>

      {request.requestKind === "tool" && (
        <pre
          className="as-pre as-perm-command"
          data-tool={request.tool}
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
          aria-label="What it will run"
        >
          {request.summary}
        </pre>
      )}
      {plan !== null && <Markdown source={plan} className="as-plan" />}
      {request.requestKind === "ask_user_question" && questions.length === 0 && (
        <p>{request.summary}</p>
      )}

      {!pending && request.decision && (
        <p
          className={cx(
            "as-perm-outcome",
            request.decision.decision === "deny" ? "as-perm-outcome-deny" : "as-perm-outcome-allow",
          )}
          role="status"
        >
          {outcomeText(request.decision)}
        </p>
      )}

      {pending && (
        <div className="ah-stack" style={{ gap: 8 }}>
          {questions.map((question) => (
            <QuestionField
              key={question.question}
              question={question}
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
          <div className="ah-row ah-wrap as-perm-actions">
            {request.requestKind === "tool" && (
              <>
                <Button
                  variant="primary"
                  icon="check"
                  disabled={disabled}
                  data-shortcut="allow"
                  aria-keyshortcuts={chords ? ALLOW_KEYS : undefined}
                  onClick={() => {
                    submit({ decision: "allow" });
                  }}
                >
                  Allow once
                  <KeyHint letter="A" />
                </Button>
                {always.map((suggestion) => {
                  const rule = ruleLabel(suggestion.rule);
                  return (
                    <Button
                      key={suggestion.index}
                      className="as-perm-always"
                      disabled={disabled}
                      title={`Always allow ${rule} in this project's local settings`}
                      onClick={() => {
                        submit({ decision: "always", suggestion: suggestion.index });
                      }}
                    >
                      Always allow <code className="as-perm-rule">{rule}</code>
                    </Button>
                  );
                })}
              </>
            )}
            {asking && (
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
                icon="check"
                disabled={disabled}
                onClick={() => {
                  submit({ decision: "allow", mode: planMode });
                }}
              >
                Approve plan
              </Button>
            )}
            {asking && (
              <Button disabled={disabled} onClick={deny}>
                {questions.length > 1 ? "Skip questions" : "Skip question"}
              </Button>
            )}
            {asking && questions.length > 1 && (
              <span className="ah-small ah-muted" aria-live="polite">
                {answeredCount} of {questions.length} answered
              </span>
            )}
          </div>
          {!asking && (
            <div className="as-perm-deny">
              <input
                id={messageId}
                className="ah-input"
                aria-label="Message to Claude if you deny (optional)"
                placeholder={
                  request.requestKind === "plan_approval"
                    ? "What should change in the plan? (optional)"
                    : "Tell Claude what to do instead (optional)"
                }
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
              <Button
                variant="danger"
                disabled={disabled}
                data-shortcut={keyed ? "deny" : undefined}
                aria-keyshortcuts={chords ? DENY_KEYS : undefined}
                onClick={deny}
              >
                {request.requestKind === "plan_approval" ? "Keep planning" : "Deny"}
                {keyed && <KeyHint letter="D" />}
              </Button>
            </div>
          )}
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
