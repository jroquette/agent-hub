import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import { Button, Icon, MenuItem, Popover } from "../../components";
import { ApiProblem, apiPost, useApi } from "../../lib/api";
import { useBrainNote } from "../brain/queries";
import { agentSessionHref } from "../sessions-list/control";
import { OpenQuestions, useOpenQuestions } from "./QuestionsBlock";
import { approvalMessage, countLine, outcomeOf, type Answers } from "./openQuestions";
import { ANSWERS_MAX_BYTES, useAnswerDrafts } from "./useAnswerDrafts";

export { approvalMessage } from "./openQuestions";

type AgentSession = components["schemas"]["AgentSession"];

/** How many sessions the picker lists besides the ones that worked on the feature. */
const OTHER_SESSIONS = 8;

/** The Discuss panel's conversation about this feature, which is not where the work happens. */
function discussSessionId(project: string, slug: string): string | null {
  try {
    return window.localStorage.getItem(`ah.discuss.session.feature:${project}:${slug}`);
  } catch {
    return null;
  }
}

const pickedKey = (project: string, slug: string) => `ah.approve.session.${project}:${slug}`;

/** The session the owner last sent this feature's approvals to, remembered per feature. */
function readPicked(project: string, slug: string): string | null {
  try {
    return window.localStorage.getItem(pickedKey(project, slug));
  } catch {
    return null;
  }
}

function writePicked(project: string, slug: string, id: string) {
  try {
    window.localStorage.setItem(pickedKey(project, slug), id);
  } catch {
    // Without storage the pick lasts until the page reloads.
  }
}

/** A session's name in one line: its title, else its last prompt. */
export function sessionName(session: AgentSession): string {
  const text = session.title ?? session.last_prompt ?? "";
  const line = text.replace(/\s+/g, " ").trim();
  if (!line) return "Untitled session";
  return line.length > 60 ? `${line.slice(0, 59)}…` : line;
}

/**
 * The sessions that worked on this feature, most recent first: the ones that changed a file of
 * its record folder, or whose title, last prompt or last reply names the feature or a ticket.
 */
export function featureSessions(
  sessions: readonly AgentSession[],
  slug: string,
  tickets: readonly string[],
  exclude: string | null,
): AgentSession[] {
  const folder = `features/${slug}/`;
  const names = [slug, ...tickets];
  // The list route leaves `changed_files` out (only one session's read carries it).
  const touched = (s: AgentSession) => {
    const files = (s as Partial<AgentSession>).changed_files ?? [];
    return files.some((f) => f.path.includes(folder));
  };
  const named = (s: AgentSession) =>
    [s.title, s.last_prompt, s.last_reply].some(
      (text) => text != null && names.some((name) => text.includes(name)),
    );
  return sessions
    .filter((s) => s.id !== exclude && s.kind === "local" && (touched(s) || named(s)))
    .sort(
      (a, b) => Number(touched(b)) - Number(touched(a)) || b.updated_at.localeCompare(a.updated_at),
    );
}

/**
 * Approve a feature record (spec, research, plan) from its tab, at the end of the record
 * (`children`): the approval goes as a message to the session that wrote the record, so that
 * session goes on from where it asked. The target is the one the owner picked for this feature,
 * else the newest session that wrote the file (`?wrote=`), else the newest one naming the feature;
 * the arrow picks another one. When the record has open questions, they sit above the bar with
 * a box each; the answers (or "accept the recommendation" for a blank one) go with the approval.
 * A record whose frontmatter says `status: approved` shows that it is approved and offers no
 * approval again.
 */
