import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import {
  Banner,
  Button,
  CopyButton,
  DerivedLabel,
  EmptyState,
  Icon,
  OptionRow,
  PathText,
  ProblemError,
  Skeleton,
  Tooltip,
} from "../../components";
import { useApi } from "../../lib/api";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { useDiscuss } from "../../shell/discuss";
import { sessionControlUnavailable } from "../sessions-list/control";
import { useAgentCapabilities } from "../sessions-list/queries";
import { useEnvironmentRemoval } from "../hub-config/EnvironmentRemoval";
import {
  AccessValue,
  CredentialLine,
  EnvironmentSource,
  FindWithClaude,
  ProductionBadge,
} from "../hub-config/EnvironmentsSection";
import { ServicePanel } from "../hub-config/ServicePanel";
import { AccessFields, SecretsFields } from "../hub-config/environmentFields";
import type { SecretsFrom } from "../hub-config/environmentFields";
import {
  ACCESS_LOOK,
  LOCAL_FILE,
  STRICTNESS,
  addServicePath,
  endpointText,
  endpointValues,
  environmentPath,
  environmentsPage,
  isMine,
  isTeams,
  lineWithValue,
  linesOf,
  postEnvironmentEdit,
  refusalOf,
  serviceKind,
  serviceLabel,
} from "../hub-config/environments";
import type {
  Access,
  EnvironmentEdit,
  HubConfigView,
  Refusal,
  SourcedEnvironment,
  SourcedService,
} from "../hub-config/environments";
import { SavedToast, UncommittedNotice, useSaveNotices } from "../hub-config/notices";
import { AskBlocked, Mono } from "../hub-config/parts";
import "../hub-config/hub-config.css";

type SectionId = "access" | "secrets" | "description";
const SECTION_WORD: Record<SectionId, string> = {
  access: "access",
  secrets: "secrets",
  description: "description",
};
const DESCRIPTION_MAX = 80;

/** `/projects/:project/environment/:name`: one environment, read and changed in place. */
export function EnvironmentScreen() {
  const { project = "", name = "" } = useParams();
  const config = useApi("/api/v1/projects/{project}/config", { path: { project } });
  const notices = useSaveNotices();
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const blocked = unavailable ? `${unavailable.title}. ${unavailable.detail}` : null;
  useEffect(() => {
    document.title = `${name} · Environments · ${project}`;
  }, [project, name]);

  const view = config.data;
  const environment = view?.environments.environments.find((item) => item.name === name);
  let body: ReactNode;
  if (config.isError)
    body = (
      <ProblemError
        title="Could not read this project's hub.json"
        detail={`${config.error.detail ?? ""} Run ./hub doctor in the hub for the line to fix.`}
        status={config.error.status}
        onRetry={() => void config.refetch()}
      />
    );
  else if (!view)
    body = (
      <div className="ah-stack" style={{ gap: 12 }} aria-busy="true">
        <Skeleton height={40} />
        <Skeleton height={320} />
      </div>
    );
  else if (!environment)
    body = (
      <EmptyState
        icon="server"
        title={`No environment called ${name}`}
        action={
          <Link className="ah-btn" to={environmentsPage(project)}>
            Back to Environments
          </Link>
        }
      >
        It may have been renamed or removed.
      </EmptyState>
    );
  else
    body = (
      <EnvironmentBody
        view={view}
        environment={environment}
        onSaved={notices.onSaved}
        blocked={blocked}
      />
    );

  return (
    <AskBlocked.Provider value={blocked}>
      <div className="ah-page" style={{ gap: 16 }}>
        <Breadcrumbs
          items={[
            { label: "Portfolio", href: "/" },
            { label: project, href: `/projects/${encodeURIComponent(project)}` },
            { label: "Environments", href: environmentsPage(project) },
            { label: name },
          ]}
        />
        {notices.teamChanged && (
          <UncommittedNotice blocked={blocked} onDismiss={notices.dismissTeamChanged} />
        )}
        {body}
        <SavedToast message={notices.saved} />
      </div>
    </AskBlocked.Provider>
  );
}

