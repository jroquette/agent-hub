import { useEffect } from "react";
import { Navigate, useNavigate, useParams } from "react-router";

import { Banner, Button, ProblemError, Skeleton, Tooltip } from "../../components";
import { useApi } from "../../lib/api";
import { useScope } from "../../lib/scope";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { useDiscuss, useDiscussTarget } from "../../shell/discuss";
import type { DiscussStarter } from "../../shell/discuss";
import { ADD_ENVIRONMENT_ID, EnvironmentsSection } from "../hub-config/EnvironmentsSection";
import { addEnvironmentPath, environmentsPage } from "../hub-config/environments";
import { SavedToast, UncommittedNotice, useSaveNotices } from "../hub-config/notices";
import { AskBlocked } from "../hub-config/parts";
import { KnowledgeProjectIndex } from "../knowledge-index";
import { sessionControlUnavailable } from "../sessions-list/control";
import { useAgentCapabilities } from "../sessions-list/queries";
import "../hub-config/hub-config.css";

/** Where the sidebar's Environments goes with All projects in scope: a project picker. */
export const ENVIRONMENTS_PICKER = "/environments";

const BRIEF = [
  "Environments and services live in the hub: the team's in hub.json (committed, changed through a hub PR), this developer's own in hub.local.json (never committed). hub.local.json may add environments and endpoints on its own environments, and may only make a team environment's access stricter (write → ask → read).",
  "Use ./hub env list, ./hub env add|set|remove and ./hub env service add|remove (--local for hub.local.json); they validate before writing. After a hub.json change run ./hub sync, show me the diff and ask me before you push or open the PR.",
  "Credentials are names only (an AWS profile name, variable names, an env file path): never write a value.",
].join("\n");

const STARTERS: readonly DiscussStarter[] = [
  {
    label: "Describe our environments",
    message:
      "Look at this project's repos and their config files, then propose the environments and services we should declare, with their addresses. Show me the proposal before you change anything.",
  },
  {
    label: "Find a missing endpoint",
    message:
      "Which services have no address in an environment where they run? Check the repos' config and propose the missing endpoints.",
  },
];

/** `/projects/:project/environments`: where the project's systems run and what agents may do. */
export function EnvironmentsScreen() {
  const { project = "" } = useParams();
  const config = useApi("/api/v1/projects/{project}/config", { path: { project } });
  const notices = useSaveNotices();
  const navigate = useNavigate();
  const { setOpen, addReference } = useDiscuss();
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const blocked = unavailable ? `${unavailable.title}. ${unavailable.detail}` : null;
  useDiscussTarget({
    key: `environments:${project}`,
    project,
    kind: "Environments",
    title: project,
    path: "hub.json",
    brief: BRIEF,
    starters: STARTERS,
  });
  useEffect(() => {
    document.title = `Environments · ${project}`;
  }, [project]);

  const view = config.data;
  const origin = { returnTo: environmentsPage(project), returnLabel: "Environments" };
  let body;
  if (config.isError) {
    body = (
      <ProblemError
        title={
          config.error.status === 404
            ? "Project not found"
            : "Could not read this project's hub.json"
        }
        detail={`${config.error.detail ?? ""} Run ./hub doctor in the hub for the line to fix.`}
        status={config.error.status}
        onRetry={() => void config.refetch()}
      />
    );
  } else if (!view) {
    body = (
      <div className="ah-stack" style={{ gap: 12 }} aria-busy="true">
        <Skeleton height={220} />
        <Skeleton height={160} />
      </div>
    );
  } else {
    body = <EnvironmentsSection view={view} onSaved={notices.onSaved} origin={origin} />;
  }

  return (
    <AskBlocked.Provider value={blocked}>
      <div className="ah-page" style={{ gap: 16 }}>
        <Breadcrumbs
          items={[
            { label: "Portfolio", href: "/" },
            { label: project, href: `/projects/${encodeURIComponent(project)}` },
            { label: "Environments" },
          ]}
        />
        <header className="ah-config-head">
          <div className="ah-stack" style={{ gap: 4, minWidth: 0 }}>
            <h1 className="ah-h1">Environments</h1>
            <p className="ah-muted ah-small" style={{ margin: 0 }}>
              Where this project&apos;s systems run, what agents may do in each, and how to reach
              each repo&apos;s services there.
            </p>
          </div>
          <div className="ah-row" style={{ gap: 8, flexShrink: 0 }}>
            <Tooltip label={blocked ?? undefined}>
              <Button
                icon="message-square"
                disabled={blocked !== null}
                onClick={() => {
                  setOpen(true);
                }}
              >
                Ask Claude about environments
              </Button>
            </Tooltip>
            {/* One primary: with no environment yet, the empty state holds it. */}
            {view && view.environments.environments.length > 0 && (
              <Button
                id={ADD_ENVIRONMENT_ID}
                variant="primary"
                icon="plus"
                onClick={() => {
                  void navigate(addEnvironmentPath(project), { state: origin });
                }}
              >
                Add environment
              </Button>
            )}
          </div>
        </header>
        {view && view.local_file.problems.length > 0 && (
          <Banner
            tone="warning"
            action={
              <Button
                size="sm"
                icon="message-square"
                disabled={blocked !== null}
                onClick={() => {
                  addReference({
                    id: "config:hub.local.json",
                    label: "hub.local.json problems",
                    source: "hub.local.json",
                    quote: view.local_file.problems.join("\n"),
                  });
                }}
              >
                Ask Claude to fix it
              </Button>
            }
          >
            Your hub.local.json has a problem, so only the team&apos;s environments show:{" "}
            {view.local_file.problems.join("; ")}
          </Banner>
        )}
        {notices.teamChanged && (
          <UncommittedNotice blocked={blocked} onDismiss={notices.dismissTeamChanged} />
        )}
        {body}
        <SavedToast message={notices.saved} />
      </div>
    </AskBlocked.Provider>
  );
}

/** `/environments`: the project in scope's environments, else a project picker. */
export function EnvironmentsPickerScreen() {
  const [scope] = useScope();
  if (scope !== null) return <Navigate to={environmentsPage(scope)} replace />;
  return (
    <KnowledgeProjectIndex
      title="Environments"
      intro="Each project's environments (your machine, staging, production), what agents may do in each, and where each repo's services run. Open a project to see and change them."
      caption="Projects and their environments"
      emptyLine="Register a hub to declare its environments."
      tip="To come straight here, choose a project in the top bar."
      href={environmentsPage}
    />
  );
}
