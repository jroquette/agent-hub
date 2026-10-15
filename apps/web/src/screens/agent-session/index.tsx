import "./agent-session.css";

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import {
  AppLink,
  Banner,
  Button,
  ConfirmDialog,
  EmptyState,
  Icon,
  ProblemError,
  Skeleton,
} from "../../components";
import { ApiProblem } from "../../lib/api";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { sessionControlUnavailable } from "../sessions-list/AgentSessionList";
import { Composer, DEFAULT_MESSAGE_MAX_BYTES } from "./Composer";
import { OldestPendingContext } from "./PermissionCard";
import { CostMeter } from "./CostMeter";
import {
  isTerminal,
  useAgentSession,
  useAgentSessionCommands,
  useAgentTranscript,
  useCapabilities,
} from "./queries";
import { AgentStatusBadge, ReconnectBanner } from "./SessionStatus";
import { TodoList } from "./TodoList";
import { Transcript } from "./Transcript";
import { modeLabel, pendingPermissions, type TranscriptState } from "./transcript";
import { useStickToBottom } from "./useStickToBottom";

const DEFAULT_MODELS = ["default", "opus", "sonnet", "haiku"];
const short = (id: string) => id.replace(/-/g, "").slice(0, 8);

function problemText(error: unknown): string {
  if (error instanceof ApiProblem)
    return error.detail ? `${error.title}: ${error.detail}` : error.title;
  return "Something went wrong. Try again.";
}

/** The last prompt sent, for ArrowUp in the empty composer; none when its stored copy is redacted. */
function lastPrompt(state: TranscriptState): string | null {
  const sending = state.sending.at(-1);
  if (sending) return sending.text;
  const sent = state.entries.findLast((entry) => entry.kind === "user");
  return sent?.kind === "user" && !sent.redacted ? sent.text : null;
}

/** The Allow once or Deny button of request `id`'s card, when it can be pressed. */
function answerButton(id: string, which: "allow" | "deny"): HTMLButtonElement | null {
  const card = Array.from(document.querySelectorAll<HTMLElement>("[data-request-id]")).find(
    (element) => element.dataset.requestId === id,
  );
  const button = card?.querySelector<HTMLButtonElement>(`[data-shortcut="${which}"]`);
  return button && !button.disabled ? button : null;
}

/** Whether a modal (the command palette, the shortcut sheet, a confirm dialog) holds the keys. */
function modalOpen(): boolean {
  return document.querySelector('[aria-modal="true"]') !== null;
}

/**
 * The chat's keys anywhere on the page (AC-234.29): Ctrl/Cmd+Alt+Enter allows and
 * Ctrl/Cmd+Alt+Backspace denies the oldest pending request, through its card's button (inert when
 * none); Shift+Esc focuses the composer.
 */
