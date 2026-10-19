import "./agent-session.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import {
  AppLink,
  Banner,
  ConfirmDialog,
  EmptyState,
  Icon,
  ProblemError,
  Skeleton,
} from "../../components";
import { ApiProblem } from "../../lib/api";
import { useMessageScreenshots, useScreenshot } from "../../lib/screenshotCopy";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { sessionControlUnavailable } from "../sessions-list/control";
import { StartSessionDialog } from "../sessions-list/StartSessionDialog";
import { Composer, DEFAULT_MESSAGE_MAX_BYTES } from "./Composer";
import { OldestPendingContext } from "./PermissionCard";
import { backgroundTasks, liveActivity, turnSteps } from "./liveActivity";
import { FeatureChip } from "../features/FeatureChip";
import { BackgroundCard, BackgroundChip, BackgroundPanel } from "./BackgroundTasks";
import { LiveActivityBar, StepsPanel, StepsToggle } from "./LiveActivityBar";
import { readStored, writeStored } from "../../lib/storage";
import { CostMeter } from "./CostMeter";
import { ChangedFilesChip, FilesPanel, useReviewed } from "./FilesPanel";
import { useResolvedThreads } from "./ReviewDiff";
import { reviewThreads } from "./review";
import { SessionMenu } from "./SessionMenu";
import {
  isTerminal,
  useAgentSession,
  useAgentSessionCommands,
  useSessionAbout,
  useAgentTranscript,
  useCapabilities,
} from "./queries";
import { AgentStatusBadge, ReconnectBanner } from "./SessionStatus";
import { TodoList } from "./TodoList";
import { Transcript } from "./Transcript";
import {
  changedFiles,
  modeLabel,
  pendingPermissions,
  lastMessageAt,
  resumable,
  runningTasks,
  type TranscriptState,
} from "./model";
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

/** Whether the Steps drawer was left open, in this browser. */
const STEPS_OPEN_KEY = "ah.chat.steps";

/** Ctrl/Cmd+Alt+. shows or hides the Steps drawer, from anywhere on the page (the key's code:
 * Option+. types "≥" on a Mac). */
function useStepsKey(toggle: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.repeat || event.isComposing || event.defaultPrevented || modalOpen()) return;
      if (!event.altKey || !(event.ctrlKey || event.metaKey) || event.code !== "Period") return;
      event.preventDefault();
      toggle();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [toggle]);
}

