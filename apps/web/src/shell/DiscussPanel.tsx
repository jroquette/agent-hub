import "./discuss.css";

import { useCallback, useRef, useState } from "react";

import { AppLink, Banner, Button, EmptyState, Icon, IconButton } from "../components";
import { usePanelDismiss } from "../components/usePanelDismiss";
import { ApiProblem } from "../lib/api";
import { captureScreen } from "../lib/screenCapture";
import type { MessageFile } from "../lib/messageFile";
import { Composer, DEFAULT_MESSAGE_MAX_BYTES } from "../screens/agent-session/Composer";
import { DiscussChat } from "../screens/agent-session/DiscussChat";
import {
  DRAWER_MIN,
  useDrawerWidth,
  type DrawerWidth,
  type PanelBounds,
} from "../screens/agent-session/DrawerResize";
import type { PermissionMode } from "../screens/agent-session/model";
import { useAgentCapabilities } from "../screens/sessions-list/queries";
import {
  discussPrompt,
  referencedMessage,
  useDiscuss,
  type DiscussReference,
  type DiscussTarget,
} from "./discuss";
import {
  readDiscussSession,
  rememberDiscussSession,
  useStartDiscussion,
  type ScreenCapture,
} from "./discussSession";
import { readScreenText } from "./screenContext";

const DEFAULT_MODELS = ["default", "opus", "sonnet", "haiku"];

/** The width the owner chose for the panel, kept in this browser. */
export const DISCUSS_WIDTH_KEY = "ah.discuss.width";
/** Docked from this viewport width; below it the panel lays over the page. */
const DOCKED_FROM = 1280;
/** The page keeps at least this much beside a docked panel. */
const PAGE_MIN = 640;
const PANEL_MAX = 720;
/** Beside an overlaid panel, this much of the page stays in view. */
const OVERLAY_GAP = 96;

/**
 * The widest the panel may be in a viewport `viewport` wide, beside a sidebar `sidebar` wide: docked,
 * it leaves the page 640 px and stops at 720; over the page, it leaves 96 px of it in view.
 */
export function discussMax(viewport: number, sidebar: number): number {
  const max =
    viewport >= DOCKED_FROM
      ? Math.min(PANEL_MAX, viewport - sidebar - PAGE_MIN)
      : viewport - OVERLAY_GAP;
  return Math.max(DRAWER_MIN, max);
}

const discussBounds = (): PanelBounds => {
  const sidebar = document.getElementById("main")?.getBoundingClientRect().left ?? 0;
  return { right: window.innerWidth, max: discussMax(window.innerWidth, sidebar) };
};

/** The Discuss panel's width: the shell sets it on its frame, so the page makes room for it. */
export function useDiscussWidth(): DrawerWidth {
  return useDrawerWidth({
    storageKey: DISCUSS_WIDTH_KEY,
    cssVar: "--discuss-chosen",
    label: "Resize the Discuss panel",
    defaultWidth: 480,
    bounds: discussBounds,
  });
}
/**
 * The right-hand panel to talk with Claude about what is on screen: one conversation per
 * artifact, a session `hub web` drives in the project's hub folder. Edits Claude proposes ask
 * through the same permission cards as the full chat.
 */
export function DiscussPanel({ resize }: { resize?: DrawerWidth | undefined }) {
  const { open } = useDiscuss();
  if (!open) return null;
  return <OpenPanel resize={resize} />;
}

/** Docked beside the page from this width: Escape closes it only from inside it there. */
const docked = () =>
  typeof window.matchMedia === "function" && window.matchMedia("(min-width: 1280px)").matches;

function OpenPanel({ resize }: { resize: DrawerWidth | undefined }) {
  const { target, setOpen } = useDiscuss();
  const panel = useRef<HTMLElement>(null);
  usePanelDismiss(
    panel,
    () => {
      setOpen(false);
    },
    {
      fromAnywhere: () => !docked(),
      fallbackFocus: () => document.querySelector<HTMLElement>("[data-discuss-toggle]"),
      keepTypedEscape: true,
    },
  );
  return (
    <aside ref={panel} className="ah-discuss" id="ah-discuss" aria-label="Discuss with Claude">
      {resize && <div {...resize.handle} aria-controls="ah-discuss" />}
      <header className="ah-discuss-head">
        <Icon name="message-square" size="sm" />
        <div className="ah-discuss-title">
          <b>Discuss with Claude</b>
          <span className="ah-small ah-muted">
            {target ? `${target.kind} · ${target.title}` : "Nothing on this screen yet"}
          </span>
        </div>
        <span className="ah-grow" />
        {resize && (
          <IconButton
            icon="maximize-2"
            label={resize.wide ? "Narrow panel" : "Widen panel"}
            aria-pressed={resize.wide}
            className="ah-discuss-widen"
            onClick={resize.toggleWide}
          />
        )}
        <IconButton
          icon="x"
          label="Close panel"
          onClick={() => {
            setOpen(false);
          }}
        />
      </header>
      {target ? (
        // The owner session is read after the target: the body starts over once it is known.
        <DiscussBody key={`${target.key}:${target.ownerSession?.id ?? ""}`} target={target} />
      ) : (
        <EmptyState icon="message-square" title="Open something to discuss">
          Register a project to talk with Claude about any screen. The conversation follows what is
          on screen.
        </EmptyState>
      )}
    </aside>
  );
}

/**
 * The parts the owner pointed at, waiting for the next message: each chip shows its part on hover
 * and can be dropped before sending.
 */