function EnvironmentBody({
  view,
  environment,
  onSaved,
  blocked,
}: {
  view: HubConfigView;
  environment: SourcedEnvironment;
  onSaved: (message: string, team: boolean) => void;
  blocked: string | null;
}) {
  const navigate = useNavigate();
  const { setOpen, addReference } = useDiscuss();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState<SectionId | null>(null);
  const project = view.project;
  const tightenedByMe = isTeams(environment) && isMine(environment);
  const { startRemove, startLoosen, dialogs } = useEnvironmentRemoval({
    view,
    onSaved,
    onDone: (removal) => {
      if (removal.kind === "remove") void navigate(environmentsPage(project));
    },
  });

  const openService = params.get("service");
  const [panelRepo, panelService] = openService ? openService.split("/", 2) : [];
  const setService = (repo: string | null, service?: string) => {
    setParams(
      (prev) => {
        if (repo === null) prev.delete("service");
        else prev.set("service", `${repo}/${service ?? ""}`);
        return prev;
      },
      { replace: true },
    );
  };

  const sectionProps = (id: SectionId) => ({
    id,
    editing: editing === id,
    locked:
      editing !== null && editing !== id
        ? `Save or cancel the ${SECTION_WORD[editing]} change first.`
        : null,
    onEdit: () => {
      setEditing(id);
    },
    onDone: () => {
      setEditing(null);
    },
  });
  const saved = (message: string, team: boolean) => {
    setEditing(null);
    onSaved(message, team);
  };

  return (
    <>
      <header className="ah-config-head">
        <div className="ah-stack" style={{ gap: 4, minWidth: 0 }}>
          <h1 className="ah-h1 ah-env-name">
            <span className="ah-mono">{environment.name}</span>
            {environment.production && <ProductionBadge />}
            <EnvironmentSource environment={environment} />
          </h1>
          {environment.description && (
            <p className="ah-muted ah-small" style={{ margin: 0 }}>
              {environment.description}
            </p>
          )}
        </div>
        <div className="ah-row" style={{ gap: 8, flexShrink: 0 }}>
          <Tooltip label={blocked ?? undefined}>
            <Button
              icon="message-square"
              disabled={blocked !== null}
              onClick={() => {
                addReference({
                  id: `config:environments.${environment.name}`,
                  label: `Environment ${environment.name}`,
                  source: isMine(environment) ? "hub.local.json" : "hub.json",
                  quote: `environments.${environment.name}: access ${environment.access}${environment.production ? ", production" : ""}`,
                });
                setOpen(true);
              }}
            >
              Ask Claude about {environment.name}
            </Button>
          </Tooltip>
          {tightenedByMe ? (
            <Button
              variant="ghost"
              icon="undo-2"
              onClick={() => {
                startLoosen(environment);
              }}
            >
              Use the team&apos;s access
            </Button>
          ) : (
            <Button
              variant="ghost"
              icon="x"
              onClick={() => {
                startRemove(environment);
              }}
            >
              Remove environment
            </Button>
          )}
        </div>
      </header>

      <div className="ah-env-detail">
        <div className="ah-card ah-env-sections">
          <AccessSection
            {...sectionProps("access")}
            view={view}
            environment={environment}
            onSaved={saved}
          />
          <SecretsSection
            {...sectionProps("secrets")}
            view={view}
            environment={environment}
            onSaved={saved}
          />
          <DescriptionSection
            {...sectionProps("description")}
            view={view}
            environment={environment}
            onSaved={saved}
          />
          <ServicesHere
            view={view}
            environment={environment}
            blocked={blocked}
            onOpen={(repo, service) => {
              setService(repo, service);
            }}
            onAdd={() => {
              void navigate(addServicePath(project), {
                state: {
                  returnTo: environmentPath(project, environment.name),
                  returnLabel: environment.name,
                },
              });
            }}
          />
        </div>
        <AgentsSee view={view} environment={environment} />
      </div>

      {panelRepo && panelService && (
        <ServicePanel
          view={view}
          repo={panelRepo}
          service={panelService}
          focusEnvironment={environment.name}
          onClose={() => {
            setService(null);
          }}
          onSaved={onSaved}
        />
      )}
      {dialogs}
    </>
  );
}

interface SectionProps {
  id: SectionId;
  editing: boolean;
  /** Why "Change" is off: another section is being changed. */
  locked: string | null;
  onEdit: () => void;
  onDone: () => void;
  view: HubConfigView;
  environment: SourcedEnvironment;
  onSaved: (message: string, team: boolean) => void;
}

