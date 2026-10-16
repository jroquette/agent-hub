/* Driving sessions from Sessions (AGH-165, AC-234.8): New session in the header, why it is unavailable, cloud guidance. */
import { useState } from "react";

import { Banner, Button, ProblemError } from "../../components";
import { CloudPanel } from "./CloudPanel";
import { sessionControlUnavailable } from "./control";
import {
  useAgentCapabilities,
  useAgentSessions,
  useCloudSessions,
  useServedFolder,
  useWorkdirs,
} from "./queries";
import { StartSessionDialog } from "./StartSessionDialog";

/** The driven sessions of `scope`, whether this machine can start one, and in which project. */
export function useDriving(scope: string | null, projects: readonly string[]) {
  const [chosen, setChosen] = useState<string | null>(null);
  const list = useAgentSessions(scope);
  const capabilities = useAgentCapabilities();
  const problem = list.error ?? capabilities.error;
  const caps = capabilities.data;
  const canDrive = caps !== undefined && sessionControlUnavailable(problem, caps) === null;
  // Under make dev/live/playground, sessions start in the served checkout's project unless another
  // is picked, so what they edit is what the dev server shows.
  const served = useServedFolder(projects, canDrive);
  const picked = chosen !== null && projects.includes(chosen) ? chosen : null;
  const project = picked ?? served.project ?? scope ?? projects[0] ?? null;
  const workdirs = useWorkdirs(project, canDrive);
  const pick = projects.length > 1 && (!scope || served.project !== null) ? setChosen : null;
  return { list, capabilities, problem, caps, canDrive, project, projects, pick, workdirs, served };
}

type Driving = ReturnType<typeof useDriving>;

/** "New session" for the page header, with the project to start in when no scope is set. */
export function NewSessionControl({ driving }: { driving: Driving }) {
  const [dialog, setDialog] = useState(false);
  const { caps, canDrive, project, pick, workdirs, served } = driving;
  const live = served.project !== null && project === served.project;
  const folders = workdirs.data?.items;
  if (!canDrive || !caps || project === null || !folders) return null;
  return (
    <>
      {pick && (
        <label className="ah-row ah-small" style={{ gap: 6 }}>
          <span className="ah-subtle">Start sessions in</span>
          <select
            className="ah-input as-select"
            value={project}
            onChange={(event) => {
              pick(event.target.value);
            }}
          >
            {driving.projects.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      )}
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
          workdirs={folders}
          capabilities={caps}
          initialWorkdirId={live ? (served.workdirId ?? undefined) : undefined}
          initialMode={live ? "acceptEdits" : undefined}
          onClose={() => {
            setDialog(false);
          }}
        />
      )}
    </>
  );
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
