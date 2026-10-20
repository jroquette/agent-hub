import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button, Dialog, SegmentedControl } from "../../components";
import {
  endpointValues,
  isTeams,
  postEnvironmentEdit,
  refusalOf,
  serviceLabel,
} from "./environments";
import type { HubConfigView, Refusal, SourcedEndpoint } from "./environments";

const NEW_SERVICE = "\u0000new";

export interface EndpointTarget {
  repo?: string | undefined;
  service?: string | undefined;
  environment?: string | undefined;
  /** The endpoint to change; absent adds one. */
  endpoint?: SourcedEndpoint | undefined;
}

/**
 * Add or change where a repo's service runs in one environment: a URL or a resource name. The
 * file is the environment's: a team environment's endpoint goes in hub.json, the developer's own
 * in hub.local.json; the dialog says which, it is not a choice.
 */
export function EndpointDialog({
  view,
  target,
  onClose,
  onSaved,
}: {
  view: HubConfigView;
  target: EndpointTarget;
  onClose: () => void;
  onSaved: (message: string, team: boolean) => void;
}) {
  const id = useId();
  const client = useQueryClient();
  const editing = target.endpoint ?? null;
  const values = editing ? endpointValues(editing) : null;
  const environments = view.environments.environments;
  const [repo, setRepo] = useState(target.repo ?? view.repos[0]?.dir ?? "");
  const servicesOf = (dir: string) =>
    view.environments.services.filter((service) => service.repo === dir);
  const [service, setService] = useState(
    target.service ?? servicesOf(repo)[0]?.name ?? NEW_SERVICE,
  );
  const [newService, setNewService] = useState("");
  const [kind, setKind] = useState("");
  const [environment, setEnvironment] = useState(target.environment ?? environments[0]?.name ?? "");
  const [where, setWhere] = useState<"url" | "resource">(values?.resource ? "resource" : "url");
  const [value, setValue] = useState(values?.url ?? values?.resource ?? "");
  const [note, setNote] = useState(values?.note ?? "");
  const [pending, setPending] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  const chosen = environments.find((item) => item.name === environment);
  const team = chosen !== undefined && isTeams(chosen);
  const serviceName = service === NEW_SERVICE ? newService.trim() : service;
  const fieldId = (key: string) => `${id}-${key}`;
  const shownError = (key: string) => refusal?.fields[key];
  const fixed = editing !== null;

  const send = (remove: boolean) => {
    if (!remove && (serviceName === "" || value.trim() === "")) {
      setRefusal({
        summary: "Nothing was saved: fix the fields marked below.",
        fields: {
          ...(serviceName === "" ? { service: "Name the service." } : {}),
          ...(value.trim() === ""
            ? { [where]: where === "url" ? "Give the URL." : "Give the resource name." }
            : {}),
        },
      });
      return;
    }
    setPending(true);
    setRefusal(null);
    const scope = team ? "team" : "local";
    const label = serviceLabel(repo, serviceName);
    const edit = remove
      ? ({
          op: "remove_endpoint",
          scope,
          repo,
          service: serviceName,
          environment,
        } as const)
      : ({
          op: "add_endpoint",
          scope,
          repo,
          service: serviceName,
          environment,
          url: where === "url" ? value.trim() : null,
          resource: where === "resource" ? value.trim() : null,
          kind: service === NEW_SERVICE ? kind.trim() || null : null,
          note: note.trim() || null,
          replace: editing !== null,
        } as const);
    postEnvironmentEdit(client, view.project, edit)
      .then(() => {
        onClose();
        onSaved(
          remove
            ? `Removed the ${environment} endpoint of ${label}`
            : `${editing ? "Saved" : "Added"} the ${environment} endpoint of ${label}`,
          team,
        );
      })
      .catch((error: unknown) => {
        setPending(false);
        setRefusal(refusalOf(error));
      });
  };

  const title = fixed
    ? `Edit endpoint · ${serviceLabel(repo, serviceName)} · ${environment}`
    : "Add endpoint";

  return (
    <Dialog
      title={title}
      size="md"
      onClose={onClose}
      pending={pending}
      initialFocus={
        target.environment !== undefined ? `#${CSS.escape(fieldId("value"))}` : undefined
      }
      footer={
        <>
          {fixed && (
            <Button
              variant="danger"
              disabled={pending}
              style={{ marginRight: "auto" }}
              onClick={() => {
                send(true);
              }}
            >
              Remove endpoint
            </Button>
          )}
          <Button disabled={pending} onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={pending || environments.length === 0}
            onClick={() => {
              send(false);
            }}
          >
            {pending ? "Saving…" : fixed ? "Save endpoint" : "Add endpoint"}
          </Button>
        </>
      }
    >
      <form
        className="ah-stack ah-config-form"
        style={{ gap: 14 }}
        onSubmit={(event) => {
          event.preventDefault();
          send(false);
        }}
      >
        {refusal && (
          <p role="alert" className="ah-config-error">
            {refusal.summary}
          </p>
        )}
        <div className="ah-env-grid">
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId("repo")} className="ah-config-field-label">
              Repo
            </label>
            <select
              id={fieldId("repo")}
              className="ah-input"
              value={repo}
              disabled={fixed || target.repo !== undefined}
              onChange={(event) => {
                setRepo(event.target.value);
                setService(servicesOf(event.target.value)[0]?.name ?? NEW_SERVICE);
              }}
            >
              {view.repos.map((item) => (
                <option key={item.dir} value={item.dir}>
                  {item.dir}
                </option>
              ))}
            </select>
          </div>
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId("service")} className="ah-config-field-label">
              Service
            </label>
            <select
              id={fieldId("service")}
              className="ah-input"
              value={service}
              disabled={fixed || target.service !== undefined}
              onChange={(event) => {
                setService(event.target.value);
              }}
            >
              {servicesOf(repo).map((item) => (
                <option key={item.name} value={item.name}>
                  {item.kind ? `${item.name} · ${item.kind}` : item.name}
                </option>
              ))}
              <option value={NEW_SERVICE}>New service…</option>
            </select>
          </div>
        </div>
        {service === NEW_SERVICE && (
          <div className="ah-env-grid">
            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={fieldId("new-service")} className="ah-config-field-label">
                Service name
              </label>
              <input
                id={fieldId("new-service")}
                className="ah-input ah-mono"
                value={newService}
                autoComplete="off"
                spellCheck={false}
                placeholder="api"
                aria-invalid={shownError("service") ? true : undefined}
                onChange={(event) => {
                  setNewService(event.target.value);
                }}
              />
              {shownError("service") && (
                <span className="ah-small ah-config-error">{shownError("service")}</span>
              )}
            </div>
            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={fieldId("kind")} className="ah-config-field-label">
                Kind <span className="ah-muted">(optional)</span>
              </label>
              <input
                id={fieldId("kind")}
                className="ah-input ah-mono"
                value={kind}
                autoComplete="off"
                spellCheck={false}
                placeholder="api, dynamodb, queue…"
                aria-invalid={shownError("kind") ? true : undefined}
                onChange={(event) => {
                  setKind(event.target.value);
                }}
              />
              {shownError("kind") && (
                <span className="ah-small ah-config-error">{shownError("kind")}</span>
              )}
            </div>
          </div>
        )}
        <div className="ah-stack" style={{ gap: 4 }}>
          <label htmlFor={fieldId("environment")} className="ah-config-field-label">
            Environment
          </label>
          <select
            id={fieldId("environment")}
            className="ah-input"
            value={environment}
            disabled={fixed || target.environment !== undefined}
            onChange={(event) => {
              setEnvironment(event.target.value);
            }}
          >
            {environments.map((item) => (
              <option key={item.name} value={item.name}>
                {item.production ? `${item.name} · Production` : item.name}
              </option>
            ))}
          </select>
          {chosen && (
            <span className="ah-small ah-muted">
              {team
                ? `Saved in hub.json: ${chosen.name} is the team's.`
                : `Saved in hub.local.json: ${chosen.name} is yours.`}
            </span>
          )}
        </div>
        <div className="ah-stack" style={{ gap: 6 }}>
          <span className="ah-config-field-label">Where</span>
          <SegmentedControl
            label="Where"
            options={[
              { id: "url", label: "URL" },
              { id: "resource", label: "Resource" },
            ]}
            value={where}
            onChange={(next) => {
              setWhere(next === "resource" ? "resource" : "url");
            }}
          />
          <input
            id={fieldId("value")}
            aria-label={where === "url" ? "URL" : "Resource name"}
            className="ah-input ah-mono"
            value={value}
            autoComplete="off"
            spellCheck={false}
            placeholder={where === "url" ? "https://api.example.com" : "demo-orders-staging"}
            aria-invalid={shownError(where) ? true : undefined}
            aria-describedby={`${fieldId("value")}-help`}
            onChange={(event) => {
              setValue(event.target.value);
            }}
          />
          <span
            id={`${fieldId("value")}-help`}
            className={shownError(where) ? "ah-small ah-config-error" : "ah-small ah-muted"}
          >
            {shownError(where) ??
              (where === "url"
                ? "scheme://host[:port][/path], e.g. https://api.example.com. No user, ? or #."
                : "A name, e.g. a table, queue or bucket: demo-orders-staging.")}
          </span>
        </div>
        <div className="ah-stack" style={{ gap: 4 }}>
          <label htmlFor={fieldId("note")} className="ah-config-field-label">
            Note <span className="ah-muted">(optional)</span>
          </label>
          <input
            id={fieldId("note")}
            className="ah-input"
            value={note}
            placeholder="read replica; use for reports"
            aria-invalid={shownError("note") ? true : undefined}
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
          {shownError("note") && (
            <span className="ah-small ah-config-error">{shownError("note")}</span>
          )}
        </div>
      </form>
    </Dialog>
  );
}