/** One section of the page: its title and "Change" in read mode; its form and Save in edit mode. */
function Section({
  id,
  title,
  editing,
  locked,
  onEdit,
  environmentName,
  read,
  form,
}: {
  id: SectionId;
  title: string;
  editing: boolean;
  locked: string | null;
  onEdit: () => void;
  environmentName: string;
  read: ReactNode;
  form: ReactNode;
}) {
  const headingId = `ah-env-section-${id}`;
  return (
    <section className="ah-env-section" aria-labelledby={headingId}>
      <div className="ah-env-section-head">
        <h2 className="ah-h3" id={headingId}>
          {title}
        </h2>
        {!editing && (
          <Tooltip label={locked ?? undefined}>
            <Button
              size="sm"
              disabled={locked !== null}
              aria-label={`Change ${title.toLowerCase()} in ${environmentName}`}
              onClick={onEdit}
            >
              Change
            </Button>
          </Tooltip>
        )}
      </div>
      {editing ? form : read}
    </section>
  );
}

/** A section form's footer: Cancel, then the section's save verb; a refusal above it. Escape
 * cancels while no dialog is open above it. */
function SectionForm({
  children,
  saveLabel,
  pending,
  refusal,
  canSave = true,
  onCancel,
  onSave,
}: {
  children: ReactNode;
  saveLabel: string;
  pending: boolean;
  refusal: Refusal | null;
  canSave?: boolean;
  onCancel: () => void;
  onSave: () => void;
}) {
  const latest = useRef({ onCancel, pending });
  useEffect(() => {
    latest.current = { onCancel, pending };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || latest.current.pending) return;
      if (document.querySelector("[data-ah-dialog], .ah-side-panel")) return;
      latest.current.onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  return (
    <form
      className="ah-stack ah-env-section-form"
      style={{ gap: 16 }}
      onSubmit={(event) => {
        event.preventDefault();
        if (canSave && !pending) onSave();
      }}
    >
      {children}
      {refusal && (
        <p role="alert" className="ah-config-error">
          {refusal.summary}
        </p>
      )}
      <div className="ah-env-section-actions">
        <Button variant="ghost" disabled={pending} onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!canSave || pending}>
          {pending ? "Saving…" : saveLabel}
        </Button>
      </div>
    </form>
  );
}

/** Sends one section's edit; the result says what was saved, or why not. */
function useSectionSave(view: HubConfigView, onSaved: (message: string, team: boolean) => void) {
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  return {
    pending,
    refusal,
    save: (edit: EnvironmentEdit | null, message: string, team: boolean) => {
      if (edit === null) {
        onSaved(message, false);
        return;
      }
      setPending(true);
      setRefusal(null);
      postEnvironmentEdit(client, view.project, edit)
        .then(() => {
          setPending(false);
          onSaved(message, team);
        })
        .catch((error: unknown) => {
          setPending(false);
          setRefusal(refusalOf(error));
        });
    },
  };
}

/* Each section's form exists only while that section is being changed: it starts from the record
   every time it opens, with nothing to reset. */

interface FormProps {
  view: HubConfigView;
  environment: SourcedEnvironment;
  onDone: () => void;
  onSaved: (message: string, team: boolean) => void;
}

function AccessSection(props: SectionProps) {
  const { environment, editing } = props;
  const teams = isTeams(environment);
  const read = (
    <div className="ah-stack" style={{ gap: 4 }}>
      <AccessValue environment={environment} />
      {teams && isMine(environment) && environment.team_access !== environment.access && (
        <span className="ah-small ah-muted">
          Team: {ACCESS_LOOK[environment.team_access ?? "write"].short}. You made it stricter for
          your agents.
        </span>
      )}
      {environment.production && (
        <span className="ah-small ah-muted">
          Production: actions never write or delete here, whatever the access.
        </span>
      )}
    </div>
  );
  return (
    <Section
      {...props}
      title="What agents may do"
      environmentName={environment.name}
      read={read}
      form={editing ? <AccessForm {...props} /> : null}
    />
  );
}

