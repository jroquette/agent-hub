import { useEffect, useId, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import {
  Banner,
  Button,
  Icon,
  Money,
  OptionRow,
  ProblemError,
  Skeleton,
  StatusBadge,
  Tooltip,
} from "../../components";
import { apiKey, apiPost, useApi } from "../../lib/api";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { useAgentSession, useAgentSessionCommands } from "../agent-session/queries";
import { sessionControlUnavailable } from "../sessions-list/control";
import { useAgentCapabilities } from "../sessions-list/queries";
import { ACCESS_LOOK, count, environmentsPage, refusalOf } from "../hub-config/environments";
import type { HubConfigView } from "../hub-config/environments";
import { countByStatus, discoverPath, reviewPath } from "./discovery";
import type { EnvironmentDiscovery } from "./discovery";
import "../hub-config/hub-config.css";

const POLL_MS = 3_000;

/** `/projects/:project/environments/discover`: ask Claude to find the services in the repos. */
export function DiscoverScreen() {
  const { project = "" } = useParams();
  const [params] = useSearchParams();
  const discovery = params.get("discovery");
  const config = useApi("/api/v1/projects/{project}/config", { path: { project } });
  useEffect(() => {
    document.title = `Find services with Claude · ${project}`;
  }, [project]);

  let body;
  if (config.isError)
    body = (
      <ProblemError
        title="Could not read this project's configuration"
        detail={config.error.detail}
        status={config.error.status}
        onRetry={() => void config.refetch()}
      />
    );
  else if (!config.data) body = <Skeleton height={320} />;
  else if (discovery) body = <Progress project={project} discoveryId={discovery} />;
  else body = <DiscoverForm view={config.data} />;

  return (
    <div className="ah-page" style={{ gap: 16 }}>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: project, href: `/projects/${encodeURIComponent(project)}` },
          { label: "Environments", href: environmentsPage(project) },
          { label: "Find services with Claude" },
        ]}
      />
      <header className="ah-stack" style={{ gap: 4 }}>
        <h1 className="ah-h1">Find services with Claude</h1>
        <p className="ah-muted" style={{ margin: 0, maxWidth: "72ch" }}>
          Claude reads the repos&apos; config and proposes environments, services and their
          addresses. It changes nothing: you review each proposal and choose what to add.
        </p>
      </header>
      {body}
    </div>
  );
}

