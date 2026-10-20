import { fileBody, type MessageFile } from "../lib/messageFile";
import { screenshotBody } from "../lib/pastedImage";
import { rememberMessageScreenshots, rememberScreenshot } from "../lib/screenshotCopy";
import type { PermissionMode } from "../screens/agent-session/model";
import { sessionControlUnavailable } from "../screens/sessions-list/control";
import {
  useAgentCapabilities,
  useCreateAgentSession,
  useWorkdirs,
} from "../screens/sessions-list/queries";
import type { DiscussTarget } from "./discuss";

const storageKey = (target: DiscussTarget) => `ah.discuss.session.${target.key}`;

/** The conversation this browser keeps for a target, if any. */
export function readDiscussSession(target: DiscussTarget): string | null {
  try {
    return window.localStorage.getItem(storageKey(target));
  } catch {
    return null;
  }
}

/** Keeps (or, with null, forgets) a target's conversation: the panel opens on it. */
export function rememberDiscussSession(target: DiscussTarget, id: string | null): void {
  try {
    if (id === null) window.localStorage.removeItem(storageKey(target));
    else window.localStorage.setItem(storageKey(target), id);
  } catch {
    // Without storage the conversation is only forgotten on reload.
  }
}

/** The screen's capture that rides on a first message (the panel's whole-screen target). */
export interface ScreenCapture {
  dataUrl: string;
  body: { media_type: "image/png"; data: string };
}

export interface StartDiscussionRequest {
  target: DiscussTarget;
  /** What Claude gets, already composed (`discussPrompt`). */
  prompt: string;
  /** The images (PNG data URLs) and files attached to the first message. */
  images?: readonly string[] | undefined;
  files?: readonly MessageFile[] | undefined;
  capture?: ScreenCapture | null | undefined;
  mode?: PermissionMode | undefined;
  model?: string | null | undefined;
}

export interface StartDiscussion {
  /** Sessions cannot run on this machine: the title and detail to show. */
  unavailable: { title: string; detail: string } | null;
  /** Why nothing can start yet (checking, no hub folder), or null. */
  reason: string | null;
  pending: boolean;
  error: unknown;
  /** Starts the conversation in the project's hub folder and returns its session id. */
  start: (request: StartDiscussionRequest) => Promise<string | null>;
}

/**
 * Starting a conversation with Claude about a target, in the project's hub folder: whether this
 * machine can drive Claude, where it works, and the `POST /agent-sessions` with the first
 * message's images and files. The images are kept in this browser for the first bubble.
 */
export function useStartDiscussion(project: string | null): StartDiscussion {
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const canDrive = capabilities.data !== undefined && unavailable === null;
  const workdirs = useWorkdirs(project, canDrive);
  const hub = workdirs.data?.items.find((w) => w.kind === "hub") ?? null;
  const create = useCreateAgentSession();

  const reason = !canDrive
    ? "Checking whether this machine can drive Claude…"
    : workdirs.isPending
      ? "Looking for the hub folder…"
      : hub === null
        ? `Project ${project ?? ""} has no hub folder to work in.`
        : null;

  const start = async ({
    target,
    prompt,
    images = [],
    files = [],
    capture = null,
    mode = "default",
    model = null,
  }: StartDiscussionRequest): Promise<string | null> => {
    if (!hub) return null;
    const session = await create.mutateAsync({
      project: target.project,
      workdir_id: hub.workdir_id,
      mode,
      fork: false,
      ...(model && model !== "default" ? { model } : {}),
      ...(capture ? { screenshot: capture.body } : {}),
      ...(images.length > 0 ? { screenshots: images.map(screenshotBody) } : {}),
      ...(files.length > 0 ? { files: files.map(fileBody) } : {}),
      prompt,
    });
    if (capture) rememberScreenshot(session.id, capture.dataUrl);
    // The first prompt is the log's first record: its bubble shows the capture, then the images.
    if (images.length > 0)
      rememberMessageScreenshots(session.id, 1, [...(capture ? [capture.dataUrl] : []), ...images]);
    return session.id;
  };

  return {
    unavailable: unavailable ? { title: unavailable.title, detail: unavailable.detail } : null,
    reason,
    pending: create.isPending,
    error: create.error,
    start,
  };
}
