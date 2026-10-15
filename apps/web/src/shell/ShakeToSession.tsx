import { useCallback, useEffect, useRef, useState } from "react";
import { useMatch } from "react-router";

import { matchingWorkdir, servedCheckout } from "../lib/devCheckout";
import { captureScreen } from "../lib/screenCapture";
import { useScope } from "../lib/scope";
import { createShakeDetector } from "../lib/shake";
import { sessionControlUnavailable } from "../screens/sessions-list/AgentSessionList";
import type {
  DriverCapabilities,
  ShakeScreenshot,
  Workdir,
} from "../screens/sessions-list/NewSessionDialog";
import { useAgentCapabilities, useWorkdirs } from "../screens/sessions-list/queries";
import { StartSessionDialog } from "../screens/sessions-list/StartSessionDialog";

/** Shown when the served checkout is not a listed folder, or outside `make dev` (O8). */
export const LIVE_RELOAD_NOTE = "Live reload needs make dev in a listed folder";

interface Opened {
  project: string;
  workdirs: readonly Workdir[];
  capabilities: DriverCapabilities;
  screenshot: ShakeScreenshot;
  workdirId: string | null;
}

/** The project of the route (`projects/:project`, `features/:project/…`, `workflows/:project/…`), else the scope (Q2). */
function useShakeProject(): string | null {
  const [scope] = useScope();
  const project = useMatch("/projects/:project/*")?.params.project;
  const feature = useMatch("/features/:project/*")?.params.project;
  const workflow = useMatch("/workflows/:project/*")?.params.project;
  return project ?? feature ?? workflow ?? scope;
}

/**
 * Shake the mouse to start a session (AGH-260): the shell mounts this only while the setting is on.
 * A shake captures the screen first, then opens "New session" with the screenshot. It does nothing
 * without a project, while session control is unavailable, without folders, or while a dialog is open.
 */
export function ShakeToSession() {
  const project = useShakeProject();
  const capabilities = useAgentCapabilities();
  const caps = capabilities.data;
  const canDrive =
    caps !== undefined && sessionControlUnavailable(capabilities.error, caps) === null;
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
      document.querySelector('[role="dialog"]') !== null
    )
      return;
    busy.current = true;
    const shot = await captureScreen();
    const workdirId = await matchingWorkdir(servedCheckout(), now.folders);
    setOpened({
      project: now.project,
      workdirs: now.folders,
      capabilities: now.caps,
      screenshot: shot.ok ? { dataUrl: shot.dataUrl } : { failed: true },
      workdirId,
    });
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
      initialMode={live ? "acceptEdits" : undefined}
      note={live ? undefined : LIVE_RELOAD_NOTE}
      onClose={() => {
        busy.current = false;
        setOpened(null);
      }}
    />
  );
}
