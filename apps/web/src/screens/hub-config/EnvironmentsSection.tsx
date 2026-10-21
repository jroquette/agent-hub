import { useContext } from "react";
import { Link, useNavigate } from "react-router";

import { Button, EmptyState, Icon, IconButton, StatusBadge, Tooltip } from "../../components";
import { AskBlocked, ConfigSource, Mono, NoneText, useAttach } from "./parts";
import { discoverPath } from "../environments/discovery";
import { useEnvironmentRemoval } from "./EnvironmentRemoval";
import { ACCESS_LOOK, addEnvironmentPath, environmentPath, isMine, isTeams } from "./environments";
import type { FlowOrigin, HubConfigView, SourcedEnvironment } from "./environments";

/** Production, by icon and word, never by colour alone. */
export function ProductionBadge() {
  return <StatusBadge status="guard" label="Production" quiet />;
}

/** What agents may do there, in a person's words. */
export function AccessValue({ environment }: { environment: SourcedEnvironment }) {
  const look = ACCESS_LOOK[environment.access];
  return (
    <span className="ah-env-access">
      <Icon name={look.icon} />
      {look.row}
    </span>
  );
}

/** The credential names (never a value), or that there are none. */
export function CredentialLine({ environment }: { environment: SourcedEnvironment }) {
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
export function EnvironmentSource({ environment }: { environment: SourcedEnvironment }) {
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

/** Opens "Find services with Claude"; off, with the reason, when sessions cannot start. */
export function FindWithClaude({
  project,
  blocked,
  primary = false,
}: {
  project: string;
  blocked: string | null;
  primary?: boolean;
}) {
  const navigate = useNavigate();
  return (
    <Tooltip label={blocked ?? undefined}>
      <Button
        variant={primary ? "primary" : "default"}
        icon="folder-search"
        disabled={blocked !== null}
        onClick={() => {
          void navigate(discoverPath(project));
        }}
      >
        Find services with Claude
      </Button>
    </Tooltip>
  );
}

export const ADD_ENVIRONMENT_ID = "ah-env-add-environment";

/** After a row goes away its button is gone: focus lands on Add environment, not the page. */
function focusAddEnvironment() {
  requestAnimationFrame(() => {
    document.getElementById(ADD_ENVIRONMENT_ID)?.focus();
  });
}

/**
 * The Environments section: every environment with what agents may do there and how many services
 * it reaches; each environment's own page lists its services. Adds, changes and removals go to hub.local.json (only me) or
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
  const navigate = useNavigate();
  const { attach, isAttached } = useAttach();
  const blocked = useContext(AskBlocked);
  const environments = view.environments.environments;
  const services = view.environments.services;
  const { startRemove, startLoosen, dialogs } = useEnvironmentRemoval({
    view,
    onSaved,
    onDone: focusAddEnvironment,
  });

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
                  <col style={{ width: "22%" }} />
                  <col />
                  <col style={{ width: 120 }} />
                  <col style={{ width: 140 }} />
                  <col style={{ width: 200 }} />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">Environment</th>
                    <th scope="col">What agents may do</th>
                    <th scope="col">Secrets</th>
                    <th scope="col">Services</th>
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
                    const reached = services.filter((service) =>
                      service.endpoints.some((item) => item.environment === environment.name),
                    ).length;
                    return (
                      <tr key={environment.name}>
                        <th scope="row">
                          <span className="ah-stack" style={{ gap: 2 }}>
                            <span className="ah-env-name">
                              <Link
                                className="ah-env-name-link"
                                to={environmentPath(view.project, environment.name)}
                              >
                                <Mono>{environment.name}</Mono>
                                <Icon name="chevron-right" />
                              </Link>
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
                          <Link
                            className="ah-env-services-count"
                            to={environmentPath(view.project, environment.name)}
                            aria-label={`${String(reached)} ${reached === 1 ? "service" : "services"} in ${environment.name}`}
                          >
                            {reached === 0 ? (
                              <span className="ah-muted">None yet</span>
                            ) : (
                              `${String(reached)} ${reached === 1 ? "service" : "services"}`
                            )}
                          </Link>
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
                                void navigate(environmentPath(view.project, environment.name));
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
                                  startLoosen(environment);
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
        </>
      )}

      {dialogs}
    </div>
  );
}
