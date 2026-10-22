import { Fragment, useEffect, useId, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import {
  Button,
  ConfirmDialog,
  CopyButton,
  DerivedLabel,
  EmptyState,
  Icon,
  PathText,
  ProblemError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
} from "../../components";
import { apiDelete, apiKey, useApi } from "../../lib/api";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import {
  ACCESS_LOOK,
  addServicePath,
  count,
  environmentsPage,
  isTeams,
  postEnvironmentEdits,
  refusalOf,
  serviceKind,
  serviceLabel,
} from "../hub-config/environments";
import { Mono } from "../hub-config/parts";
import { SavedToast, UncommittedNotice, useSaveNotices } from "../hub-config/notices";
import {
  STATUS_LOOK,
  addressesToApply,
  applyPlan,
  countByStatus,
  defaultSelection,
  environmentKey,
  serviceKey,
} from "./discovery";
import type {
  DiscoveryProposal,
  EnvironmentDiscovery,
  ProposalStatus,
  ProposedAddress,
  ProposedEnvironment,
  ProposedService,
} from "./discovery";
import "../hub-config/hub-config.css";

type Filter = ProposalStatus | "all";
type Evidence = ProposedEnvironment["evidence"][number];

/** `/projects/:project/environments/discover/:discoveryId`: decide each proposal. */
export function ReviewScreen() {
  const { project = "", discoveryId = "" } = useParams();
  const found = useApi("/api/v1/projects/{project}/environment-discoveries/{discovery_id}", {
    path: { project, discovery_id: discoveryId },
  });
  const config = useApi("/api/v1/projects/{project}/config", { path: { project } });
  const notices = useSaveNotices();
  useEffect(() => {
    document.title = `Review what Claude found · ${project}`;
  }, [project]);

  let body: ReactNode;
  if (found.isError || config.isError)
    body = (
      <ProblemError
        title="Could not read Claude's proposal"
        detail={(found.error ?? config.error)?.detail}
        status={(found.error ?? config.error)?.status}
        onRetry={() => {
          void found.refetch();
          void config.refetch();
        }}
      />
    );
  else if (!found.data || !config.data) body = <Skeleton height={320} />;
  else if (!found.data.proposal)
    body = (
      <EmptyState icon="folder-search" title="No proposal yet">
        Claude has not sent its proposal for this search.{" "}
        <Link
          to={`/projects/${encodeURIComponent(project)}/environments/discover?discovery=${encodeURIComponent(discoveryId)}`}
        >
          See its progress
        </Link>
        .
      </EmptyState>
    );
  else
    body = (
      <Review
        project={project}
        discovery={found.data}
        proposal={found.data.proposal}
        declared={
          new Map(
            config.data.environments.environments.map((environment) => [
              environment.name,
              isTeams(environment) ? ("team" as const) : ("local" as const),
            ]),
          )
        }
        onSaved={notices.onSaved}
      />
    );

  return (
    <div className="ah-page" style={{ gap: 16 }}>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: project, href: `/projects/${encodeURIComponent(project)}` },
          { label: "Environments", href: environmentsPage(project) },
          { label: "Review what Claude found" },
        ]}
      />
      {notices.teamChanged && (
        <UncommittedNotice blocked={null} onDismiss={notices.dismissTeamChanged} />
      )}
      {body}
      <SavedToast message={notices.saved} />
    </div>
  );
}

