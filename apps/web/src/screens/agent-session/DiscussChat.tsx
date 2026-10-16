import "./agent-session.css";

import { useEffect, useState } from "react";

import { Skeleton } from "../../components";
import { ApiProblem } from "../../lib/api";
import { Composer, DEFAULT_MESSAGE_MAX_BYTES } from "./Composer";
import { CostMeter } from "./CostMeter";
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
import { TodoList } from "./TodoList";
import { Transcript } from "./Transcript";
import { pendingPermissions } from "./model";
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
}: DiscussChatViewProps) {
  const snapshot = useAgentSession(agentSessionId);
  const capabilities = useCapabilities();
  const commands = useAgentSessionCommands(agentSessionId);
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
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
    return (
      <p className="ah-small as-error" role="alert" style={{ padding: 12 }}>
        {problem.title}
      </p>
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
  const ended = isTerminal(status);
  const pending = pendingPermissions(state).filter(
    (id) => state.permissions[id]?.requestKind === "tool",
  );
  return (
    <div className="as-page">
      <div className="ah-row ah-wrap ah-small ah-discuss-meta">
        <AgentStatusBadge status={status} endReason={state.endReason ?? session.end_reason} />
        <CostMeter meter={state.meter} />
      </div>
      {transcript.streaming && (
        <ReconnectBanner connected={transcript.health.closedSince === null} />
      )}
      <TodoList items={state.todos} />
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
            mode={state.mode ?? session.mode}
            model={state.model ?? session.model ?? null}
            models={capabilities.data?.models ?? DEFAULT_MODELS}
            onSend={async (text) => {
              await transcript.send(prepareMessage ? prepareMessage(text) : text, commands.send);
              onSent?.();
            }}
            onInterrupt={commands.interrupt}
            onSettings={commands.settings}
            onSending={follow.pin}
            maxBytes={DEFAULT_MESSAGE_MAX_BYTES}
            commands={state.slashCommands}
            draftId={agentSessionId}
            focusOnOpen={pending.length === 0}
          />
        </div>
      </footer>
    </div>
  );
}
