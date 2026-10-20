import { useEffect, useId, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import {
  Button,
  EmptyState,
  Icon,
  OptionRow,
  ProblemError,
  Skeleton,
  StatusBadge,
} from "../../components";
import { useApi } from "../../lib/api";
import { SetupFlow } from "./SetupFlow";
import {
  ACCESS_LOOK,
  NAME_PATTERN,
  SERVICE_KINDS,
  addEnvironmentPath,
  addressKind,
  flowOrigin,
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
// Past this many repos the repo question is a select, not a list of rows.
const MAX_REPO_ROWS = 6;

/** `/projects/:project/environments/services/new`: add a repo's service, one question at a time. */
export function AddServiceScreen() {
  const { project = "" } = useParams();
  const location = useLocation();
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
            <Link
              className="ah-btn ah-btn-primary"
              to={addEnvironmentPath(project)}
              state={location.state as unknown}
            >
              Add environment
            </Link>
          }
        >
          An address always belongs to one environment, so the project needs at least one, like your
          machine or staging.
        </EmptyState>
      </div>
    );
  return <AddServiceFlow view={config.data} />;
}

/** A repo's hint: its role, unless every repo says the same (then it tells nothing). */
function repoHints(view: HubConfigView): Record<string, string> {
  const roles = new Set(view.repos.map((repo) => repo.role));
  return Object.fromEntries(
    view.repos.map((repo) => [repo.dir, roles.size > 1 && repo.role ? repo.role : repo.github]),
  );
}