function Review({
  project,
  discovery,
  proposal,
  declared,
  onSaved,
}: {
  project: string;
  discovery: EnvironmentDiscovery;
  proposal: DiscoveryProposal;
  declared: ReadonlyMap<string, "team" | "local">;
  onSaved: (message: string, team: boolean) => void;
}) {
  const id = useId();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Set<string>>(() => defaultSelection(proposal));
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [discarding, setDiscarding] = useState(false);
  const counts = countByStatus(proposal);
  const plan = useMemo(
    () => applyPlan(proposal, selected, declared),
    [proposal, selected, declared],
  );
  const skippedOf = (key: string) => plan.skipped.find((item) => item.key === key)?.reason;
  const shows = (status: ProposalStatus) => filter === "all" || filter === status;

  const toggle = (key: string) => {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
  };
  const selectNew = () => {
    setSelected(defaultSelection(proposal));
  };

  const apply = () => {
    setPending(true);
    setFailure(null);
    postEnvironmentEdits(client, project, plan.ops)
      .then(() => {
        setPending(false);
        void client.invalidateQueries({
          queryKey: apiKey("/api/v1/projects/{project}/environment-discoveries/{discovery_id}", {
            path: { project, discovery_id: discovery.id },
          }),
        });
        setSelected(new Set());
        const parts = [
          plan.environments > 0 ? count(plan.environments, "environment") : null,
          plan.services > 0 ? count(plan.services, "service") : null,
        ].filter(Boolean);
        onSaved(`Added ${parts.join(" and ")}`, true);
      })
      .catch((error: unknown) => {
        setPending(false);
        setFailure(refusalOf(error).summary);
      });
  };

  const discard = () => {
    apiDelete("/api/v1/projects/{project}/environment-discoveries/{discovery_id}", {
      path: { project, discovery_id: discovery.id },
    })
      .then(() => {
        void client.invalidateQueries({
          queryKey: apiKey("/api/v1/projects/{project}/environment-discoveries", {
            path: { project },
          }),
        });
        void navigate(environmentsPage(project));
      })
      .catch((error: unknown) => {
        setDiscarding(false);
        setFailure(refusalOf(error).summary);
      });
  };

  const environmentRows = proposal.environments.filter((environment) => shows(environment.status));
  const servicesByRepo = discovery.repos
    .map((repo) => ({
      repo,
      services: proposal.services.filter(
        (service) => service.repo === repo && shows(service.status),
      ),
    }))
    .filter((group) => group.services.length > 0);
  const toAdd = plan.environments + plan.services;

  return (
    <>
      <header className="ah-config-head">
        <div className="ah-stack" style={{ gap: 4, minWidth: 0 }}>
          <h1 className="ah-h1 ah-env-name">
            Review what Claude found{" "}
            <DerivedLabel how="Read from the repos by Claude">Proposed by Claude</DerivedLabel>
          </h1>
          <p className="ah-muted ah-small" style={{ margin: 0 }}>
            Read {discovery.repos.join(", ")} ·{" "}
            <Link to={`/agent-sessions/${discovery.agent_session_id}`}>Open the conversation</Link>
          </p>
        </div>
        <Button
          variant="ghost"
          icon="x"
          onClick={() => {
            setDiscarding(true);
          }}
        >
          Discard proposal
        </Button>
      </header>

      <SegmentedControl
        label="Show"
        options={[
          { id: "all", label: `All ${String(counts.all)}` },
          { id: "new", label: `New ${String(counts.new)}` },
          { id: "differs", label: `Differs ${String(counts.differs)}` },
          { id: "declared", label: `Already declared ${String(counts.declared)}` },
        ]}
        value={filter}
        onChange={(next) => {
          setFilter(next as Filter);
        }}
      />

      {counts.all === 0 ? (
        <EmptyState icon="folder-search" title="Claude found nothing new">
          The repos you picked declare nothing it could match, or it is all here already.
        </EmptyState>
      ) : (
        <div className="ah-table-wrap">
          <table className="ah-table ah-env-table ah-review-table">
            <caption className="ah-sr">Proposals from Claude</caption>
            <colgroup>
              <col style={{ width: 44 }} />
              <col style={{ width: "26%" }} />
              <col />
              <col style={{ width: 220 }} />
              <col style={{ width: 150 }} />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">
                  <span className="ah-sr">Add</span>
                </th>
                <th scope="col">What</th>
                <th scope="col">Details</th>
                <th scope="col">Found in</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {environmentRows.length > 0 && (
                <GroupRow icon="server" title={`Environments ${String(environmentRows.length)}`} />
              )}
              {environmentRows.map((environment) => (
                <EnvironmentRow
                  key={environment.name}
                  idPrefix={id}
                  environment={environment}
                  checked={selected.has(environmentKey(environment))}
                  onToggle={() => {
                    toggle(environmentKey(environment));
                  }}
                />
              ))}
              {servicesByRepo.map((group) => (
                <Fragment key={group.repo}>
                  <GroupRow
                    icon="book"
                    title={`Services · ${group.repo} ${String(group.services.length)}`}
                  />
                  {group.services.map((service) => (
                    <ServiceRow
                      key={service.name}
                      idPrefix={id}
                      service={service}
                      checked={selected.has(serviceKey(service))}
                      skipped={skippedOf(serviceKey(service))}
                      onToggle={() => {
                        toggle(serviceKey(service));
                      }}
                    />
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {proposal.missing.length > 0 && (
        <section className="ah-env-block" aria-labelledby={`${id}-missing`}>
          <h2 className="ah-h3" id={`${id}-missing`}>
            Probably missing {proposal.missing.length}
          </h2>
          <ul className="ah-env-services-here">
            {proposal.missing.map((item) => (
              <li key={`${item.repo}/${item.name}`} className="ah-review-missing">
                <Icon name="triangle-alert" />
                <span className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
                  <span>
                    <Mono>{serviceLabel(item.repo, item.name)}</Mono>
                    {item.kind && (
                      <span className="ah-muted">
                        {" "}
                        · {serviceKind(item.kind)?.label ?? item.kind}
                      </span>
                    )}
                  </span>
                  <span className="ah-small ah-muted">{item.why}</span>
                  <EvidenceList evidence={item.evidence} />
                </span>
                <Link
                  className="ah-btn ah-btn-sm"
                  to={addServicePath(project, item.repo)}
                  state={{ returnTo: environmentsPage(project), returnLabel: "Environments" }}
                >
                  Add by hand
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(proposal.not_read.length > 0 || proposal.dropped.length > 0) && (
        <section className="ah-small ah-muted ah-stack" style={{ gap: 4 }}>
          {proposal.not_read.length > 0 && (
            <p style={{ margin: 0 }}>
              Not read {proposal.not_read.length}:{" "}
              {proposal.not_read.map((item) => `${item.path} (${item.reason})`).join(" · ")}
            </p>
          )}
          {proposal.dropped.length > 0 && (
            <p style={{ margin: 0 }}>
              Left out by agent-hub {proposal.dropped.length}:{" "}
              {proposal.dropped.map((item) => `${item.what}: ${item.reason}`).join(" · ")}
            </p>
          )}
        </section>
      )}

      <div className="ah-review-bar" role="region" aria-label="Add the selected proposals">
        <span aria-live="polite">{count(toAdd, "item")} selected</span>
        <Button size="sm" variant="ghost" onClick={selectNew}>
          Select all new
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setSelected(new Set());
          }}
        >
          Clear
        </Button>
        <span className="ah-grow" />
        {failure && (
          <span role="alert" className="ah-config-error ah-small">
            {failure}
          </span>
        )}
        <Button variant="primary" icon="plus" disabled={toAdd === 0 || pending} onClick={apply}>
          {pending ? "Adding…" : `Add ${String(toAdd)} for the team`}
        </Button>
      </div>

      {discarding && (
        <ConfirmDialog
          title="Discard Claude's proposal?"
          confirmLabel="Discard proposal"
          consequences={["The items you did not add are dropped. Nothing in hub.json changes."]}
          onCancel={() => {
            setDiscarding(false);
          }}
          onConfirm={discard}
        />
      )}
    </>
  );
}

function GroupRow({ icon, title }: { icon: "server" | "book"; title: string }) {
  return (
    <tr className="ah-env-repo">
      <th scope="rowgroup" colSpan={5}>
        <span className="ah-env-name">
          <Icon name={icon} />
          {title}
        </span>
      </th>
    </tr>
  );
}

function StatusCell({ status, yours }: { status: ProposalStatus; yours?: string | null }) {
  const look = STATUS_LOOK[status];
  return (
    <span className="ah-stack" style={{ gap: 2 }}>
      <span className="ah-env-access">
        <Icon name={look.icon} /> {look.label}
      </span>
      {status === "differs" && yours && <span className="ah-small ah-muted">yours: {yours}</span>}
    </span>
  );
}

function EvidenceList({ evidence }: { evidence: readonly Evidence[] }) {
  if (evidence.length === 0) return <span className="ah-muted">—</span>;
  const [first, ...rest] = evidence;
  if (!first) return null;
  const where = first.line ? `${first.path}:${String(first.line)}` : first.path;
  return (
    <span className="ah-env-access ah-small">
      <Icon name="file-text" />
      <span className="ah-mono">
        <PathText path={where} max={30} />
      </span>
      {rest.length > 0 && (
        <span className="ah-muted" title={rest.map((item) => item.path).join("\n")}>
          +{rest.length}
        </span>
      )}
      <CopyButton text={where} label={`Copy ${where}`} compact />
    </span>
  );
}

function SelectCell({
  id,
  label,
  checked,
  disabled,
  reason,
  onToggle,
}: {
  id: string;
  label: string;
  checked: boolean;
  disabled: boolean;
  reason?: string | undefined;
  onToggle: () => void;
}) {
  return (
    <td>
      <input
        id={id}
        type="checkbox"
        className="ah-review-check"
        aria-label={label}
        aria-describedby={reason ? `${id}-reason` : undefined}
        checked={checked && !disabled}
        disabled={disabled}
        onChange={onToggle}
      />
      {reason && (
        <span id={`${id}-reason`} className="ah-sr">
          {reason}
        </span>
      )}
    </td>
  );
}

function EnvironmentRow({
  idPrefix,
  environment,
  checked,
  onToggle,
}: {
  idPrefix: string;
  environment: ProposedEnvironment;
  checked: boolean;
  onToggle: () => void;
}) {
  const look = ACCESS_LOOK[environment.access];
  const declared = environment.status === "declared";
  return (
    <tr data-status={environment.status}>
      <SelectCell
        id={`${idPrefix}-env-${environment.name}`}
        label={`Add environment ${environment.name}`}
        checked={checked}
        disabled={declared}
        reason={declared ? "Nothing to add." : undefined}
        onToggle={onToggle}
      />
      <th scope="row">
        <span className="ah-env-name">
          <Mono>{environment.name}</Mono>
          {environment.production && <StatusBadge status="guard" label="Production" quiet />}
        </span>
      </th>
      <td>
        <span className="ah-stack" style={{ gap: 2 }}>
          <span className="ah-env-access">
            <Icon name={look.icon} /> {look.row}
          </span>
          {environment.description && (
            <span className="ah-small ah-muted">{environment.description}</span>
          )}
          {(environment.aws_profile ?? environment.env_file) && (
            <span className="ah-small ah-muted">
              {environment.aws_profile && (
                <>
                  AWS profile <Mono>{environment.aws_profile}</Mono>{" "}
                </>
              )}
              {environment.env_file && (
                <>
                  env file <Mono>{environment.env_file}</Mono>
                </>
              )}
            </span>
          )}
        </span>
      </td>
      <td>
        <EvidenceList evidence={environment.evidence} />
      </td>
      <td>
        <StatusCell status={environment.status} yours={environment.yours} />
      </td>
    </tr>
  );
}

function AddressLine({ address }: { address: ProposedAddress }) {
  return (
    <span className="ah-small" data-status={address.status}>
      <span className="ah-mono">{address.environment}</span>{" "}
      <code className="ah-mono">{address.address}</code>
      {address.status === "declared" && <span className="ah-muted"> · already yours</span>}
      {address.status === "differs" && address.yours && (
        <span className="ah-muted"> · yours: {address.yours}</span>
      )}
    </span>
  );
}

function ServiceRow({
  idPrefix,
  service,
  checked,
  skipped,
  onToggle,
}: {
  idPrefix: string;
  service: ProposedService;
  checked: boolean;
  skipped?: string | undefined;
  onToggle: () => void;
}) {
  const nothing = addressesToApply(service).length === 0;
  return (
    <tr data-status={service.status}>
      <SelectCell
        id={`${idPrefix}-svc-${service.repo}-${service.name}`}
        label={`Add ${serviceLabel(service.repo, service.name)}`}
        checked={checked}
        disabled={nothing}
        reason={nothing ? "Nothing to add." : undefined}
        onToggle={onToggle}
      />
      <th scope="row">
        <span className="ah-stack" style={{ gap: 2 }}>
          <Mono>{service.name}</Mono>
          {service.kind && (
            <span className="ah-small ah-muted">
              {serviceKind(service.kind)?.label ?? service.kind}
            </span>
          )}
        </span>
      </th>
      <td>
        <span className="ah-stack" style={{ gap: 2 }}>
          {service.addresses.map((address) => (
            <AddressLine key={address.environment} address={address} />
          ))}
          {checked && skipped && <span className="ah-small ah-config-error">{skipped}</span>}
        </span>
      </td>
      <td>
        <EvidenceList evidence={service.evidence} />
      </td>
      <td>
        <StatusCell status={service.status} />
      </td>
    </tr>
  );
}
