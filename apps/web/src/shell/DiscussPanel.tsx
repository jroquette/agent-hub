import "./discuss.css";

import { useCallback, useState } from "react";

import { AppLink, Banner, Button, EmptyState, Icon, IconButton } from "../components";
import { ApiProblem } from "../lib/api";
import { Composer, DEFAULT_MESSAGE_MAX_BYTES } from "../screens/agent-session/Composer";
import { DiscussChat } from "../screens/agent-session/DiscussChat";
import type { PermissionMode } from "../screens/agent-session/model";
import { sessionControlUnavailable } from "../screens/sessions-list/control";
import {
  useAgentCapabilities,
  useCreateAgentSession,
  useWorkdirs,
} from "../screens/sessions-list/queries";
import { discussPrompt, useDiscuss, type DiscussTarget } from "./discuss";

const DEFAULT_MODELS = ["default", "opus", "sonnet", "haiku"];
const storageKey = (target: DiscussTarget) => `ah.discuss.session.${target.key}`;

function readStored(target: DiscussTarget): string | null {
  try {
    return window.localStorage.getItem(storageKey(target));
  } catch {
    return null;
  }
}

function writeStored(target: DiscussTarget, id: string | null) {
  try {
    if (id === null) window.localStorage.removeItem(storageKey(target));
    else window.localStorage.setItem(storageKey(target), id);
  } catch {
    // Without storage the conversation is only forgotten on reload.
  }
}

/**
 * The right-hand panel to talk with Claude about what is on screen: one conversation per
 * artifact, a session `hub web` drives in the project's hub folder. Edits Claude proposes ask
 * through the same permission cards as the full chat.
 */
export function DiscussPanel() {
  const { target, open, setOpen } = useDiscuss();
  if (!open) return null;
  return (
    <aside className="ah-discuss" aria-label="Discuss with Claude">
      <header className="ah-discuss-head">
        <Icon name="message-square" size="sm" />
        <div className="ah-discuss-title">
          <b>Discuss with Claude</b>
          <span className="ah-small ah-muted">
            {target ? `${target.kind} · ${target.title}` : "Nothing on this screen yet"}
          </span>
        </div>
        <span className="ah-grow" />
        <IconButton
          icon="x"
          label="Close panel"
          onClick={() => {
            setOpen(false);
          }}
        />
      </header>
      {target ? (
        <DiscussBody key={target.key} target={target} />
      ) : (
        <EmptyState icon="message-square" title="Open something to discuss">
          A feature's spec, research, plan, criteria or tickets, a workflow, a skill, an agent or a
          hook. The conversation follows what is on screen.
        </EmptyState>
      )}
    </aside>
  );
}

function DiscussBody({ target }: { target: DiscussTarget }) {
  const [sessionId, setSessionId] = useState<string | null>(() => readStored(target));
  const forget = useCallback(() => {
    writeStored(target, null);
    setSessionId(null);
  }, [target]);

  return (
    <div className="ah-discuss-body">
      <div className="ah-row ah-small ah-discuss-meta">
        {target.path && <span className="ah-mono ah-muted ah-discuss-path">{target.path}</span>}
        <span className="ah-grow" />
        {sessionId && (
          <>
            <AppLink href={`/agent-sessions/${encodeURIComponent(sessionId)}`}>Full chat</AppLink>
            <Button size="sm" variant="ghost" icon="plus" onClick={forget}>
              New conversation
            </Button>
          </>
        )}
      </div>
      {sessionId ? (
        <DiscussChat agentSessionId={sessionId} onGone={forget} />
      ) : (
        <StartDiscussion
          target={target}
          onStarted={(id) => {
            writeStored(target, id);
            setSessionId(id);
          }}
        />
      )}
    </div>
  );
}

function StartDiscussion({
  target,
  onStarted,
}: {
  target: DiscussTarget;
  onStarted: (id: string) => void;
}) {
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const canDrive = capabilities.data !== undefined && unavailable === null;
  const workdirs = useWorkdirs(target.project, canDrive);
  const hub = workdirs.data?.items.find((w) => w.kind === "hub") ?? null;
  const create = useCreateAgentSession();
  const [mode, setMode] = useState<PermissionMode>("default");
  const [model, setModel] = useState<string | null>(null);

  if (unavailable) {
    return (
      <div className="ah-discuss-note">
        <Banner tone="warning" boxed>
          <b>{unavailable.title}.</b> {unavailable.detail}
        </Banner>
      </div>
    );
  }
  const reason = !canDrive
    ? "Checking whether this machine can drive Claude…"
    : workdirs.isPending
      ? "Looking for the hub folder…"
      : hub === null
        ? `Project ${target.project} has no hub folder to work in.`
        : null;

  return (
    <div className="as-page">
      <div className="ah-discuss-note ah-small ah-muted">
        Ask about this {target.kind.toLowerCase()}, challenge it, or ask Claude to change it.
        Claude works in the hub folder of <b>{target.project}</b>; every file edit asks you first
        unless you switch the mode to accept edits.
      </div>
      <div className="ah-grow" />
      <footer className="as-footer">
        <div className="as-column">
          <Composer
            status={null}
            mode={mode}
            model={model}
            models={capabilities.data?.models ?? DEFAULT_MODELS}
            onSend={async (text) => {
              if (!hub) return;
              const session = await create.mutateAsync({
                project: target.project,
                workdir_id: hub.workdir_id,
                mode,
                fork: false,
                ...(model && model !== "default" ? { model } : {}),
                prompt: discussPrompt(target, text),
              });
              onStarted(session.id);
            }}
            onInterrupt={() => undefined}
            onSettings={(change) => {
              if (change.mode) setMode(change.mode);
              if (change.model) setModel(change.model);
              return undefined;
            }}
            maxBytes={DEFAULT_MESSAGE_MAX_BYTES}
            draftId={`discuss.${target.key}`}
            focusOnOpen
            disabledReason={reason}
          />
          {create.error instanceof ApiProblem && (
            <p className="ah-small as-error" role="alert">
              {create.error.detail ?? create.error.title}
            </p>
          )}
        </div>
      </footer>
    </div>
  );
}
