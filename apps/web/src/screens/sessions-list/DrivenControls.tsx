/* Driving sessions from Sessions (AGH-165, AC-234.8): New session in the header, why it is unavailable, cloud guidance. */
import { useCallback, useState, type ReactNode } from "react";

import { Banner, Button, ProblemError } from "../../components";
import { CloudPanel } from "./CloudPanel";
import { resumable, sessionControlUnavailable } from "./control";
import {
  useAgentCapabilities,
  useAgentSessions,
  useCloudSessions,
  useWorkdirs,
  type AgentSession,
} from "./queries";
import { isDriven, type SectionRow } from "./sections";
import { StartSessionDialog } from "./StartSessionDialog";

/**
 * The driven sessions of `scope`, whether this machine can start one, and the project New session
 * opens on; its "Where" switches to another of `projects` when no scope is set (AC-234.14).
 */
export function useDriving(scope: string | null, projects: readonly string[]) {
  const project = scope ?? projects[0] ?? null;
  const list = useAgentSessions(scope);
  const capabilities = useAgentCapabilities();
  const problem = list.error ?? capabilities.error;
  const caps = capabilities.data;
  const canDrive = caps !== undefined && sessionControlUnavailable(problem, caps) === null;
  const workdirs = useWorkdirs(project, canDrive);
  const choices = scope ? [] : projects;
  return { list, capabilities, problem, caps, canDrive, project, choices, workdirs };
}

type Driving = ReturnType<typeof useDriving>;

/** "New session" for the page header; the dialog's "Where" picks the project. */
export function NewSessionControl({ driving }: { driving: Driving }) {
  const [dialog, setDialog] = useState(false);
  const { caps, canDrive, project, choices, workdirs } = driving;
  const folders = workdirs.data?.items;
  if (!canDrive || !caps || project === null || !folders) return null;
  return (
    <>
      <Button
        variant="primary"
        icon="plus"
        onClick={() => {
          setDialog(true);
        }}
      >
        New session
      </Button>
      {dialog && (
        <StartSessionDialog
          project={project}
          projects={choices}
          workdirs={folders}
          capabilities={caps}
          onClose={() => {
            setDialog(false);
          }}
        />
      )}
    </>
  );
}

/**
 * Resume on the rows and tiles of ended or failed driven sessions, twins included (AC-234.15):
 * `button(row)` is the control, `dialog` the prefilled New session it opens.
 */
export function useResume(driving: Driving) {
  const [target, setTarget] = useState<AgentSession | null>(null);
  const { caps, canDrive } = driving;
  const items = driving.list.data?.items;
  // Stable while the list is: the memoised tiles and the table columns do not render again.
  const button = useCallback(
    (row: SectionRow): ReactNode => {
      const id = isDriven(row) ? row.id : row.agent_session_id;
      const session = isDriven(row) ? row : items?.find((a) => a.id === id);
      if (!canDrive || !session || !resumable(session)) return null;
      return (
        <Button
          size="sm"
          icon="play"
          aria-label={`Resume ${session.title ?? "Untitled session"}`}
          // The row or tile around it opens the chat on click: Resume opens the dialog only.
          onClick={(event) => {
            event.stopPropagation();
            setTarget(session);
          }}
        >
          Resume
        </Button>
      );
    },
    [canDrive, items],
  );
  const dialog = target && caps && (
    <StartSessionDialog
      project={target.project}
      capabilities={caps}
      resume={target}
      onClose={() => {
        setTarget(null);
      }}
    />
  );
  return { button, dialog };
}

/** Why sessions cannot be driven here (401, container, 503, no claude), or a failed list or folder read. */
export function DrivenBanner({ driving }: { driving: Driving }) {
  const { problem, caps, canDrive, workdirs, list, capabilities } = driving;
  const unavailable = sessionControlUnavailable(problem, caps);
  if (unavailable)
    return (
      <Banner tone="warning" boxed>
        <b>{unavailable.title}.</b> {unavailable.detail}
      </Banner>
    );
  if (problem)
    return (
      <ProblemError
        title="Could not load the agent sessions"
        detail={problem.detail}
        status={problem.status}
        type={problem.type}
        onRetry={() => {
          void list.refetch();
          void capabilities.refetch();
        }}
        compact
      />
    );
  if (workdirs.error && canDrive)
    return (
      <ProblemError
        title="Could not list the working folders"
        detail={workdirs.error.detail}
        status={workdirs.error.status}
        onRetry={() => {
          void workdirs.refetch();
        }}
        compact
      />
    );
  return null;
}

/** The cloud guidance, collapsed below the sections (O-5). */
export function CloudSessions({ driving }: { driving: Driving }) {
  const { caps, canDrive, project, workdirs } = driving;
  const cloudSessions = useCloudSessions(project, canDrive && caps?.cloud === true);
  if (!canDrive || !caps || project === null || !workdirs.data) return null;
  return (
    <details>
      <summary className="ah-small">Cloud sessions</summary>
      <CloudPanel key={project} capabilities={caps} sessions={cloudSessions.data?.items ?? []} />
    </details>
  );
}