/**
 * The chat view of a session `hub web` drives (D10, `/agent-sessions/:id`): the snapshot and the
 * log, then the live stream; the transcript, todos, cost meter, status, permission cards and the
 * composer; Close while live, Delete once ended. A message to an ended session resumes it in
 * place, on the same page and log.
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
  const screenshotUrl = useScreenshot(agentSessionId);
  const messageScreenshots = useMessageScreenshots(agentSessionId);
  const commands = useAgentSessionCommands(agentSessionId);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [forking, setForking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [backgroundOpen, setBackgroundOpen] = useState(false);
  // The Steps drawer opens as it was last left, in this browser.
  const [liveOpen, setLiveOpen] = useState(() => readStored(STEPS_OPEN_KEY) === "open");
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const stepsTrigger = useRef<HTMLElement | null>(null);
  // Restored on load, the drawer leaves the keyboard in the composer.
  const [stepsFocus, setStepsFocus] = useState(false);
  // The file a card in the conversation asked for; the nonce re-opens it in an open drawer.
  const [filePick, setFilePick] = useState<{ path: string | null; nonce: number }>({
    path: null,
    nonce: 0,
  });
  const review = useReviewed(agentSessionId);
  const resolvedThreads = useResolvedThreads(agentSessionId);
  const closeFiles = useCallback(() => {
    setFilesOpen(false);
  }, []);
  // One drawer at a time: opening one closes the others.
  const closePanels = useCallback(() => {
    setFilesOpen(false);
    setLiveOpen(false);
    setBackgroundOpen(false);
  }, []);
  const setBackground = useCallback((open: boolean) => {
    setBackgroundOpen(open);
    if (open) {
      setFilesOpen(false);
      setLiveOpen(false);
    }
  }, []);
  const closeBackground = useCallback(() => {
    setBackgroundOpen(false);
  }, []);
  const setSteps = useCallback((open: boolean) => {
    writeStored(STEPS_OPEN_KEY, open ? "open" : "closed");
    setLiveOpen(open);
    if (open) {
      stepsTrigger.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setStepsFocus(true);
      setFilesOpen(false);
      setBackgroundOpen(false);
    } else {
      // Focus goes back to what opened it, else to the composer.
      (stepsTrigger.current ?? composer.current)?.focus({ preventScroll: true });
    }
  }, []);
  const closeLive = useCallback(() => {
    setSteps(false);
  }, [setSteps]);
  const toggleSteps = useCallback(() => {
    setSteps(!liveOpen);
  }, [liveOpen, setSteps]);
  useStepsKey(toggleSteps);
  const openFile = useCallback((path: string | null) => {
    setFilePick((before) => ({ path, nonce: before.nonce + 1 }));
    setLiveOpen(false);
    setBackgroundOpen(false);
    setFilesOpen(true);
  }, []);
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const follow = useStickToBottom(scroller);
  // The chords answer tool permissions only (AC-234.29): a question or plan card ahead of them is skipped.
  const pending = pendingPermissions(transcript.state).filter(
    (id) => transcript.state.permissions[id]?.requestKind === "tool",
  );
  useChatKeys(pending, composer);
  const setComposer = useCallback((element: HTMLTextAreaElement | null) => {
    composer.current = element;
  }, []);

  const problem = snapshot.error ?? transcript.error;
  const session = snapshot.data;
  const { name, feature } = useSessionAbout(session);
  const { state } = transcript;
  const { tools, permissions } = state;
  // Only the calls and their permissions change the list, not every streamed text delta.
  const files = useMemo(() => changedFiles({ tools, permissions }), [tools, permissions]);
  const threads = useMemo(
    () => reviewThreads(state.entries, state.sending),
    [state.entries, state.sending],
  );
  const crumbs = [
    { label: "Sessions", href: "/sessions" },
    { label: name ?? `Agent session ${short(agentSessionId)}` },
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
  const activity = liveActivity(state);
  const steps = turnSteps(state);
  const tasks = backgroundTasks(state);
  const ended = isTerminal(status);
  const mode = state.mode ?? session.mode;
  const model = state.model ?? session.model ?? null;
  const models = capabilities.data?.models ?? DEFAULT_MODELS;
  const cloud = session.kind === "cloud";
  const endReason = state.endReason ?? session.end_reason;
  const canResume = resumable(session, endReason);
  // A message resumes an ended session in place; Fork… starts a new conversation from it (AC-234.15).
  const caps = capabilities.data;
  const canFork = ended && canResume && caps?.available === true;

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
              {name ?? "Untitled session"}
            </h1>
            {feature && <FeatureChip project={feature.project} slug={feature.slug} />}
            <AgentStatusBadge
              status={status}
              endReason={state.endReason ?? session.end_reason}
              background={runningTasks(state)}
            />
            <span className="ah-grow" />
            <BackgroundChip
              tasks={tasks}
              open={backgroundOpen}
              onToggle={() => {
                setBackground(!backgroundOpen);
              }}
            />
            <StepsToggle
              steps={steps}
              open={liveOpen}
              onToggle={() => {
                setSteps(!liveOpen);
              }}
            />
            {files.length > 0 && (
              <ChangedFilesChip
                files={files}
                review={review}
                open={filesOpen}
                onToggle={() => {
                  if (filesOpen) setFilesOpen(false);
                  else openFile(null);
                }}
              />
            )}
            {session.observed_session_id ? (
              <AppLink
                className="ah-row ah-small"
                href={`/sessions/${encodeURIComponent(session.observed_session_id)}`}
                style={{ gap: 4, fontWeight: 500 }}
                title="Timeline, tools, errors and raw events of this session"
              >
                <Icon name="activity" size="sm" />
                Events
              </AppLink>
            ) : (
              <span
                className="ah-row ah-small ah-subtle"
                style={{ gap: 4 }}
                title="The hub's hooks have sent no event for this session yet. They run only in a folder whose .claude/settings.json has them (the hub folder), so a session started in a repo folder has no timeline."
              >
                <Icon name="activity" size="sm" />
                No events
              </span>
            )}
            <SessionMenu
              busy={busy}
              onFork={
                canFork
                  ? () => {
                      setForking(true);
                    }
                  : undefined
              }
              onClose={
                ended
                  ? undefined
                  : () => {
                      act(commands.close);
                    }
              }
              onDelete={
                ended
                  ? () => {
                      setConfirmDelete(true);
                    }
                  : undefined
              }
            />
          </div>
          <div className="ah-row ah-wrap ah-small ah-muted" style={{ gap: 12 }}>
            <span>
              {session.project} ›{" "}
              <b className="ah-mono as-workdir-label">{session.workdir_label}</b>
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
      {/* The chords answer the oldest pending tool permission: its card names them (AC-234.29). */}
      <OldestPendingContext.Provider value={pending[0]}>
        <Transcript
          state={state}
          onAnswerPermission={ended ? undefined : commands.answer}
          scrollerRef={setScroller}
          follow={follow}
          screenshotUrl={screenshotUrl}
          messageScreenshots={messageScreenshots}
          onActivityOpen={closePanels}
          files={files}
          reviewed={review.reviewed}
          onOpenFile={openFile}
          footer={
            <BackgroundCard
              tasks={tasks}
              since={lastMessageAt(state)}
              onOpen={() => {
                setBackground(true);
              }}
            />
          }
          sidePanel={
            backgroundOpen ? (
              <BackgroundPanel
                tasks={tasks}
                onClose={closeBackground}
                onStop={cloud || ended ? undefined : commands.stopTask}
              />
            ) : liveOpen && steps.end !== null ? (
              <StepsPanel steps={steps} onClose={closeLive} focusOnOpen={stepsFocus} />
            ) : filesOpen ? (
              <FilesPanel
                files={files}
                sessionId={agentSessionId}
                onClose={closeFiles}
                workdirLabel={session.workdir_label}
                review={review}
                initialPath={filePick.path}
                pickNonce={filePick.nonce}
                comments={{
                  threads,
                  resolved: resolvedThreads,
                  // A comment is a message to this session's Claude: it answers in the chat too.
                  onComment:
                    cloud || (ended && !canResume)
                      ? undefined
                      : (text) => transcript.send(text, (message) => commands.send(message)),
                }}
              />
            ) : undefined
          }
        />
      </OldestPendingContext.Provider>
      <footer className="as-footer">
        <div className="as-column">
          <LiveActivityBar
            activity={activity}
            open={activity?.phase === "background" ? backgroundOpen : liveOpen}
            onToggle={() => {
              // Between turns the bar is about the background tasks: it opens their drawer.
              if (activity?.phase === "background") setBackground(!backgroundOpen);
              else setSteps(!liveOpen);
            }}
          />
          <Composer
            status={status}
            mode={mode}
            model={model}
            models={models}
            onSend={(text, screenshots) =>
              transcript.send(text, (message) => commands.send(message, screenshots), screenshots)
            }
            acceptsImages={!cloud}
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
            resumable={canResume}
          />
        </div>
      </footer>
      {forking && caps && (
        <StartSessionDialog
          project={session.project}
          capabilities={caps}
          forkOf={{ ...session, status, mode, model }}
          onClose={() => {
            setForking(false);
          }}
        />
      )}
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