function AccessForm({ view, environment, onDone, onSaved }: FormProps) {
  const id = useId();
  const teams = isTeams(environment);
  const teamAccess = environment.team_access ?? null;
  const localBroken = view.local_file.problems.length > 0;
  const [scope, setScope] = useState<"team" | "local">(isMine(environment) ? "local" : "team");
  const [access, setAccess] = useState<Access>(environment.access);
  const [production, setProduction] = useState(environment.production);
  const { pending, refusal, save } = useSectionSave(view, onSaved);
  const tightening = teams && scope === "local";

  const submit = () => {
    const message = `Saved the access of ${environment.name}`;
    if (tightening) {
      if (access === teamAccess) {
        save(
          environment.access === teamAccess
            ? null
            : { op: "remove_environment", scope: "local", name: environment.name },
          message,
          false,
        );
        return;
      }
      save(
        { op: "set_environment", scope: "local", name: environment.name, access },
        message,
        false,
      );
      return;
    }
    const target = teams ? "team" : "local";
    save(
      { op: "set_environment", scope: target, name: environment.name, access, production },
      message,
      target === "team",
    );
  };

  return (
    <SectionForm
      saveLabel="Save access"
      pending={pending}
      refusal={refusal}
      onCancel={onDone}
      onSave={submit}
    >
      {teams && (
        <fieldset className="ah-env-fieldset">
          <legend className="ah-config-field-label">Change it for</legend>
          <div className="ah-options">
            <OptionRow
              type="radio"
              name={`${id}-scope`}
              icon="users"
              label="The whole team"
              description="Saved in hub.json. Every developer's agents follow it once the hub PR merges."
              checked={scope === "team"}
              onToggle={() => {
                setScope("team");
                if (teamAccess) setAccess(teamAccess);
              }}
            />
            <OptionRow
              type="radio"
              name={`${id}-scope`}
              icon="laptop"
              label="Only me"
              disabled={localBroken}
              description={
                localBroken
                  ? "Your hub.local.json has a problem; fix it first."
                  : `Saved in hub.local.json. You can only make it stricter than the team's ${ACCESS_LOOK[teamAccess ?? "write"].short}.`
              }
              checked={scope === "local"}
              onToggle={() => {
                setScope("local");
                setAccess(environment.access);
                setProduction(environment.production);
              }}
            />
          </div>
        </fieldset>
      )}
      <AccessFields
        idPrefix={`${id}-fields`}
        legend={`What may agents do in ${environment.name}?`}
        access={access}
        onAccess={setAccess}
        production={production}
        onProduction={setProduction}
        looser={(candidate) =>
          tightening && teamAccess !== null && STRICTNESS[candidate] < STRICTNESS[teamAccess]
            ? "Stricter than the team's only."
            : null
        }
        productionLocked={tightening ? "Only the team decides what is production." : undefined}
      />
    </SectionForm>
  );
}

function secretsFromOf(environment: SourcedEnvironment): SecretsFrom {
  if (environment.credentials?.env_file) return "file";
  if ((environment.credentials?.env ?? []).length > 0) return "shell";
  return "none";
}

function SecretsSection(props: SectionProps) {
  const { environment, editing } = props;
  const credentials = environment.credentials;
  const read =
    credentials?.env_file || (credentials?.env ?? []).length > 0 || credentials?.aws_profile ? (
      <CredentialLine environment={environment} />
    ) : (
      <span className="ah-muted">Not yet: scripted actions get no secrets here.</span>
    );
  return (
    <Section
      {...props}
      title="Secrets for scripted actions"
      environmentName={environment.name}
      read={read}
      form={editing ? <SecretsForm {...props} /> : null}
    />
  );
}

function SecretsForm({ view, environment, onDone, onSaved }: FormProps) {
  const id = useId();
  const credentials = environment.credentials;
  const [secretsFrom, setSecretsFrom] = useState<SecretsFrom>(secretsFromOf(environment));
  const [envFile, setEnvFile] = useState(credentials?.env_file ?? "");
  const [variables, setVariables] = useState((credentials?.env ?? []).join("\n"));
  const [awsProfile, setAwsProfile] = useState(credentials?.aws_profile ?? "");
  const { pending, refusal, save } = useSectionSave(view, onSaved);
  const team = isTeams(environment);

  const fileMissing = secretsFrom === "file" && envFile.trim() === "";
  const shellMissing = secretsFrom === "shell" && linesOf(variables).length === 0;
  const canSave = !fileMissing && !shellMissing && lineWithValue(variables) === null;

  return (
    <SectionForm
      saveLabel="Save secrets"
      pending={pending}
      refusal={refusal}
      canSave={canSave}
      onCancel={onDone}
      onSave={() => {
        save(
          {
            op: "set_environment",
            scope: team ? "team" : "local",
            name: environment.name,
            env_file: secretsFrom === "file" ? envFile.trim() : "",
            credential_env: secretsFrom === "shell" ? linesOf(variables) : [],
            aws_profile: awsProfile.trim(),
          },
          `Saved the secrets of ${environment.name}`,
          team,
        );
      }}
    >
      {team && (
        <Banner tone="info" boxed>
          Secrets of a team environment are the team&apos;s: saving changes hub.json.
        </Banner>
      )}
      <SecretsFields
        idPrefix={`${id}-fields`}
        legend={`Where do the secrets for scripted actions in ${environment.name} live?`}
        project={view.project}
        firstRepo={view.repos[0]?.dir}
        environmentName={environment.name}
        secretsFrom={secretsFrom}
        onSecretsFrom={setSecretsFrom}
        envFile={envFile}
        onEnvFile={setEnvFile}
        variables={variables}
        onVariables={setVariables}
        awsProfile={awsProfile}
        onAwsProfile={setAwsProfile}
      />
    </SectionForm>
  );
}