function ReferenceChips({
  references,
  onRemove,
}: {
  references: readonly DiscussReference[];
  onRemove: (id: string) => void;
}) {
  if (references.length === 0) return null;
  return (
    <div className="ah-discuss-refs" role="group" aria-label="References for the next message">
      <span className="ah-small ah-subtle">Next message is about</span>
      {references.map((reference) => (
        <span key={reference.id} className="ah-discuss-ref" title={reference.quote}>
          <Icon name="bookmark" size="sm" />
          <span className="ah-discuss-ref-label">{reference.label}</span>
          <IconButton
            size="sm"
            icon="x"
            label={`Remove the reference ${reference.label}`}
            onClick={() => {
              onRemove(reference.id);
            }}
          />
        </span>
      ))}
    </div>
  );
}

function DiscussBody({ target }: { target: DiscussTarget }) {
  const { references, removeReference, clearReferences } = useDiscuss();
  const owner = target.ownerSession ?? null;
  // The owner's session comes first; the panel's own conversation is one click away.
  const [sessionId, setSessionId] = useState<string | null>(
    () => owner?.id ?? readDiscussSession(target),
  );
  const onOwner = owner !== null && sessionId === owner.id;
  const forget = useCallback(() => {
    if (!onOwner) rememberDiscussSession(target, null);
    setSessionId(null);
  }, [target, onOwner]);

  return (
    <div className="ah-discuss-body">
      {owner && (
        <div className="ah-row ah-small ah-discuss-meta">
          <Icon name="square-terminal" size="sm" />
          {onOwner ? (
            <span className="ah-discuss-path" title={owner.name}>
              <span className="ah-muted">Feature session: </span>
              {owner.name}
            </span>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setSessionId(owner.id);
              }}
            >
              Back to the feature session
            </Button>
          )}
        </div>
      )}
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
      <ReferenceChips references={references} onRemove={removeReference} />
      {sessionId ? (
        <DiscussChat
          agentSessionId={sessionId}
          onGone={forget}
          prepareMessage={(text) => referencedMessage(references, text)}
          onSent={clearReferences}
        />
      ) : (
        <StartDiscussion
          target={target}
          references={references}
          onStarted={(id) => {
            rememberDiscussSession(target, id);
            setSessionId(id);
            clearReferences();
          }}
        />
      )}
    </div>
  );
}

interface ScreenRead {
  text: string;
  screenshot: ScreenCapture | null;
}

/** What the screen shows when the conversation starts: its main column's text and a screenshot. */
async function readScreen(): Promise<ScreenRead> {
  const main = document.getElementById("main");
  const text = readScreenText(main);
  // A capture that fails or times out still sends the text: the screenshot is a bonus.
  const shot = main ? await captureScreen(main) : null;
  return {
    text,
    screenshot: shot?.ok
      ? {
          dataUrl: shot.dataUrl,
          body: {
            media_type: "image/png",
            data: shot.dataUrl.slice(shot.dataUrl.indexOf(",") + 1),
          },
        }
      : null,
  };
}

function withScreenText(brief: string | undefined, text: string): string {
  const shown = text === "" ? "(the screen shows no text)" : text;
  return [brief, "What the screen shows, as text:", "<screen>", shown, "</screen>"]
    .filter(Boolean)
    .join("\n");
}

function StartDiscussion({
  target,
  references,
  onStarted,
}: {
  target: DiscussTarget;
  references: readonly DiscussReference[];
  onStarted: (id: string) => void;
}) {
  const capabilities = useAgentCapabilities();
  const {
    unavailable,
    reason,
    pending,
    error,
    start: startSession,
  } = useStartDiscussion(target.project);
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
  // The first message may carry images and files of its own, after the screen's capture.
  const start = async (
    text: string,
    images: readonly string[] = [],
    files: readonly MessageFile[] = [],
  ) => {
    const screen = target.screen ? await readScreen() : null;
    const id = await startSession({
      target,
      prompt: discussPrompt(
        screen ? { ...target, brief: withScreenText(target.brief, screen.text) } : target,
        referencedMessage(references, text),
      ),
      images,
      files,
      capture: screen?.screenshot,
      mode,
      model,
    });
    if (id) onStarted(id);
  };

  return (
    <div className="as-page">
      <div className="ah-discuss-note ah-small ah-muted">
        {target.screen ? (
          <>
            Ask about what this screen shows. Your first message takes its text and a screenshot
            along; select text on the page and press Discuss selection to point at one part.
          </>
        ) : (
          <>
            Ask about this {target.kind.toLowerCase()}, challenge it, or ask Claude to change it.
            Point at one part with its Discuss button, or select text on the page and press Discuss
            selection.
          </>
        )}{" "}
        Claude works in the hub folder of <b>{target.project}</b>; every file edit asks you first
        unless you switch the mode to accept edits.
      </div>
      {target.starters && target.starters.length > 0 && (
        <div className="ah-discuss-starters" role="group" aria-label="Start with">
          {target.starters.map((starter) => (
            <Button
              key={starter.label}
              size="sm"
              icon="message-square"
              disabled={reason !== null || pending}
              onClick={() => {
                // A failure shows below the composer (create.error); nothing else to do here.
                start(starter.message).catch(() => undefined);
              }}
            >
              {starter.label}
            </Button>
          ))}
        </div>
      )}
      <div className="ah-grow" />
      <footer className="as-footer">
        <div className="as-column">
          <Composer
            status={null}
            mode={mode}
            model={model}
            models={capabilities.data?.models ?? DEFAULT_MODELS}
            onSend={start}
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
            acceptsImages
            acceptsFiles
          />
          {error instanceof ApiProblem && (
            <p className="ah-small as-error" role="alert">
              {error.detail ?? error.title}
            </p>
          )}
        </div>
      </footer>
    </div>
  );
}