function AddServiceFlow({ view }: { view: HubConfigView }) {
  const id = useId();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [params] = useSearchParams();
  const project = view.project;
  const origin = flowOrigin(useLocation().state, project);
  const environments = view.environments.environments;
  const givenRepo = params.get("repo");

  const [index, setIndex] = useState(0);
  const [kindId, setKindId] = useState<string | null>(null);
  const [repo, setRepo] = useState(givenRepo ?? view.repos[0]?.dir ?? "");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [addresses, setAddresses] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const kind = serviceKind(kindId);
  const fieldId = (key: string) => `${id}-${key}`;
  const hints = repoHints(view);
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
  const addressOf = (environment: string) => (addresses[environment] ?? "").trim();
  // Nothing is said about the repo and the name before the person reaches their step.
  const repoKnown = givenRepo !== null || index >= 1;
  const label = serviceLabel(repo, name.trim());

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
        address: addressOf(environment.name),
      })),
    })
      .then(() => {
        const state: SavedState = {
          saved: `Added ${label}`,
          team: filled.some((environment) => isTeams(environment)),
        };
        void navigate(origin.returnTo, { state });
      })
      .catch((error: unknown) => {
        setPending(false);
        setFailure(
          `Could not save: ${refusalOf(error).summary.replace(/^Nothing was saved: /, "")} Your answers are kept; try again.`,
        );
      });
  };

  const steps = [
    { title: STEPS[0], summary: kind?.label },
    { title: STEPS[1], summary: name.trim() ? label : undefined },
    {
      title: STEPS[2],
      summary:
        filled.length > 0 ? filled.map((environment) => environment.name).join(", ") : undefined,
    },
    { title: STEPS[3] },
  ];

  const preview = (
    <div className="ah-stack" style={{ gap: 8 }}>
      <div className="ah-setup-preview-line">
        {repoKnown && name.trim() ? (
          <code className="ah-mono">{label}</code>
        ) : (
          <span className="ah-muted">Repo and name not chosen yet</span>
        )}
        {kind && kind.id !== "other" && <span className="ah-muted"> · {kind.label}</span>}
      </div>
      <ul className="ah-setup-preview-list">
        {environments.map((environment) => (
          <li key={environment.name}>
            <span className="ah-mono">{environment.name}</span>{" "}
            {addressOf(environment.name) ? (
              <code className="ah-mono">{addressOf(environment.name)}</code>
            ) : (
              <span className="ah-muted">not here yet</span>
            )}
          </li>
        ))}
      </ul>
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
      help = "Pick what this service is. It suggests a name and example addresses.";
      canContinue = kind !== undefined;
      blocked = "Pick one to go on.";
      body = (
        <fieldset className="ah-env-fieldset">
          <legend className="ah-sr">{question}</legend>
          <div className="ah-options">
            {SERVICE_KINDS.map((candidate) => (
              <OptionRow
                key={candidate.id}
                type="radio"
                name={fieldId("kind")}
                icon={candidate.icon}
                label={candidate.label}
                description={candidate.hint}
                checked={kindId === candidate.id}
                onToggle={() => {
                  setKindId(candidate.id);
                  if (!nameTouched) setName(candidate.name);
                }}
              />
            ))}
          </div>
        </fieldset>
      );
      break;
    case 1:
      question = "Which repo runs it, and what is it called?";
      help = "The repo whose code it is. The name is how agents refer to it.";
      canContinue = nameProblem === null && repo !== "";
      body = (
        <div className="ah-stack" style={{ gap: 20 }}>
          {view.repos.length > MAX_REPO_ROWS ? (
            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={fieldId("repo")} className="ah-config-field-label">
                Repo
              </label>
              <select
                id={fieldId("repo")}
                className="ah-input ah-setup-input ah-setup-input-short"
                value={repo}
                onChange={(event) => {
                  setRepo(event.target.value);
                }}
              >
                {view.repos.map((item) => (
                  <option key={item.dir} value={item.dir}>
                    {item.dir}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <fieldset className="ah-env-fieldset">
              <legend className="ah-config-field-label">Repo</legend>
              <div className="ah-options">
                {view.repos.map((item) => (
                  <OptionRow
                    key={item.dir}
                    type="radio"
                    name={fieldId("repo")}
                    icon="book"
                    label={item.dir}
                    description={hints[item.dir]}
                    checked={repo === item.dir}
                    onToggle={() => {
                      setRepo(item.dir);
                    }}
                  />
                ))}
              </div>
            </fieldset>
          )}
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId("name")} className="ah-config-field-label">
              Service name
            </label>
            <input
              id={fieldId("name")}
              className="ah-input ah-mono ah-setup-input ah-setup-input-short"
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
      blocked = "Fill at least one address.";
      body = (
        <div className="ah-stack" style={{ gap: 12 }}>
          <div className="ah-setup-addresses">
            {environments.map((environment) => {
              const value = addresses[environment.name] ?? "";
              const look = ACCESS_LOOK[environment.access];
              const inputId = fieldId(`at-${environment.name}`);
              return (
                <div key={environment.name} className="ah-setup-address">
                  <div className="ah-stack" style={{ gap: 4 }}>
                    <span className="ah-env-name">
                      <code className="ah-mono">{environment.name}</code>
                      {environment.production && (
                        <StatusBadge status="guard" label="Production" quiet />
                      )}
                    </span>
                    <span className="ah-small ah-muted ah-env-access">
                      <Icon name={look.icon} /> {look.short}
                    </span>
                  </div>
                  <div className="ah-stack" style={{ gap: 4 }}>
                    <input
                      id={inputId}
                      className="ah-input ah-mono ah-setup-input"
                      aria-label={`Address in ${environment.name}`}
                      value={value}
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={kind ? exampleAddress(kind, environment) : "address"}
                      aria-describedby={`${inputId}-kind`}
                      onChange={(event) => {
                        setAddresses({ ...addresses, [environment.name]: event.target.value });
                      }}
                    />
                    <span id={`${inputId}-kind`} className="ah-small ah-muted">
                      {value.trim() === ""
                        ? "Empty: it does not run here."
                        : addressKind(value.trim()) === "url"
                          ? "A URL."
                          : "A resource name."}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            <Icon name="lock" /> Never a password: a URL takes no user or token.
          </p>
        </div>
      );
      break;
    default:
      question = `Add ${label}?`;
      help = "Check your answers. Change any of them before you add it.";
      body = (
        <div className="ah-stack" style={{ gap: 16 }}>
          <dl className="ah-setup-review">
            {[
              { title: "Kind", value: kind?.label, step: 0 },
              { title: "Repo", value: repo, step: 1 },
              { title: "Name", value: name.trim(), step: 1 },
              {
                title: "Addresses",
                value: environments.map((environment) => (
                  <div key={environment.name}>
                    {addressOf(environment.name) ? (
                      <>
                        <span className="ah-mono">{environment.name}</span> ·{" "}
                        <code className="ah-mono">{addressOf(environment.name)}</code>
                      </>
                    ) : (
                      <span className="ah-muted">Not in {environment.name}</span>
                    )}
                  </div>
                )),
                step: 2,
              },
            ].map((row) => (
              <div key={row.title} className="ah-setup-review-row">
                <dt>{row.title}</dt>
                <dd>{row.value}</dd>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Change ${row.title.toLowerCase()}`}
                  onClick={() => {
                    setIndex(row.step);
                  }}
                >
                  Change
                </Button>
              </div>
            ))}
          </dl>
          <div className="ah-setup-next">
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
              <li>Agents see it from their next session.</li>
            </ol>
          </div>
        </div>
      );
  }

  return (
    <SetupFlow
      project={project}
      origin={origin}
      title="Add service"
      intro="Tell agents what a repo runs and where to reach it in each environment."
      noun="service"
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
      previewWhere="In AGENTS.md and the session brief"
      preview={preview}
    >
      {body}
    </SetupFlow>
  );
}