function DiscoverForm({ view }: { view: HubConfigView }) {
  const id = useId();
  const navigate = useNavigate();
  const client = useQueryClient();
  const project = view.project;
  const environments = view.environments.environments;
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const blocked = unavailable ? `${unavailable.title}. ${unavailable.detail}` : null;
  const [repos, setRepos] = useState<Set<string>>(new Set(view.repos.map((repo) => repo.dir)));
  const [picked, setPicked] = useState<Set<string>>(
    new Set(environments.map((environment) => environment.name)),
  );
  const [suggest, setSuggest] = useState(true);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const toggle = (set: Set<string>, value: string, update: (next: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    update(next);
  };

  const start = () => {
    setPending(true);
    setFailure(null);
    apiPost(
      "/api/v1/projects/{project}/environment-discoveries",
      {
        repos: view.repos.map((repo) => repo.dir).filter((dir) => repos.has(dir)),
        environments: environments
          .map((environment) => environment.name)
          .filter((name) => picked.has(name)),
        suggest_environments: suggest,
      },
      { path: { project } },
    )
      .then((created) => {
        void client.invalidateQueries({
          queryKey: apiKey("/api/v1/projects/{project}/environment-discoveries", {
            path: { project },
          }),
        });
        void navigate(discoverPath(project, created.id));
      })
      .catch((error: unknown) => {
        setPending(false);
        setFailure(refusalOf(error).summary);
      });
  };

  return (
    <form
      className="ah-card ah-setup-card ah-discover-card"
      aria-label="What Claude should read"
      onSubmit={(event) => {
        event.preventDefault();
        if (repos.size > 0 && !pending && blocked === null) start();
      }}
    >
      <fieldset className="ah-env-fieldset">
        <legend className="ah-h3">Which repos should Claude read?</legend>
        <div className="ah-options">
          {view.repos.map((repo) => (
            <OptionRow
              key={repo.dir}
              type="checkbox"
              name={`${id}-repos`}
              icon="book"
              label={repo.dir}
              description={repo.role || repo.github}
              checked={repos.has(repo.dir)}
              onToggle={() => {
                toggle(repos, repo.dir, setRepos);
              }}
            />
          ))}
        </div>
      </fieldset>

      <fieldset className="ah-env-fieldset" style={{ marginTop: 20 }}>
        <legend className="ah-h3">Which environments should it look for?</legend>
        <div className="ah-options">
          {environments.map((environment) => (
            <OptionRow
              key={environment.name}
              type="checkbox"
              name={`${id}-environments`}
              icon={ACCESS_LOOK[environment.access].icon}
              label={environment.name}
              description={ACCESS_LOOK[environment.access].row}
              checked={picked.has(environment.name)}
              onToggle={() => {
                toggle(picked, environment.name, setPicked);
              }}
            />
          ))}
          <OptionRow
            type="checkbox"
            name={`${id}-suggest`}
            icon="circle-dashed"
            label="Suggest environments we have not declared"
            description="Like a staging stack the repos deploy to."
            checked={suggest}
            onToggle={() => {
              setSuggest(!suggest);
            }}
          />
        </div>
      </fieldset>

      <details className="ah-env-details" style={{ marginTop: 20 }}>
        <summary className="ah-config-field-label">What Claude reads</summary>
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          serverless.yml, CDK stacks, template.yaml, docker-compose files, Terraform, package.json
          scripts and .env.example files (names only). Never .env files or any file the guard
          blocks. It can only read: it cannot run commands or change files.
        </p>
      </details>
      <p className="ah-small ah-muted ah-env-honesty">
        <Icon name="info" /> Claude reads code, not your AWS account. A queue made by hand in the
        console, or defined in a repo you did not pick, will not show up.
      </p>
      {failure && (
        <p role="alert" className="ah-config-error">
          {failure}
        </p>
      )}
      <footer className="ah-setup-footer">
        <span className="ah-grow" />
        {repos.size === 0 && <span className="ah-small ah-muted">Pick at least one repo.</span>}
        <Link className="ah-btn ah-btn-ghost" to={environmentsPage(project)}>
          Cancel
        </Link>
        <Tooltip label={blocked ?? undefined}>
          <Button
            type="submit"
            variant="primary"
            icon="folder-search"
            disabled={repos.size === 0 || pending || blocked !== null}
          >
            {pending ? "Starting…" : "Find services with Claude"}
          </Button>
        </Tooltip>
      </footer>
    </form>
  );
}

/** While Claude reads: status, time spent and cost, the conversation, and Stop. */
function Progress({ project, discoveryId }: { project: string; discoveryId: string }) {
  const navigate = useNavigate();
  const found = useApi(
    "/api/v1/projects/{project}/environment-discoveries/{discovery_id}",
    { path: { project, discovery_id: discoveryId } },
    {
      refetchInterval: (query) => (query.state.data?.state === "running" ? POLL_MS : false),
    },
  );
  if (found.isError)
    return (
      <ProblemError
        title={found.error.status === 404 ? "No such search" : "Could not read this search"}
        detail={found.error.detail}
        status={found.error.status}
        onRetry={() => void found.refetch()}
      />
    );
  if (!found.data) return <Skeleton height={160} />;
  return (
    <ProgressCard
      discovery={found.data}
      onReview={() => {
        void navigate(reviewPath(project, discoveryId));
      }}
      onAgain={() => {
        void navigate(discoverPath(project));
      }}
    />
  );
}

function ProgressCard({
  discovery,
  onReview,
  onAgain,
}: {
  discovery: EnvironmentDiscovery;
  onReview: () => void;
  onAgain: () => void;
}) {
  const session = useAgentSession(discovery.agent_session_id);
  const commands = useAgentSessionCommands(discovery.agent_session_id);
  const [stopping, setStopping] = useState(false);
  const counts = discovery.proposal ? countByStatus(discovery.proposal) : null;
  const scope = `${count(discovery.repos.length, "repo")} · ${count(discovery.environments.length, "environment")}`;

  if (discovery.state === "failed")
    return (
      <ProblemError
        title="Claude could not finish reading the repos"
        detail={`${discovery.problem ?? "No proposal came back"}. Nothing was written.`}
        onRetry={onAgain}
      />
    );

  return (
    <section className="ah-card ah-setup-card ah-discover-card" aria-labelledby="ah-discover-state">
      <div className="ah-env-block-head">
        <h2 className="ah-h3" id="ah-discover-state" style={{ margin: 0 }}>
          {discovery.state === "running"
            ? `Claude is reading ${count(discovery.repos.length, "repo")}`
            : discovery.state === "stopped"
              ? "Stopped"
              : "Finished"}
        </h2>
        <span className="ah-row" style={{ gap: 8 }}>
          {discovery.state === "running" && <StatusBadge status="live" label="Reading" />}
          {discovery.state === "finished" && <StatusBadge status="done" label="Finished" />}
          {discovery.state === "stopped" && <StatusBadge status="stopped" />}
          {session.data && (
            <span className="ah-small ah-muted">
              <Money value={session.data.cost_usd} /> so far
            </span>
          )}
        </span>
      </div>
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        {scope}: {discovery.repos.join(", ")}
      </p>
      {discovery.state === "running" && (
        <p style={{ margin: 0 }}>
          Claude reads each repo&apos;s config files. This usually takes a few minutes; you can
          leave this page, it keeps going.
        </p>
      )}
      {discovery.state === "finished" && counts && (
        <Banner tone="info" boxed>
          Found {count(discovery.proposal?.environments.length ?? 0, "environment")} and{" "}
          {count(discovery.proposal?.services.length ?? 0, "service")} ({counts.new} new,{" "}
          {counts.differs} different from yours).
          {(discovery.proposal?.missing.length ?? 0) > 0 &&
            ` ${count(discovery.proposal?.missing.length ?? 0, "thing")} probably missing.`}
        </Banner>
      )}
      {discovery.state === "stopped" && (
        <p style={{ margin: 0 }}>Stopped before Claude sent its proposal. Nothing was written.</p>
      )}
      <footer className="ah-setup-footer">
        <Link className="ah-btn ah-btn-ghost" to={`/agent-sessions/${discovery.agent_session_id}`}>
          Open the conversation
        </Link>
        <span className="ah-grow" />
        {discovery.state === "running" && (
          <Button
            disabled={stopping}
            onClick={() => {
              setStopping(true);
              void commands.close().finally(() => {
                setStopping(false);
              });
            }}
          >
            {stopping ? "Stopping…" : "Stop"}
          </Button>
        )}
        {discovery.state === "stopped" && <Button onClick={onAgain}>Start again</Button>}
        {discovery.state === "finished" && (
          <Button variant="primary" icon="check" onClick={onReview}>
            Review {count(counts?.all ?? 0, "proposal")}
          </Button>
        )}
      </footer>
    </section>
  );
}
