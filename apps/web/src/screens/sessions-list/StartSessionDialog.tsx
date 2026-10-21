import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { rememberMessageScreenshots, rememberScreenshot } from "../../lib/screenshotCopy";
import type { PermissionMode } from "../agent-session/model";
import { agentSessionHref } from "./control";
import {
  NewSessionDialog,
  type AgentSession,
  type DriverCapabilities,
  type ShakeScreenshot,
  type Workdir,
} from "./NewSessionDialog";
import { useCreateAgentSession, useWorkdirs } from "./queries";

export interface StartSessionDialogProps {
  /** The project to start in, and `workdirs`, its folders. */
  project: string;
  /** The projects "Where" may switch to; another one's folders load here. */
  projects?: readonly string[] | undefined;
  /** Not needed to fork, which starts in its session's own folder. */
  workdirs?: readonly Workdir[] | undefined;
  capabilities: DriverCapabilities;
  screenshot?: ShakeScreenshot | undefined;
  initialWorkdirId?: string | undefined;
  initialMode?: PermissionMode | undefined;
  note?: string | undefined;
  /** An ended session to fork (AC-234.15). */
  forkOf?: AgentSession | undefined;
  title?: string | undefined;
  initialPrompt?: string | undefined;
  onClose: () => void;
}

/**
 * "New session" wired to the API: it loads the folders of a project chosen in "Where", creates the
 * session, then opens its chat view. The sessions list and the shell's shake (AGH-260) both mount it; a screenshot
 * sent with the first prompt is kept in memory for the chat view.
 */
export function StartSessionDialog({
  project: firstProject,
  projects,
  workdirs: firstWorkdirs,
  capabilities,
  screenshot,
  initialWorkdirId,
  initialMode,
  note,
  forkOf,
  title,
  initialPrompt,
  onClose,
}: StartSessionDialogProps) {
  const navigate = useNavigate();
  const [project, setProject] = useState(firstProject);
  const other = useWorkdirs(project, project !== firstProject);
  // A shake's screenshot leaves the mutation cache with the dialog, not gcTime later.
  const create = useCreateAgentSession({ release: screenshot !== undefined });
  const { reset } = create;

  useEffect(() => {
    reset();
  }, [reset]);

  return (
    <NewSessionDialog
      project={project}
      projects={projects}
      onProjectChange={setProject}
      workdirs={project === firstProject ? firstWorkdirs : other.data?.items}
      workdirsProblem={
        project !== firstProject && other.error
          ? `Could not list the working folders: ${other.error.detail ?? other.error.title}`
          : undefined
      }
      capabilities={capabilities}
      pending={create.isPending}
      error={create.error}
      screenshot={screenshot}
      initialWorkdirId={initialWorkdirId}
      initialMode={initialMode}
      note={note}
      forkOf={forkOf}
      title={title}
      initialPrompt={initialPrompt}
      onSubmit={(body) => {
        create.mutate(body, {
          onSuccess: (created) => {
            // The images sent, marked up or not, are the ones the chat view shows: the capture,
            // then the images added to the first prompt (its record is the log's first).
            const png = (data: string) => `data:image/png;base64,${data}`;
            if (body.screenshot) rememberScreenshot(created.id, png(body.screenshot.data));
            if (body.screenshots?.length)
              rememberMessageScreenshots(created.id, 1, [
                ...(body.screenshot ? [png(body.screenshot.data)] : []),
                ...body.screenshots.map((image) => png(image.data)),
              ]);
            onClose();
            void navigate(agentSessionHref(created.id));
          },
        });
      }}
      onCancel={onClose}
    />
  );
}
