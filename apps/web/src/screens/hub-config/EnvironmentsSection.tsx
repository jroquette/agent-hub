import { Fragment, useState } from "react";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import {
  Button,
  ConfirmDialog,
  Dialog,
  EmptyState,
  Icon,
  PathText,
  StatusBadge,
  Tooltip,
} from "../../components";
import { ConfigRow, ConfigSource, Mono, NoneText, Section, useAttach } from "./parts";
import { EndpointDialog } from "./EndpointDialog";
import type { EndpointTarget } from "./EndpointDialog";
import { EnvironmentDialog } from "./EnvironmentDialog";
import {
  ACCESS_LOOK,
  LOCAL_FILE,
  addEnvironmentPath,
  addServicePath,
  count,
  endpointText,
  endpointValues,
  endpointsIn,
  isMine,
  isTeams,
  postEnvironmentEdit,
  refusalOf,
  serviceLabel,
} from "./environments";
import type { HubConfigView, SourcedEnvironment, SourcedService } from "./environments";

/** Production, by icon and word, never by colour alone. */
function ProductionBadge() {
  return <StatusBadge status="guard" label="Production" quiet />;
}

/** What agents may do there, in a person's words. */
function AccessValue({ environment }: { environment: SourcedEnvironment }) {
  const look = ACCESS_LOOK[environment.access];
  return (
    <span className="ah-env-access">
      <Icon name={look.icon} />
      {look.row}
    </span>
  );
}

/** The credential names (never a value), or that there are none. */
function CredentialLine({ environment }: { environment: SourcedEnvironment }) {
  const credentials = environment.credentials;
  const parts = [];
  if (credentials?.aws_profile)
    parts.push(
      <span key="aws">
        AWS profile <Mono>{credentials.aws_profile}</Mono>
      </span>,
    );
  if (credentials?.env && credentials.env.length > 0)
    parts.push(
      <span key="env">
        {credentials.env.length === 1 ? "variable" : "variables"}{" "}
        {credentials.env.map((name) => (
          <Mono key={name}>{name}</Mono>
        ))}
      </span>,
    );
  if (credentials?.env_file)
    parts.push(
      <span key="file">
        env file <Mono>{credentials.env_file}</Mono>
      </span>,
    );
  if (parts.length === 0) return <NoneText>No credentials</NoneText>;
  return (
    <span className="ah-env-credentials">
      <Icon name="lock" />
      {parts}
    </span>
  );
}

/** Who set the environment: the team, you, or the team with your stricter access. */
function EnvironmentSource({ environment }: { environment: SourcedEnvironment }) {
  if (isTeams(environment) && isMine(environment))
    return (
      <Tooltip
        label={`hub.local.json → environments.${environment.name}.access makes the team's access stricter for your agents.`}
      >
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
        <span className="ah-config-source" data-source="local" tabIndex={0}>
          <Icon name="laptop" />
          Tightened by you
        </span>
      </Tooltip>
    );
  return (
    <ConfigSource
      source={isMine(environment) ? "local" : "team"}
      where={`${environment.source} → environments.${environment.name}`}
    />
  );
}

type Removal =
  | { kind: "environment"; environment: SourcedEnvironment }
  | { kind: "in-use"; environment: SourcedEnvironment }
  | { kind: "loosen"; environment: SourcedEnvironment };

const ADD_ENVIRONMENT_ID = "ah-env-add-environment";

/** After a row goes away its button is gone: focus lands on Add environment, not the page. */
function focusAddEnvironment() {
  requestAnimationFrame(() => {
    document.getElementById(ADD_ENVIRONMENT_ID)?.focus();
  });
}

/**
 * The Environments section: every environment with what agents may do there, and every repo's
 * services per environment. Adds, changes and removals go to hub.local.json (only me) or
 * hub.json (the team, uncommitted), through the same checks as `hub env`.
 */