function DescriptionSection(props: SectionProps) {
  const { environment, editing } = props;
  return (
    <Section
      {...props}
      title="Description"
      environmentName={environment.name}
      read={
        environment.description ? (
          <span>{environment.description}</span>
        ) : (
          <span className="ah-muted">None yet.</span>
        )
      }
      form={editing ? <DescriptionForm {...props} /> : null}
    />
  );
}

function DescriptionForm({ view, environment, onDone, onSaved }: FormProps) {
  const id = useId();
  const [description, setDescription] = useState(environment.description ?? "");
  const { pending, refusal, save } = useSectionSave(view, onSaved);
  const team = isTeams(environment);
  return (
    <SectionForm
      saveLabel="Save description"
      pending={pending}
      refusal={refusal}
      onCancel={onDone}
      onSave={() => {
        save(
          {
            op: "set_environment",
            scope: team ? "team" : "local",
            name: environment.name,
            description: description.trim(),
          },
          `Saved the description of ${environment.name}`,
          team,
        );
      }}
    >
      <div className="ah-stack" style={{ gap: 4 }}>
        <label htmlFor={`${id}-description`} className="ah-sr">
          Description
        </label>
        <input
          id={`${id}-description`}
          className="ah-input ah-setup-input"
          value={description}
          maxLength={DESCRIPTION_MAX}
          onChange={(event) => {
            setDescription(event.target.value);
          }}
        />
        <span className="ah-small ah-muted">
          Helps agents tell environments apart. {description.length} / {DESCRIPTION_MAX}
        </span>
      </div>
    </SectionForm>
  );
}

/** The services this environment reaches, grouped by repo, each with its address here; the
 * project's other services follow, folded, so one can be given an address here. */