export function ApproveRecord({
  project,
  slug,
  record,
  path,
  tickets,
  children,
}: {
  project: string;
  slug: string;
  record: string;
  path: string;
  tickets: readonly string[];
  children?: ReactNode;
}) {
  const sessions = useApi(
    "/api/v1/agent-sessions",
    { query: { project } },
    { retry: false, refetchInterval: 15_000 },
  );
  const writers = useApi(
    "/api/v1/agent-sessions",
    { query: { project, wrote: path } },
    { retry: false, refetchInterval: 15_000 },
  );
  const [chosen, setChosen] = useState<string | null>(() => readPicked(project, slug));
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<AgentSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [sentAnswers, setSentAnswers] = useState<Answers>({});
  const notePath = path.replace(/^brain\//, "");
  const note = useBrainNote(project, notePath);
  const questions = useOpenQuestions(project, notePath);
  const drafts = useAnswerDrafts(project, slug, record, questions);

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element && target.closest("[data-approve-picker]"))) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    // Focus goes into the list on open: the session picked, else the first one.
    const list = trigger.current?.parentElement;
    const first =
      list?.querySelector<HTMLElement>(".ah-menu-item[aria-current]") ??
      list?.querySelector<HTMLElement>(".ah-menu-item");
    first?.focus();
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // An approved record says so instead of offering the approval again.
  if (isApproved(note.data?.frontmatter.status)) {
    return (
      <>
        {children}
        <div className="ah-row ah-wrap ah-small" style={{ gap: 8 }} role="status">
          <Icon name="check" size="sm" style={{ color: "var(--done)" }} />
          <span>
            {`${record.charAt(0).toUpperCase()}${record.slice(1)}`} approved
            {typeof note.data?.frontmatter.last_verified === "string" &&
              ` · last verified ${note.data.frontmatter.last_verified}`}
            .
          </span>
        </div>
      </>
    );
  }
  // Without session control (no cookie, the container) there is nowhere to send it.
  if (!sessions.isSuccess) return <>{children}</>;
  const all = sessions.data.items.filter((s) => s.kind === "local");
  const wrote = writersOf(writers.data?.items ?? [], all);
  const related = featureSessions(all, slug, tickets, discussSessionId(project, slug)).filter(
    (s) => !wrote.some((w) => w.id === s.id),
  );
  const listed = [...wrote, ...related];
  const others = all.filter((s) => !listed.some((r) => r.id === s.id)).slice(0, OTHER_SESSIONS);
  const target = [...all, ...wrote].find((s) => s.id === chosen) ?? wrote[0] ?? related[0] ?? null;

  const approve = () => {
    if (!target) {
      setOpen(true);
      return;
    }
    const answers = drafts.answers;
    const text = approvalMessage(record, path, questions, answers);
    if (new TextEncoder().encode(text).length > ANSWERS_MAX_BYTES) {
      setError(
        "Your answers are too long for one message (over 64 KiB). Shorten the longest ones.",
      );
      return;
    }
    setBusy(true);
    setError(null);
    void apiPost(
      "/api/v1/agent-sessions/{agent_session_id}/messages",
      { text },
      { path: { agent_session_id: target.id } },
    )
      .then(() => {
        writePicked(project, slug, target.id);
        setSentAnswers(answers);
        drafts.clear();
        setSent(target);
      })
      .catch((cause: unknown) => {
        const why =
          cause instanceof ApiProblem
            ? (cause.detail ?? cause.title)
            : "The approval could not be sent.";
        setError(`${why} Try again, or pick another session.`);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const pick = (id: string) => () => {
    setChosen(id);
    writePicked(project, slug, id);
    setOpen(false);
    trigger.current?.focus();
  };
  const item = (s: AgentSession) => (
    <MenuItem
      key={s.id}
      icon="square-terminal"
      selected={s.id === target?.id}
      onClick={pick(s.id)}
      hint={<span className="ah-subtle ah-small">{s.status}</span>}
    >
      {sessionName(s)}
    </MenuItem>
  );
  const section = (label: string, rows: readonly AgentSession[]) =>
    rows.length > 0 && (
      <>
        <div className="ah-subtle ah-small" style={{ padding: "var(--space-2) var(--space-3)" }}>
          {label}
        </div>
        {rows.map(item)}
      </>
    );

  const answered = questions.filter((q) => outcomeOf(q, drafts.answers) === "answered").length;
  const withAnswers = (n: number) =>
    n === 0 ? "" : ` with ${String(n)} answer${n === 1 ? "" : "s"}`;
  const sentCount = questions.filter((q) => outcomeOf(q, sentAnswers) === "answered").length;

  const bar = () => {
    if (sent) {
      return (
        <div className="ah-row ah-wrap ah-small" style={{ gap: 8 }} role="status">
          <Icon name="check" size="sm" style={{ color: "var(--done)" }} />
          <span>
            Approval of the {record} sent to <b>{sessionName(sent)}</b>
            {withAnswers(sentCount)}.
          </span>
          <Link to={agentSessionHref(sent.id)}>Open session</Link>
        </div>
      );
    }
    const wroteIt = target !== null && wrote.some((s) => s.id === target.id);
    return (
      <div className="ah-stack" style={{ gap: "var(--space-2)" }}>
        {questions.length > 0 && (
          <span className="ah-small ah-muted">{countLine(questions, drafts.answers)}</span>
        )}
        <div
          className="ah-row ah-wrap ah-small"
          style={{ gap: 8 }}
          role="group"
          aria-label={`Approve the ${record}`}
        >
          <Button
            size="sm"
            variant="primary"
            icon="check"
            disabled={busy}
            onClick={approve}
            title={
              target
                ? questions.length > 0
                  ? `Send the approval and your answers to ${sessionName(target)}`
                  : `Send "${approvalMessage(record, path)}" to ${sessionName(target)}`
                : "Pick the session that worked on this feature"
            }
          >
            {busy ? "Sending approval…" : `Approve ${record}${withAnswers(answered)}`}
          </Button>
          <span data-approve-picker style={{ position: "relative" }} className="ah-row">
            <button
              type="button"
              className="ah-btn ah-btn-ghost ah-btn-sm"
              ref={trigger}
              aria-haspopup="dialog"
              aria-expanded={open}
              disabled={busy}
              aria-label={`Approval goes to: ${target ? sessionName(target) : "no session picked"}`}
              onClick={() => {
                setOpen(!open);
              }}
            >
              <span className="ah-muted">to</span>
              <span>{target ? sessionName(target) : "pick a session"}</span>
              {wroteIt && <span className="ah-subtle">· wrote it</span>}
              <Icon name="chevron-down" size="sm" />
            </button>
            <Popover
              open={open}
              label="Session that gets the approval"
              style={{
                bottom: "calc(100% + var(--space-1))",
                left: 0,
                minWidth: 320,
                maxWidth: 440,
              }}
            >
              {section(`Wrote ${path.split("/").pop() ?? record}`, wrote)}
              {section(`Worked on ${slug}`, related)}
              {section(`Other sessions in ${project}`, others)}
              {all.length === 0 && wrote.length === 0 && (
                <div
                  className="ah-muted ah-small"
                  style={{ padding: "var(--space-2) var(--space-3)" }}
                >
                  No session in {project} yet.
                </div>
              )}
            </Popover>
          </span>
          {error && (
            <span role="alert" className="ah-row" style={{ gap: "var(--space-2)" }}>
              <Icon name="circle-x" size="sm" style={{ color: "var(--failed)" }} />
              <span>{error}</span>
            </span>
          )}
        </div>
      </div>
    );
  };

  return (
    <>
      {children}
      {questions.length > 0 && (
        <OpenQuestions
          questions={questions}
          answers={sent ? sentAnswers : drafts.answers}
          changed={drafts.changed}
          onAnswer={drafts.set}
          disabled={busy}
          sent={sent !== null}
        />
      )}
      {bar()}
    </>
  );
}

/** Whether a record's frontmatter `status` says the owner approved it. */
export function isApproved(status: string | readonly string[] | undefined): boolean {
  return typeof status === "string" && status.trim().toLowerCase() === "approved";
}

/**
 * The local sessions `?wrote=` answered. A hub web older than that filter ignores it and answers
 * every session; that answer names no writer.
 */
export function writersOf(
  answered: readonly AgentSession[],
  all: readonly AgentSession[],
): AgentSession[] {
  const local = answered.filter((s) => s.kind === "local");
  const ignored = all.length > 1 && local.length >= all.length;
  return ignored ? [] : local;
}
