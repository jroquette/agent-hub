import { useEffect, useId, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { Button, EmptyState, Icon, ProblemError, Skeleton, StatusBadge } from "../../components";
import { useApi } from "../../lib/api";
import { ChoiceTile, SetupFlow } from "./SetupFlow";
import {
  ACCESS_LOOK,
  NAME_PATTERN,
  SERVICE_KINDS,
  addEnvironmentPath,
  addressKind,
  environmentsHome,
  exampleAddress,
  isTeams,
  postEnvironmentEdit,
  refusalOf,
  serviceKind,
  serviceLabel,
} from "./environments";
import type { HubConfigView, SavedState } from "./environments";
import "./hub-config.css";

const STEPS = ["What runs", "Repo and name", "Addresses", "Review"] as const;

/** `/projects/:project/config/services/new`: add a repo's service, one question at a time. */
export function AddServiceScreen() {
  const { project = "" } = useParams();
  const config = useApi("/api/v1/projects/{project}/config", { path: { project } });
  useEffect(() => {
    document.title = `Add service · ${project}`;
  }, [project]);
  if (config.isError)
    return (
      <div className="ah-page">
        <ProblemError
          title="Could not read this project's configuration"
          detail={config.error.detail}
          status={config.error.status}
          onRetry={() => void config.refetch()}
        />
      </div>
    );
  if (!config.data)
    return (
      <div className="ah-page" aria-busy="true">
        <Skeleton height={320} />
      </div>
    );
  if (config.data.environments.environments.length === 0)
    return (
      <div className="ah-page">
        <EmptyState
          icon="server"
          title="Add an environment first"
          action={
            <Link className="ah-btn ah-btn-primary" to={addEnvironmentPath(project)}>
              Add environment
            </Link>
          }
        >
          A service is reached at an address in an environment, so the project needs at least one
          environment, like your machine or staging.
        </EmptyState>
      </div>
    );
  return <AddServiceFlow view={config.data} />;
}

function AddServiceFlow({ view }: { view: HubConfigView }) {
  const id = useId();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [params] = useSearchParams();
  const project = view.project;
  const environments = view.environments.environments;

  const [index, setIndex] = useState(0);
  const [kindId, setKindId] = useState<string | null>(null);
  const [repo, setRepo] = useState(params.get("repo") ?? view.repos[0]?.dir ?? "");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [addresses, setAddresses] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const kind = serviceKind(kindId);
  const fieldId = (key: string) => `${id}-${key}`;
  const taken = view.environments.services.some(
    (service) => service.repo === repo && service.name === name.trim(),
  );
  const nameProblem =
    name.trim() === ""
      ? "Name the service."
      : taken
        ? `${repo} already has ${name.trim()}. Add its addresses from the table instead.`
        : NAME_PATTERN.test(name.trim())
          ? null
          : "Letters, digits, - and _ only, up to 40.";
  const filled = environments.filter((environment) => (addresses[environment.name] ?? "").trim());
  const fallbackName = kind && kind.name !== "" ? kind.name : "service";
  const shown = serviceLabel(repo, name.trim() === "" ? fallbackName : name.trim());

  const save = () => {
    setPending(true);
    setFailure(null);
    postEnvironmentEdit(client, project, {
      op: "add_service",
      repo,
      service: name.trim(),
      kind: kind && kind.id !== "other" ? kind.id : null,
      addresses: filled.map((environment) => ({
        environment: environment.name,
        address: (addresses[environment.name] ?? "").trim(),
      })),
    })
      .then(() => {
        const state: SavedState = {
          saved: `Added ${serviceLabel(repo, name.trim())}`,
          team: filled.some((environment) => isTeams(environment)),
        };
        void navigate(environmentsHome(project), { state });
      })
      .catch((error: unknown) => {
        setPending(false);
        setFailure(refusalOf(error).summary);
      });
  };

  const steps = [
    { title: STEPS[0], summary: kind?.label },
    { title: STEPS[1], summary: name.trim() ? shown : undefined },
    {
      title: STEPS[2],
      summary:
        filled.length > 0 ? filled.map((environment) => environment.name).join(", ") : undefined,
    },
    { title: STEPS[3] },
  ];

  const preview = (
    <div className="ah-stack" style={{ gap: 10 }}>
      <code className="ah-flow-preview-line">
        {shown}
        {kind && kind.id !== "other" ? ` (${kind.id})` : ""}
      </code>
      {filled.length === 0 ? (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          Its addresses show here as you fill them.
        </p>
      ) : (
        <ul className="ah-flow-preview-list">
          {filled.map((environment) => (
            <li key={environment.name}>
              <span className="ah-mono">{environment.name}</span>{" "}
              <code className="ah-mono">{(addresses[environment.name] ?? "").trim()}</code>
            </li>
          ))}
        </ul>
      )}
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        Agents call or query it there instead of guessing a host.
      </p>
    </div>
  );

  let question = "";
  let help = "";
  let body = null;
  let canContinue = true;
  let blocked: string | undefined;

  switch (index) {
    case 0:
      question = "What runs?";
      help = "Pick what this service is. It fills in a name and example addresses for you.";
      canContinue = kind !== undefined;
      blocked = "Pick one to go on.";
      body = (
        <div className="ah-flow-tiles">
          {SERVICE_KINDS.map((candidate) => (
            <ChoiceTile
              key={candidate.id}
              name={fieldId("kind")}
              icon={candidate.icon}
              label={candidate.label}
              hint={candidate.hint}
              checked={kindId === candidate.id}
              onPick={() => {
                setKindId(candidate.id);
                if (!nameTouched) setName(candidate.name);
              }}
            />
          ))}
        </div>
      );
      break;
    case 1:
      question = "Which repo runs it, and what is it called?";
      help = "The repo whose code this service is. The name is how agents refer to it.";
      canContinue = nameProblem === null && repo !== "";
      body = (
        <div className="ah-stack" style={{ gap: 16 }}>
          <fieldset className="ah-env-fieldset">
            <legend className="ah-config-field-label">Repo</legend>
            <div className="ah-flow-tiles">
              {view.repos.map((item) => (
                <ChoiceTile
                  key={item.dir}
                  name={fieldId("repo")}
                  icon="git-branch"
                  label={item.dir}
                  hint={item.role || item.github}
                  checked={repo === item.dir}
                  onPick={() => {
                    setRepo(item.dir);
                  }}
                />
              ))}
            </div>
          </fieldset>
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId("name")} className="ah-config-field-label">
              Service name
            </label>
            <input
              id={fieldId("name")}
              className="ah-input ah-mono ah-flow-input"
              value={name}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={name.trim() !== "" && nameProblem ? true : undefined}
              aria-describedby={`${fieldId("name")}-help`}
              onChange={(event) => {
                setNameTouched(true);
                setName(event.target.value);
              }}
            />
            <span
              id={`${fieldId("name")}-help`}
              className={
                name.trim() !== "" && nameProblem ? "ah-small ah-config-error" : "ah-small ah-muted"
              }
            >
              {name.trim() !== "" && nameProblem
                ? nameProblem
                : "e.g. api, admin-portal, orders-db."}
            </span>
          </div>
        </div>
      );
      break;
    case 2:
      question = `Where is ${name.trim() || "it"} in each environment?`;
      help =
        "A URL like http://localhost:8000, or a name like orders-table. Leave an environment empty if it does not run there.";
      canContinue = filled.length > 0;
      blocked = "Fill at least one.";
      body = (
        <div className="ah-flow-addresses">
          {environments.map((environment) => {
            const value = addresses[environment.name] ?? "";
            const look = ACCESS_LOOK[environment.access];
            return (
              <div key={environment.name} className="ah-flow-address">
                <div className="ah-flow-address-head">
                  <label htmlFor={fieldId(`at-${environment.name}`)} className="ah-env-name">
                    <code className="ah-mono">{environment.name}</code>
                    {environment.production && (
                      <StatusBadge status="guard" label="Production" quiet />
                    )}
                  </label>
                  <span className="ah-small ah-muted ah-env-access">
                    <Icon name={look.icon} /> {look.row}
                  </span>
                </div>
                <input
                  id={fieldId(`at-${environment.name}`)}
                  className="ah-input ah-mono ah-flow-input"
                  value={value}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={kind ? exampleAddress(kind, environment) : "address"}
                  aria-describedby={`${fieldId(`at-${environment.name}`)}-kind`}
                  onChange={(event) => {
                    setAddresses({ ...addresses, [environment.name]: event.target.value });
                  }}
                />
                <span
                  id={`${fieldId(`at-${environment.name}`)}-kind`}
                  className="ah-small ah-muted"
                >
                  {value.trim() === ""
                    ? "Empty: it does not run here."
                    : addressKind(value.trim()) === "url"
                      ? "A URL."
                      : "A resource name."}
                </span>
              </div>
            );
          })}
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            <Icon name="lock" /> Never a password: a URL takes no user or token.
          </p>
        </div>
      );
      break;
    default:
      question = `Add ${shown}?`;
      help = "Check your answers. Change any of them before you add it.";
      body = (
        <div className="ah-stack" style={{ gap: 16 }}>
          <dl className="ah-flow-review">
            {steps.slice(0, -1).map((step, position) => (
              <div key={step.title} className="ah-flow-review-row">
                <dt>{step.title}</dt>
                <dd>
                  {position === 2
                    ? filled.map((environment) => (
                        <div key={environment.name}>
                          <span className="ah-mono">{environment.name}</span>{" "}
                          <code className="ah-mono">
                            {(addresses[environment.name] ?? "").trim()}
                          </code>
                        </div>
                      ))
                    : step.summary}
                </dd>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Change ${step.title.toLowerCase()}`}
                  onClick={() => {
                    setIndex(position);
                  }}
                >
                  Change
                </Button>
              </div>
            ))}
          </dl>
          <div className="ah-flow-next">
            <strong className="ah-small">What happens next</strong>
            <ol className="ah-small">
              {filled.some((environment) => isTeams(environment)) && (
                <li>
                  The addresses in the team&apos;s environments go to{" "}
                  <code className="ah-mono">hub.json</code>, not committed: run{" "}
                  <code className="ah-mono">./hub sync</code> and open a hub PR.
                </li>
              )}
              {filled.some((environment) => !isTeams(environment)) && (
                <li>
                  The addresses in your own environments go to{" "}
                  <code className="ah-mono">hub.local.json</code> on this machine.
                </li>
              )}
              <li>Agents see it in their next session.</li>
            </ol>
          </div>
        </div>
      );
  }

  return (
    <SetupFlow
      project={project}
      title="Add service"
      intro="A service is something a repo runs: an API, a portal, a database, a queue. Tell agents where to find it in each environment."
      steps={steps}
      index={index}
      onIndex={setIndex}
      question={question}
      help={help}
      canContinue={canContinue}
      blocked={blocked}
      onFinish={save}
      finishLabel="Add service"
      pending={pending}
      failure={failure}
      preview={preview}
    >
      {body}
    </SetupFlow>
  );
}