function ServicesHere({
  view,
  environment,
  blocked,
  onOpen,
  onAdd,
}: {
  view: HubConfigView;
  environment: SourcedEnvironment;
  blocked: string | null;
  onOpen: (repo: string, service: string) => void;
  onAdd: () => void;
}) {
  const services = view.environments.services;
  const addressOf = (service: SourcedService) =>
    service.endpoints.find((item) => item.environment === environment.name);
  const here = services.filter((service) => addressOf(service) !== undefined);
  const elsewhere = services.filter((service) => addressOf(service) === undefined);
  const repos = view.repos
    .map((repo) => ({ dir: repo.dir, items: here.filter((service) => service.repo === repo.dir) }))
    .filter((repo) => repo.items.length > 0);
  return (
    <section className="ah-env-section" aria-labelledby="ah-env-section-services">
      <div className="ah-env-section-head">
        <h2 className="ah-h3" id="ah-env-section-services">
          Services in {environment.name}{" "}
          <span className="ah-muted ah-env-count">{here.length}</span>
        </h2>
        <span className="ah-row" style={{ gap: 8 }}>
          <FindWithClaude project={view.project} blocked={blocked} />
          <Button size="sm" icon="plus" onClick={onAdd}>
            Add service
          </Button>
        </span>
      </div>
      {here.length === 0 ? (
        <span className="ah-muted">
          {services.length === 0
            ? "No services yet. Add the API, portal or database each repo runs."
            : `No service has an address in ${environment.name} yet. Open one below to add it.`}
        </span>
      ) : (
        repos.map((repo) => (
          <div key={repo.dir} className="ah-stack" style={{ gap: 6 }}>
            <span className="ah-env-name ah-small ah-muted">
              <Icon name="book" />
              {repo.dir}
            </span>
            <ul className="ah-env-services-here">
              {repo.items.map((service) => (
                <ServiceRow
                  key={service.name}
                  service={service}
                  environment={environment.name}
                  onOpen={onOpen}
                />
              ))}
            </ul>
          </div>
        ))
      )}
      {elsewhere.length > 0 && (
        <details className="ah-env-elsewhere">
          <summary className="ah-small">
            {elsewhere.length === 1
              ? "1 service of this project is not here yet"
              : `${String(elsewhere.length)} services of this project are not here yet`}
          </summary>
          <ul className="ah-env-services-here">
            {elsewhere.map((service) => (
              <ServiceRow
                key={`${service.repo}/${service.name}`}
                service={service}
                environment={environment.name}
                onOpen={onOpen}
                withRepo
              />
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** One service: its name and kind, its address in this environment (or "Not here yet"). */
function ServiceRow({
  service,
  environment,
  onOpen,
  withRepo = false,
}: {
  service: SourcedService;
  environment: string;
  onOpen: (repo: string, service: string) => void;
  withRepo?: boolean;
}) {
  const endpoint = service.endpoints.find((item) => item.environment === environment);
  const label = serviceLabel(service.repo, service.name);
  const shown = endpoint ? endpointText(endpoint) : null;
  const note = endpoint ? endpointValues(endpoint).note : "";
  return (
    <li className="ah-env-service-item">
      <button
        type="button"
        className="ah-env-service-row"
        aria-label={
          shown
            ? `Open ${label}: ${shown} in ${environment}`
            : `Open ${label}: not in ${environment} yet`
        }
        onClick={() => {
          onOpen(service.repo, service.name);
        }}
      >
        <span className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
          <Mono>{withRepo ? label : service.name}</Mono>
          {service.kind && (
            <span className="ah-small ah-muted">
              {serviceKind(service.kind)?.label ?? service.kind}
            </span>
          )}
        </span>
        <span className="ah-row ah-mono ah-small" style={{ gap: 6, minWidth: 0 }}>
          {shown ? (
            <>
              <PathText path={shown} max={48} />
              {endpoint?.source === LOCAL_FILE && <Icon name="laptop" title="Set by you" />}
              {note && <Icon name="info" title={note} />}
            </>
          ) : (
            <span className="ah-muted">Not here yet</span>
          )}
        </span>
        <Icon name="chevron-right" />
      </button>
      {shown && (
        <CopyButton
          text={shown}
          label={`Copy the address of ${label} in ${environment}`}
          className="ah-env-copy"
          compact
        />
      )}
    </li>
  );
}

/** What agents read about this environment, derived from the record. */
function AgentsSee({
  view,
  environment,
}: {
  view: HubConfigView;
  environment: SourcedEnvironment;
}) {
  const here = view.environments.services.flatMap((service) =>
    service.endpoints
      .filter((endpoint) => endpoint.environment === environment.name)
      .map((endpoint) => ({ service, endpoint })),
  );
  const mine = isMine(environment) && !isTeams(environment);
  return (
    <aside className="ah-card ah-setup-preview" aria-label="What agents see">
      <div className="ah-setup-preview-title">
        <Icon name="scan-eye" /> What agents see{" "}
        <DerivedLabel how="Built from hub.json and hub.local.json">Preview</DerivedLabel>
      </div>
      <div className="ah-small ah-muted">
        {mine ? "Not in AGENTS.md: only your sessions' brief lists it." : "In AGENTS.md"}
      </div>
      <div className="ah-setup-preview-line">
        <code className="ah-mono">{environment.name}</code>{" "}
        <span className="ah-muted">
          ({environment.access}
          {environment.production ? ", production" : ""})
        </span>
        {environment.description ? `: ${environment.description}` : ""}
      </div>
      <div className="ah-small ah-muted">In each session&apos;s brief</div>
      <ul className="ah-setup-preview-list">
        <li>
          <Icon name={ACCESS_LOOK[environment.access].icon} /> {ACCESS_LOOK[environment.access].row}
        </li>
        {here.map(({ service, endpoint }) => (
          <li key={`${service.repo}/${service.name}`}>
            <span className="ah-mono">{service.name}</span>{" "}
            <code className="ah-mono">{endpointText(endpoint)}</code>
          </li>
        ))}
      </ul>
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        Agents never see secret values or the env file&apos;s contents.
      </p>
    </aside>
  );
}
