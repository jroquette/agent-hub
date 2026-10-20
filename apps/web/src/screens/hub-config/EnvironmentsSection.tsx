import { Fragment, useContext, useState } from "react";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import {
  Button,
  ConfirmDialog,
  Dialog,
  EmptyState,
  Icon,
  IconButton,
  PathText,
  StatusBadge,
  Tooltip,
} from "../../components";
import { AskBlocked, ConfigSource, Mono, NoneText, useAttach } from "./parts";
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
  serviceKind,
  serviceLabel,
} from "./environments";
import type { FlowOrigin, HubConfigView, SourcedEnvironment, SourcedService } from "./environments";

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

export const ADD_ENVIRONMENT_ID = "ah-env-add-environment";

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
  origin,
}: {
  view: HubConfigView;
  onSaved: (message: string, team: boolean) => void;
  /** Where the add flows come back to. */
  origin: FlowOrigin;
}) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const { attach, isAttached } = useAttach();
  const blocked = useContext(AskBlocked);
  const environments = view.environments.environments;
  const services = view.environments.services;
  const [editing, setEditing] = useState<SourcedEnvironment | null>(null);
  const [endpoint, setEndpoint] = useState<EndpointTarget | null>(null);
  const [removal, setRemoval] = useState<Removal | null>(null);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

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
      onSaved(`Removed the addresses of ${environment.name}`, team);
    } catch (error: unknown) {
      setFailure(refusalOf(error).summary);
    } finally {
      setPending(false);
    }
  };

  const servicesOf = (dir: string): SourcedService[] =>
    services.filter((service) => service.repo === dir);

  const withServices = view.repos.filter((repo) => servicesOf(repo.dir).length > 0);
  const withoutServices = view.repos.filter((repo) => servicesOf(repo.dir).length === 0);
  const addService = (repo?: string) => {
    void navigate(addServicePath(view.project, repo), { state: origin });
  };

  return (
    <div className="ah-env-page">
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
                void navigate(addEnvironmentPath(view.project), { state: origin });
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
          <section className="ah-env-block" aria-labelledby="ah-env-environments">
            <div className="ah-env-block-head">
              <h2 className="ah-h2" id="ah-env-environments">
                Environments <span className="ah-muted ah-env-count">{environments.length}</span>
              </h2>
            </div>
            <div className="ah-table-wrap">
              <table className="ah-table ah-env-table">
                <caption className="ah-sr">Environments and what agents may do</caption>
                <colgroup>
                  <col style={{ width: "22%" }} />
                  <col style={{ width: "24%" }} />
                  <col />
                  <col style={{ width: 140 }} />
                  <col style={{ width: 200 }} />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">Environment</th>
                    <th scope="col">What agents may do</th>
                    <th scope="col">Secrets</th>
                    <th scope="col">Set by</th>
                    <th scope="col">
                      <span className="ah-sr">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {environments.map((environment) => {
                    const tightened =
                      isTeams(environment) &&
                      isMine(environment) &&
                      environment.team_access !== environment.access;
                    const askId = `environments.${environment.name}`;
                    return (
                      <tr key={environment.name}>
                        <th scope="row">
                          <span className="ah-stack" style={{ gap: 2 }}>
                            <span className="ah-env-name">
                              <Mono>{environment.name}</Mono>
                              {environment.production && <ProductionBadge />}
                            </span>
                            {environment.description && (
                              <span className="ah-small ah-muted">{environment.description}</span>
                            )}
                          </span>
                        </th>
                        <td>
                          <span className="ah-stack" style={{ gap: 2 }}>
                            <AccessValue environment={environment} />
                            {tightened && environment.team_access && (
                              <span className="ah-small ah-muted">
                                Team: {ACCESS_LOOK[environment.team_access].short}
                              </span>
                            )}
                          </span>
                        </td>
                        <td>
                          <CredentialLine environment={environment} />
                        </td>
                        <td>
                          <EnvironmentSource environment={environment} />
                        </td>
                        <td>
                          <span className="ah-env-actions">
                            <IconButton
                              icon={isAttached(askId) ? "check" : "message-square"}
                              size="sm"
                              variant="ghost"
                              disabled={blocked !== null}
                              label={
                                blocked !== null
                                  ? `Ask Claude to change ${environment.name} (unavailable: ${blocked})`
                                  : `Ask Claude to change ${environment.name}`
                              }
                              onClick={() => {
                                attach({
                                  id: `config:${askId}`,
                                  label: `Environment ${environment.name}`,
                                  source: isMine(environment) ? "hub.local.json" : "hub.json",
                                  quote: `environments.${environment.name}: access ${environment.access}${environment.production ? ", production" : ""}`,
                                });
                              }}
                            />
                            <Button
                              size="sm"
                              variant="ghost"
                              icon="pencil"
                              aria-label={`Edit: ${environment.name}`}
                              onClick={() => {
                                setEditing(environment);
                              }}
                            >
                              Edit
                            </Button>
                            {isTeams(environment) && isMine(environment) ? (
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
                            )}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="ah-small ah-muted ah-env-honesty">
              <Icon name="info" /> agent-hub&apos;s own scripted actions follow this access
              strictly. Commands an agent types itself (aws, psql, curl) are told to follow it, but
              cannot always be blocked.
            </p>
          </section>

          <section className="ah-env-block" aria-labelledby="ah-env-services">
            <div className="ah-env-block-head">
              <h2 className="ah-h2" id="ah-env-services">
                Services <span className="ah-muted ah-env-count">{services.length}</span>
              </h2>
              {services.length > 0 && (
                <Button
                  icon="plus"
                  onClick={() => {
                    addService();
                  }}
                >
                  Add service
                </Button>
              )}
            </div>
            {services.length === 0 ? (
              <EmptyState
                icon="server"
                title="No services yet"
                action={
                  <Button
                    variant="primary"
                    icon="plus"
                    onClick={() => {
                      addService();
                    }}
                  >
                    Add service
                  </Button>
                }
              >
                Add the API, portal or database each repo runs, with its address in{" "}
                {environments.map((environment) => environment.name).join(", ")}. Agents then know
                where to point instead of guessing hosts.
              </EmptyState>
            ) : (
              <div className="ah-table-wrap ah-env-matrix-wrap">
                <table className="ah-table ah-env-matrix">
                  <caption className="ah-sr">Addresses per service and environment</caption>
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
                    {withServices.map((repo) => (
                      <Fragment key={repo.dir}>
                        <tr className="ah-env-repo">
                          <th scope="rowgroup" colSpan={environments.length + 1}>
                            <span className="ah-env-name">
                              <Icon name="book" />
                              {repo.dir}
                            </span>
                          </th>
                        </tr>
                        {servicesOf(repo.dir).map((service) => (
                          <tr key={service.name}>
                            <th scope="row" className="ah-env-service">
                              <Mono>{service.name}</Mono>
                              {service.kind && (
                                <span className="ah-muted">
                                  {" "}
                                  · {serviceKind(service.kind)?.label ?? service.kind}
                                </span>
                              )}
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
                                      aria-label={`Add address for ${where} in ${environment.name}`}
                                      onClick={() => {
                                        setEndpoint({
                                          repo: repo.dir,
                                          service: service.name,
                                          environment: environment.name,
                                        });
                                      }}
                                    >
                                      Add address
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
                                    aria-label={`Edit the address of ${where} in ${environment.name}: ${shown}${found.source === LOCAL_FILE ? " · set by you" : ""}${note ? ` · note: ${note}` : ""}`}
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
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {services.length > 0 && withoutServices.length > 0 && (
              <p className="ah-small ah-muted ah-env-without">
                No services yet in{" "}
                {withoutServices.map((repo, position) => (
                  <Fragment key={repo.dir}>
                    {position > 0 && " · "}
                    <button
                      type="button"
                      className="ah-link-button"
                      aria-label={`Add a service to ${repo.dir}`}
                      onClick={() => {
                        addService(repo.dir);
                      }}
                    >
                      {repo.dir}
                    </button>
                  </Fragment>
                ))}
              </p>
            )}
          </section>
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
          title={`${removal.environment.name} is still used by ${count(endpointsIn(view.environments, removal.environment.name).length, "address")}`}
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
                  : `Remove ${count(endpointsIn(view.environments, removal.environment.name).length, "address")}`}
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
    </div>
  );
}