export function EnvironmentsSection({
  view,
  onSaved,
}: {
  view: HubConfigView;
  onSaved: (message: string, team: boolean) => void;
}) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const { attach, isAttached } = useAttach();
  const environments = view.environments.environments;
  const services = view.environments.services;
  const [editing, setEditing] = useState<SourcedEnvironment | null>(null);
  const [endpoint, setEndpoint] = useState<EndpointTarget | null>(null);
  const [removal, setRemoval] = useState<Removal | null>(null);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const quote = environments
    .map(
      (environment) =>
        `environments.${environment.name}: access ${environment.access}${environment.production ? ", production" : ""} (${environment.source})`,
    )
    .join("\n");

  const startRemove = (environment: SourcedEnvironment) => {
    setFailure(null);
    const used = endpointsIn(view.environments, environment.name);
    setRemoval({ kind: used.length > 0 ? "in-use" : "environment", environment });
  };

  const removeEnvironment = (environment: SourcedEnvironment) => {
    setPending(true);
    // A tightened team environment: removing it here drops only my stricter access.
    const scope = isMine(environment) ? "local" : "team";
    postEnvironmentEdit(client, view.project, {
      op: "remove_environment",
      scope,
      name: environment.name,
    })
      .then(() => {
        setPending(false);
        setRemoval(null);
        focusAddEnvironment();
        onSaved(
          isTeams(environment) && scope === "local"
            ? `${environment.name} is back to the team's access`
            : `Removed ${environment.name}`,
          scope === "team",
        );
      })
      .catch((error: unknown) => {
        setPending(false);
        setFailure(refusalOf(error).summary);
      });
  };

  const removeEndpoints = async (environment: SourcedEnvironment) => {
    setPending(true);
    setFailure(null);
    let team = false;
    try {
      for (const { service, endpoint: used } of endpointsIn(view.environments, environment.name)) {
        const scope = used.source === LOCAL_FILE ? "local" : "team";
        team ||= scope === "team";
        await postEnvironmentEdit(client, view.project, {
          op: "remove_endpoint",
          scope,
          repo: service.repo,
          service: service.name,
          environment: environment.name,
        });
      }
      setRemoval({ kind: "environment", environment });
      onSaved(`Removed the endpoints of ${environment.name}`, team);
    } catch (error: unknown) {
      setFailure(refusalOf(error).summary);
    } finally {
      setPending(false);
    }
  };

  const servicesOf = (dir: string): SourcedService[] =>
    services.filter((service) => service.repo === dir);

  return (
    <Section
      id="environments"
      title="Environments"
      askName="the environments"
      icon="server"
      purpose="Tell agents where your systems run and how to reach them: first the environments, then the services each repo runs there. Agents read it in AGENTS.md and their brief."
      onAsk={() => {
        attach({
          id: "config:section:environments",
          label: "Environments",
          source: "hub.json",
          quote: quote || "No environments declared.",
        });
      }}
    >
      {environments.length === 0 ? (
        <EmptyState
          icon="server"
          title="No environments yet"
          command="./hub env add local --access write --local"
          action={
            <Button
              id={ADD_ENVIRONMENT_ID}
              variant="primary"
              icon="plus"
              onClick={() => {
                void navigate(addEnvironmentPath(view.project));
              }}
            >
              Add environment
            </Button>
          }
        >
          Say where your systems run (this machine, a test stack, production) and what agents may do
          in each. Agents read it, so they stop guessing hosts and profiles.
        </EmptyState>
      ) : (
        <>
          <div className="ah-env-subhead" style={{ marginTop: 0 }}>
            <div>
              <h3 className="ah-env-subtitle">
                <span className="ah-env-step">1</span> Environments
              </h3>
              <p className="ah-small ah-muted" style={{ margin: 0 }}>
                Where your systems run, and what agents may do in each.
              </p>
            </div>
            <Button
              id={ADD_ENVIRONMENT_ID}
              icon="plus"
              onClick={() => {
                void navigate(addEnvironmentPath(view.project));
              }}
            >
              Add environment
            </Button>
          </div>
          <div className="ah-config-rows">
            {environments.map((environment) => {
              const tightened =
                isTeams(environment) &&
                isMine(environment) &&
                environment.team_access !== environment.access;
              return (
                <ConfigRow
                  key={environment.name}
                  label={environment.name}
                  labelNode={
                    <span className="ah-env-name">
                      <Mono>{environment.name}</Mono>
                      {environment.production && <ProductionBadge />}
                    </span>
                  }
                  source={<EnvironmentSource environment={environment} />}
                  ask={{
                    label: `Ask Claude to change ${environment.name}`,
                    pressed: isAttached(`environments.${environment.name}`),
                    onClick: () => {
                      attach({
                        id: `config:environments.${environment.name}`,
                        label: `Environment ${environment.name}`,
                        source: isMine(environment) ? "hub.local.json" : "hub.json",
                        quote: `environments.${environment.name}: access ${environment.access}${environment.production ? ", production" : ""}`,
                      });
                    },
                  }}
                  onEdit={() => {
                    setEditing(environment);
                  }}
                  editLabel="Edit"
                  actions={
                    isTeams(environment) && isMine(environment) ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon="undo-2"
                        aria-label={`Use the team's access for ${environment.name}`}
                        onClick={() => {
                          setFailure(null);
                          setRemoval({ kind: "loosen", environment });
                        }}
                      >
                        Use team&apos;s
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon="x"
                        aria-label={`Remove environment ${environment.name}`}
                        onClick={() => {
                          startRemove(environment);
                        }}
                      >
                        Remove
                      </Button>
                    )
                  }
                >
                  <span className="ah-config-cell">
                    <AccessValue environment={environment} />
                    {environment.description && (
                      <span className="ah-small ah-muted">{environment.description}</span>
                    )}
                    {tightened && environment.team_access && (
                      <span className="ah-small ah-muted">
                        Team: {ACCESS_LOOK[environment.team_access].short}
                      </span>
                    )}
                    <span className="ah-small">
                      <CredentialLine environment={environment} />
                    </span>
                  </span>
                </ConfigRow>
              );
            })}
          </div>

          <p className="ah-small ah-muted ah-env-honesty">
            <Icon name="info" /> Scripted actions follow this access strictly. Free commands (aws,
            psql, curl) follow it as an instruction, plus blocked words: best effort.
          </p>

          <div className="ah-env-subhead">
            <div>
              <h3 className="ah-env-subtitle">
                <span className="ah-env-step">2</span> Services
              </h3>
              <p className="ah-small ah-muted" style={{ margin: 0 }}>
                What each repo runs (an API, a portal, a database) and its address in each
                environment. <Icon name="laptop" /> marks the ones set by you.
              </p>
            </div>
            <Button
              icon="plus"
              onClick={() => {
                void navigate(addServicePath(view.project));
              }}
            >
              Add service
            </Button>
          </div>
          {services.length === 0 && (
            <div className="ah-env-services-empty">
              <Icon name="server" />
              <div className="ah-stack" style={{ gap: 4 }}>
                <strong>No services yet</strong>
                <span className="ah-small ah-muted">
                  Add the API, portal or database each repo runs, with its address in{" "}
                  {environments.map((environment) => environment.name).join(", ")}. Agents then know
                  where to point instead of guessing hosts.
                </span>
              </div>
              <Button
                variant="primary"
                icon="plus"
                onClick={() => {
                  void navigate(addServicePath(view.project));
                }}
              >
                Add service
              </Button>
            </div>
          )}
          {services.length > 0 && (
            <div className="ah-table-wrap ah-env-matrix-wrap">
              <table className="ah-table ah-env-matrix">
                <caption className="ah-env-caption">Endpoints per service and environment</caption>
                <thead>
                  <tr>
                    <th scope="col">Service</th>
                    {environments.map((environment) => (
                      <th key={environment.name} scope="col">
                        <span className="ah-env-name">
                          {environment.name}
                          {environment.production && <ProductionBadge />}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {view.repos.map((repo) => {
                    const own = servicesOf(repo.dir);
                    return (
                      <Fragment key={repo.dir}>
                        <tr className="ah-env-repo">
                          <th scope="rowgroup" colSpan={environments.length + 1}>
                            <span className="ah-env-name">
                              <Icon name="book" />
                              {repo.dir}
                              {own.length === 0 && (
                                <>
                                  <span className="ah-muted">· No services yet</span>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    icon="plus"
                                    aria-label={`Add a service to ${repo.dir}`}
                                    onClick={() => {
                                      void navigate(addServicePath(view.project, repo.dir));
                                    }}
                                  >
                                    Add service
                                  </Button>
                                </>
                              )}
                            </span>
                          </th>
                        </tr>
                        {own.map((service) => (
                          <tr key={service.name}>
                            <th scope="row" className="ah-env-service">
                              <Mono>{service.name}</Mono>
                              {service.kind && <span className="ah-muted"> · {service.kind}</span>}
                            </th>
                            {environments.map((environment) => {
                              const found = service.endpoints.find(
                                (item) => item.environment === environment.name,
                              );
                              const where = serviceLabel(repo.dir, service.name);
                              if (!found)
                                return (
                                  <td key={environment.name}>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      icon="plus"
                                      className="ah-env-add"
                                      aria-label={`Add endpoint for ${where} in ${environment.name}`}
                                      onClick={() => {
                                        setEndpoint({
                                          repo: repo.dir,
                                          service: service.name,
                                          environment: environment.name,
                                        });
                                      }}
                                    >
                                      Add
                                    </Button>
                                  </td>
                                );
                              const shown = endpointText(found);
                              const note = endpointValues(found).note;
                              return (
                                <td key={environment.name}>
                                  <button
                                    type="button"
                                    className="ah-env-cell"
                                    aria-label={`Edit endpoint of ${where} in ${environment.name}: ${shown}${found.source === LOCAL_FILE ? " · set by you" : ""}${note ? ` · note: ${note}` : ""}`}
                                    onClick={() => {
                                      setEndpoint({
                                        repo: repo.dir,
                                        service: service.name,
                                        environment: environment.name,
                                        endpoint: found,
                                      });
                                    }}
                                  >
                                    <span className="ah-mono">
                                      <PathText path={shown} max={34} />
                                    </span>
                                    {found.source === LOCAL_FILE && (
                                      <Icon name="laptop" title="Set by you" />
                                    )}
                                    {note && <Icon name="info" title={note} />}
                                  </button>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {editing !== null && (
        <EnvironmentDialog
          view={view}
          editing={editing}
          onClose={() => {
            setEditing(null);
          }}
          onSaved={onSaved}
        />
      )}
      {endpoint !== null && (
        <EndpointDialog
          view={view}
          target={endpoint}
          onClose={() => {
            setEndpoint(null);
          }}
          onSaved={onSaved}
        />
      )}
      {removal?.kind === "environment" && (
        <ConfirmDialog
          title={`Remove environment ${removal.environment.name}?`}
          confirmLabel={pending ? "Removing…" : "Remove environment"}
          pending={pending}
          requireText={removal.environment.production ? removal.environment.name : undefined}
          consequences={[
            `Agents stop seeing ${removal.environment.name}.`,
            ...(isMine(removal.environment)
              ? []
              : ["hub.json changes; run ./hub sync and open a hub PR."]),
            ...(removal.environment.production
              ? [`Type ${removal.environment.name} to confirm.`]
              : []),
          ]}
          onCancel={() => {
            setRemoval(null);
          }}
          onConfirm={() => {
            removeEnvironment(removal.environment);
          }}
        >
          {failure && (
            <p role="alert" className="ah-config-error">
              {failure}
            </p>
          )}
        </ConfirmDialog>
      )}
      {removal?.kind === "loosen" && (
        <ConfirmDialog
          title={`Use the team's access for ${removal.environment.name}?`}
          tone="primary"
          confirmLabel={pending ? "Saving…" : "Use the team's access"}
          pending={pending}
          consequences={[
            `Your agents ${ACCESS_LOOK[removal.environment.team_access ?? "write"].short} in ${removal.environment.name} again, as the team set it.`,
            "Your stricter setting is removed from hub.local.json.",
          ]}
          onCancel={() => {
            setRemoval(null);
          }}
          onConfirm={() => {
            removeEnvironment(removal.environment);
          }}
        >
          {failure && (
            <p role="alert" className="ah-config-error">
              {failure}
            </p>
          )}
        </ConfirmDialog>
      )}
      {removal?.kind === "in-use" && (
        <Dialog
          title={`${removal.environment.name} is still used by ${count(endpointsIn(view.environments, removal.environment.name).length, "endpoint")}`}
          size="sm"
          pending={pending}
          onClose={() => {
            setRemoval(null);
          }}
          footer={
            <>
              <Button
                disabled={pending}
                onClick={() => {
                  setRemoval(null);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                disabled={pending}
                onClick={() => {
                  void removeEndpoints(removal.environment);
                }}
              >
                {pending
                  ? "Removing…"
                  : `Remove ${count(endpointsIn(view.environments, removal.environment.name).length, "endpoint")}`}
              </Button>
            </>
          }
        >
          <ul className="ah-consequences">
            {endpointsIn(view.environments, removal.environment.name).map(
              ({ service, endpoint: used }) => (
                <li key={`${service.repo}/${service.name}`}>
                  {serviceLabel(service.repo, service.name)} · <Mono>{endpointText(used)}</Mono>
                </li>
              ),
            )}
          </ul>
          <p className="ah-muted">Remove them first, then the environment.</p>
          {failure && (
            <p role="alert" className="ah-config-error">
              {failure}
            </p>
          )}
        </Dialog>
      )}
    </Section>
  );
}