function useChatKeys(pending: readonly string[], composer: { current: HTMLElement | null }) {
  const oldest = useRef(pending[0]);
  useEffect(() => {
    oldest.current = pending[0];
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // A key held down, mid-composition, already taken (the `/` menu's Enter) or under a modal
      // is not the chat's: it never answers a request.
      if (event.repeat || event.isComposing || event.defaultPrevented || modalOpen()) return;
      if (event.key === "Escape" && event.shiftKey) {
        event.preventDefault();
        composer.current?.focus({ preventScroll: true });
        return;
      }
      if (!event.altKey || !(event.ctrlKey || event.metaKey)) return;
      const which = event.key === "Enter" ? "allow" : event.key === "Backspace" ? "deny" : null;
      const button = which && oldest.current ? answerButton(oldest.current, which) : null;
      if (!button) return;
      event.preventDefault();
      button.click();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [composer]);
}

/**
 * The chat view of a session `hub web` drives (D10, `/agent-sessions/:id`): the snapshot and the
 * log, then the live stream; the transcript, todos, cost meter, status, permission cards and the
 * composer; Close while live, Delete once ended.
 */
export function AgentSessionScreen() {
  const { agentSessionId = "" } = useParams();
  // Keyed by id: another session starts from an empty transcript.
  return <AgentSessionChat key={agentSessionId} agentSessionId={agentSessionId} />;
}

function AgentSessionChat({ agentSessionId }: { agentSessionId: string }) {
  const navigate = useNavigate();
  const snapshot = useAgentSession(agentSessionId);
  const capabilities = useCapabilities();
  const transcript = useAgentTranscript(agentSessionId);
  const commands = useAgentSessionCommands(agentSessionId);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const follow = useStickToBottom(scroller);
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const pending = pendingPermissions(transcript.state);
  useChatKeys(pending, composer);
  const setComposer = useCallback((element: HTMLTextAreaElement | null) => {
    composer.current = element;
  }, []);

  const problem = snapshot.error ?? transcript.error;
  const session = snapshot.data;
  const { state } = transcript;
  const crumbs = [
    { label: "Sessions", href: "/sessions" },
    { label: session?.title ?? `Agent session ${short(agentSessionId)}` },
  ];

  if (problem) {
    const unavailable = sessionControlUnavailable(problem, null);
    return (
      <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
        <Breadcrumbs items={crumbs} />
        <h1 className="ah-h1" style={{ fontSize: 20 }}>
          Agent session
        </h1>
        {unavailable ? (
          <Banner tone="warning" boxed>
            <b>{unavailable.title}.</b> {unavailable.detail}
          </Banner>
        ) : problem.status === 404 ? (
          <EmptyState icon="square-terminal" title={problem.title}>
            {problem.detail ?? "No session hub web drives has this id. It may have been deleted."}{" "}
            <AppLink href="/sessions">Back to Sessions</AppLink>
          </EmptyState>
        ) : (
          <ProblemError
            title="Could not load this session"
            detail={problem.detail}
            status={problem.status}
            type={problem.type}
            onRetry={() => {
              void snapshot.refetch();
              transcript.retry();
            }}
          />
        )}
      </div>
    );
  }

  // A reload after a stream reset keeps the transcript on screen until the new one is built.
  if (!session || (transcript.loading && state.lastSeq === 0)) {
    return (
      <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
        <Breadcrumbs items={crumbs} />
        <Skeleton lines={6} />
      </div>
    );
  }

  const status = state.status ?? session.status;
  const ended = isTerminal(status);
  const mode = state.mode ?? session.mode;
  const model = state.model ?? session.model ?? null;
  const models = capabilities.data?.models ?? DEFAULT_MODELS;
  const cloud = session.kind === "cloud";

  const act = (action: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    void action()
      .catch((cause: unknown) => {
        setActionError(problemText(cause));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  // One fixed-height column (AC-234.16): the header and the composer stay put, the transcript
  // between them is the only scroller.
  return (
    <div className="as-page">
      <header className="as-header">
        <div className="as-column ah-stack">
          <Breadcrumbs items={crumbs} />
          <div className="ah-row ah-wrap" style={{ gap: 12 }}>
            <Icon name="square-terminal" size="lg" style={{ color: "var(--text-subtle)" }} />
            <h1 className="ah-h1" style={{ fontSize: 20 }}>
              {session.title ?? "Untitled session"}
            </h1>
            <AgentStatusBadge status={status} endReason={state.endReason ?? session.end_reason} />
            <span className="ah-grow" />
            {session.claude_session_id && (
              <AppLink
                className="ah-row ah-small"
                style={{ gap: 4 }}
                href={`/sessions/${encodeURIComponent(session.claude_session_id)}`}
              >
                <Icon name="activity" size="sm" />
                Observed session {short(session.claude_session_id)}
              </AppLink>
            )}
            {ended ? (
              <Button
                size="sm"
                variant="ghost"
                icon="file-x"
                disabled={busy}
                onClick={() => {
                  setConfirmDelete(true);
                }}
              >
                Delete session
              </Button>
            ) : (
              <Button
                size="sm"
                icon="x"
                disabled={busy}
                onClick={() => {
                  act(commands.close);
                }}
              >
                Close session
              </Button>
            )}
          </div>
          <div className="ah-row ah-wrap ah-small ah-muted" style={{ gap: 12 }}>
            <span>
              {session.project} › <b className="ah-mono">{session.workdir_label}</b>
            </span>
            <span>
              {modeLabel(mode)}
              {model ? ` · ${model}` : ""}
            </span>
            <CostMeter meter={state.meter} />
          </div>
          {actionError && (
            <p className="ah-small as-error" role="alert">
              {actionError}
            </p>
          )}
          {transcript.streaming && (
            <ReconnectBanner connected={transcript.health.closedSince === null} />
          )}
          <TodoList items={state.todos} />
        </div>
      </header>
      {/* The chords answer the oldest pending request: its card names them (AC-234.29). */}
      <OldestPendingContext.Provider value={pending[0]}>
        <Transcript
          state={state}
          onAnswerPermission={ended ? undefined : commands.answer}
          scrollerRef={setScroller}
          follow={follow}
        />
      </OldestPendingContext.Provider>
      <footer className="as-footer">
        <div className="as-column">
          <Composer
            status={status}
            mode={mode}
            model={model}
            models={models}
            onSend={(text) => transcript.send(text, commands.send)}
            onInterrupt={commands.interrupt}
            onSettings={commands.settings}
            onSending={follow.pin}
            maxBytes={DEFAULT_MESSAGE_MAX_BYTES}
            commands={state.slashCommands}
            draftId={agentSessionId}
            focusOnOpen={pending.length === 0}
            lastPrompt={lastPrompt(state)}
            inputRef={setComposer}
            disabledReason={cloud ? "A cloud session is driven from claude.ai." : null}
          />
        </div>
      </footer>
      {confirmDelete && (
        <ConfirmDialog
          title="Delete this session?"
          confirmLabel="Delete"
          consequences={[
            "Its stored conversation is removed from the hub web database.",
            "The observed session in Sessions stays.",
          ]}
          onCancel={() => {
            setConfirmDelete(false);
          }}
          onConfirm={() => {
            setConfirmDelete(false);
            act(async () => {
              await commands.remove();
              await navigate("/sessions");
            });
          }}
        />
      )}
    </div>
  );
}
