import "./agent-session.css";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { ProblemError, Skeleton } from "../../components";
import { ApiProblem } from "../../lib/api";
import { Composer, DEFAULT_MESSAGE_MAX_BYTES } from "./Composer";
import { CostMeter } from "./CostMeter";
import { liveActivity, turnSteps } from "./liveActivity";
import { LiveActivityBar, StepsPanel } from "./LiveActivityBar";
import { OldestPendingContext } from "./PermissionCard";
import {
  isTerminal,
  useAgentSession,
  useAgentSessionCommands,
  useAgentTranscript,
  useCapabilities,
  type AgentTranscript,
} from "./queries";
import { AgentStatusBadge, ReconnectBanner } from "./SessionStatus";
import { useSlashOptions } from "./SlashMenu";
import { TodoList } from "./TodoList";
import { Transcript } from "./Transcript";
import { pendingPermissions, resumable } from "./model";
import { useStickToBottom } from "./useStickToBottom";

const DEFAULT_MODELS = ["default", "opus", "sonnet", "haiku"];

export interface DiscussChatProps {
  agentSessionId: string;
  /** The session is gone (deleted, or `hub web` forgot it): the caller starts a new one. */
  onGone: () => void;
  /** Turns the typed text into the message sent (the Discuss panel quotes its references). */
  prepareMessage?: ((text: string) => string) | undefined;
  /** The message was accepted: the Discuss panel drops the references it carried. */
  onSent?: (() => void) | undefined;
  /** Keeps the session's permission mode fixed: no mode switch (a scenario investigation, whose
   * allowed writes and `./hub` commands must keep asking, E-13, E-15). */
  lockMode?: boolean | undefined;
  /** False keeps focus where the page put it (a reopened scenario investigation). */
  focusComposer?: boolean | undefined;
  /** Where the session's status and cost show, when the caller has a header for them. */
  metaSlot?: HTMLElement | null | undefined;
  /** Shown inside the composer, above the message (the references it will carry). */
  composerAccessory?: ReactNode;
}

export interface DiscussChatViewProps extends DiscussChatProps {
  /** The session's transcript, opened by the caller when it reads it too (the Studio preview). */
  transcript: AgentTranscript;
}

/**
 * The chat of a driven session, compact enough for a side panel: the same transcript, permission
 * cards and composer as the full chat page, without its header actions and page-wide keys.
 */
export function DiscussChat(props: DiscussChatProps) {
  const transcript = useAgentTranscript(props.agentSessionId);
  return <DiscussChatView {...props} transcript={transcript} />;
}

/** The compact chat over a transcript the caller already holds (one stream per session). */
export function DiscussChatView({
  agentSessionId,
  onGone,
  transcript,
  prepareMessage,
  onSent,
  lockMode = false,
  focusComposer = true,
  metaSlot,
  composerAccessory,
}: DiscussChatViewProps) {
  const snapshot = useAgentSession(agentSessionId);
  const capabilities = useCapabilities();
  const commands = useAgentSessionCommands(agentSessionId);
  const slashOptions = useSlashOptions(snapshot.data?.project, transcript.state.slashCommands);
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const [stepsOpen, setStepsOpen] = useState(false);
  const follow = useStickToBottom(scroller);
  const session = snapshot.data;
  const { state } = transcript;

  const problem = snapshot.error ?? transcript.error;
  const gone = problem instanceof ApiProblem && problem.status === 404;
  useEffect(() => {
    if (gone) onGone();
  }, [gone, onGone]);
  if (gone) return null;
  if (problem) {
    const known = problem instanceof ApiProblem ? problem : null;
    return (
      <div style={{ padding: 12 }}>
        <ProblemError
          compact
          title="Could not load this conversation"
          detail={known?.detail ?? (problem instanceof Error ? problem.message : undefined)}
          status={known?.status}
          type={known?.type}
          onRetry={() => {
            void snapshot.refetch();
            transcript.retry();
          }}
        />
      </div>
    );
  }
  if (!session || (transcript.loading && state.lastSeq === 0)) {
    return (
      <div style={{ padding: 12 }}>
        <Skeleton lines={4} />
      </div>
    );
  }

  const status = state.status ?? session.status;
  const activity = liveActivity(state);
  const steps = turnSteps(state);
  const ended = isTerminal(status);
  const endReason = state.endReason ?? session.end_reason;
  const pending = pendingPermissions(state).filter(
    (id) => state.permissions[id]?.requestKind === "tool",
  );
  const meta = (
    <>
      <AgentStatusBadge status={status} endReason={endReason} />
      <CostMeter meter={state.meter} compact />
    </>
  );
  return (
    <div className="as-page">
      {metaSlot === undefined ? (
        <div className="ah-row ah-wrap ah-small ah-discuss-meta">{meta}</div>
      ) : (
        metaSlot && createPortal(meta, metaSlot)
      )}
      {transcript.streaming && (
        <ReconnectBanner connected={transcript.health.closedSince === null} />
      )}
      <OldestPendingContext.Provider value={pending[0]}>
        <Transcript
          state={state}
          onAnswerPermission={ended ? undefined : commands.answer}
          scrollerRef={setScroller}
          follow={follow}
          sidePanel={
            stepsOpen && steps.end !== null ? (
              <StepsPanel
                steps={steps}
                onClose={() => {
                  setStepsOpen(false);
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
            open={stepsOpen}
            onToggle={() => {
              setStepsOpen(!stepsOpen);
            }}
          />
          <TodoList items={state.todos} />
          <Composer
            status={status}
            mode={state.mode ?? session.mode}
            model={state.model ?? session.model ?? null}
            models={capabilities.data?.models ?? DEFAULT_MODELS}
            onSend={async (text, screenshots, files) => {
              await transcript.send(
                prepareMessage ? prepareMessage(text) : text,
                (message) => commands.send(message, screenshots, files),
                screenshots,
                files,
              );
              onSent?.();
            }}
            onInterrupt={commands.interrupt}
            onSettings={commands.settings}
            onSending={follow.pin}
            maxBytes={DEFAULT_MESSAGE_MAX_BYTES}
            commands={slashOptions}
            draftId={agentSessionId}
            focusOnOpen={focusComposer && pending.length === 0}
            resumable={resumable(session, endReason)}
            modeLocked={lockMode || session.restricted === true}
            acceptsImages
            acceptsFiles
            accessory={composerAccessory}
          />
        </div>
      </footer>
    </div>
  );
}
