import { useCallback, useEffect, useRef, useState } from "react";
import { useMatch } from "react-router";

import { matchingWorkdir, servedCheckout } from "../lib/devCheckout";
import { captureScreen } from "../lib/screenCapture";
import { useScope } from "../lib/scope";
import { createShakeDetector } from "../lib/shake";
import { sessionControlUnavailable } from "../screens/sessions-list/control";
import type {
  DriverCapabilities,
  ShakeScreenshot,
  Workdir,
} from "../screens/sessions-list/NewSessionDialog";
import {
  useAgentCapabilities,
  useProjects,
  useServedFolder,
  useWorkdirs,
} from "../screens/sessions-list/queries";
import { StartSessionDialog } from "../screens/sessions-list/StartSessionDialog";

/** Shown when the served checkout is not a listed folder, or outside `make dev` (O8). */
export const LIVE_RELOAD_NOTE = "Live reload needs make dev in a listed folder";

/** Any open dialog, a confirmation (`alertdialog`) included: a shake never stacks on one. */
function dialogOpen(): boolean {
  return document.querySelector('[role="dialog"], [role="alertdialog"]') !== null;
}

interface Opened {
  project: string;
  workdirs: readonly Workdir[];
  capabilities: DriverCapabilities;
  screenshot: ShakeScreenshot;
  workdirId: string | null;
}

/**
 * The project of a shake: under `make dev` or `make live`, the one that lists the served checkout;
 * else the route's (`projects/:project`, `features/:project/…`, `workflows/:project/…`), else the
 * scope (Q2), else the first registered project, as Sessions' New session picks it, so a shake works
 * on every screen, "All projects" and Settings included.
 */
function useShakeProject(canDrive: boolean): string | null {
  const [scope] = useScope();
  const projects = useProjects();
  const names = (projects.data?.items ?? []).map((item) => item.name);
  const served = useServedFolder(names, canDrive).project;
  const project = useMatch("/projects/:project/*")?.params.project;
  const feature = useMatch("/features/:project/*")?.params.project;
  const workflow = useMatch("/workflows/:project/*")?.params.project;
  return served ?? project ?? feature ?? workflow ?? scope ?? names[0] ?? null;
}

/**
 * Shake the mouse to start a session (AGH-260): the shell mounts this only while the setting is on.
 * A shake captures the screen first, then opens "New session" with the screenshot. It does nothing
 * when no project is registered, while session control is unavailable, without folders, or while a
 * dialog is open.
 */
export function ShakeToSession() {
  const capabilities = useAgentCapabilities();
  const caps = capabilities.data;
  const canDrive =
    caps !== undefined && sessionControlUnavailable(capabilities.error, caps) === null;
  const project = useShakeProject(canDrive);
  const workdirs = useWorkdirs(project, canDrive);
  const folders = workdirs.data?.items;
  const [opened, setOpened] = useState<Opened | null>(null);
  const busy = useRef(false);

  const latest = useRef({ project, caps, canDrive, folders });
  useEffect(() => {
    latest.current = { project, caps, canDrive, folders };
  });

  const onShake = useCallback(async () => {
    const now = latest.current;
    if (
      busy.current ||
      now.project === null ||
      !now.canDrive ||
      now.caps === undefined ||
      !now.folders ||
      now.folders.length === 0 ||
      dialogOpen()
    )
      return;
    const { project, caps, folders } = now;
    busy.current = true;
    let opening = false;
    try {
      const shot = await captureScreen();
      // No match is the honest fallback when the id cannot be derived (no crypto.subtle).
      const workdirId = await matchingWorkdir(servedCheckout(), folders).catch(() => null);
      // A dialog that opened during the capture wins: the shot is dropped.
      if (dialogOpen()) return;
      setOpened({
        project,
        workdirs: folders,
        capabilities: caps,
        screenshot: shot.ok ? { dataUrl: shot.dataUrl } : { failed: true },
        workdirId,
      });
      opening = true;
    } catch {
      // A shake that fails before opening opens nothing; the next shake tries again.
    } finally {
      if (!opening) busy.current = false;
    }
  }, []);

  useEffect(() => {
    const detect = createShakeDetector();
    const onMove = (event: PointerEvent) => {
      const shaken = detect({
        x: event.clientX,
        t: event.timeStamp,
        pointerType: event.pointerType,
        buttons: event.buttons,
      });
      if (shaken) void onShake();
    };
    window.addEventListener("pointermove", onMove);
    return () => {
      window.removeEventListener("pointermove", onMove);
    };
  }, [onShake]);

  if (!opened) return null;
  const live = opened.workdirId !== null;
  return (
    <StartSessionDialog
      project={opened.project}
      workdirs={opened.workdirs}
      capabilities={opened.capabilities}
      screenshot={opened.screenshot}
      initialWorkdirId={opened.workdirId ?? undefined}
      initialMode={live ? "auto" : undefined}
      note={live ? undefined : LIVE_RELOAD_NOTE}
      onClose={() => {
        busy.current = false;
        setOpened(null);
      }}
    />
  );
}
