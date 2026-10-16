import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { rememberScreenshot } from "../../lib/screenshotCopy";
import type { PermissionMode } from "../agent-session/model";
import { agentSessionHref } from "./control";
import {
  NewSessionDialog,
  type DriverCapabilities,
  type ShakeScreenshot,
  type Workdir,
} from "./NewSessionDialog";
import { useCreateAgentSession, useResumable } from "./queries";

export interface StartSessionDialogProps {
  project: string;
  workdirs: readonly Workdir[];
  capabilities: DriverCapabilities;
  screenshot?: ShakeScreenshot | undefined;
  initialWorkdirId?: string | undefined;
  initialMode?: PermissionMode | undefined;
  note?: string | undefined;
  onClose: () => void;
}

/**
 * "New session" wired to the API: it loads the folder's resumable sessions, creates the session, then
 * opens its chat view. The sessions list and the shell's shake (AGH-260) both mount it; a screenshot
 * sent with the first prompt is kept in memory for the chat view.
 */
export function StartSessionDialog({
  project,
  workdirs,
  capabilities,
  screenshot,
  initialWorkdirId,
  initialMode,
  note,
  onClose,
}: StartSessionDialogProps) {
  const navigate = useNavigate();
  const [resumeFor, setResumeFor] = useState<string | null>(null);
  const resumable = useResumable(project, resumeFor);
  // A shake's screenshot leaves the mutation cache with the dialog, not gcTime later.
  const create = useCreateAgentSession({ release: screenshot !== undefined });
  const { reset } = create;

  useEffect(() => {
    reset();
  }, [reset]);

  return (
    <NewSessionDialog
      project={project}
      workdirs={workdirs}
      capabilities={capabilities}
      resumable={resumable.data?.items}
      onWorkdirChange={setResumeFor}
      pending={create.isPending}
      error={create.error}
      screenshot={screenshot}
      initialWorkdirId={initialWorkdirId}
      initialMode={initialMode}
      note={note}
      onSubmit={(body) => {
        create.mutate(body, {
          onSuccess: (created) => {
            // The image sent, marked up or not, is the one the chat view shows.
            if (body.screenshot)
              rememberScreenshot(created.id, `data:image/png;base64,${body.screenshot.data}`);
            onClose();
            void navigate(agentSessionHref(created.id));
          },
        });
      }}
      onCancel={onClose}
    />
  );
}
