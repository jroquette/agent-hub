import { useId, useMemo, useState } from "react";
import type { RefObject } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button, ConfirmDialog, Icon, IconButton, SidePanel } from "../../components";
import { AddressList } from "./environmentFields";
import {
  LOCAL_FILE,
  SERVICE_KINDS,
  count,
  endpointText,
  endpointValues,
  isTeams,
  postEnvironmentEdits,
  refusalOf,
  serviceKind,
  serviceLabel,
} from "./environments";
import type { HubConfigView, SingleEdit } from "./environments";

/**
 * One service over the page: its kind, description and its address in every environment, all
 * changed as drafts and saved together in one write. Removing an address strikes its row until
 * Save (Undo brings it back); removing the service asks first.
 */
export function ServicePanel({
  view,
  repo,
  service,
  focusEnvironment,
  openerRef,
  onClose,
  onSaved,
}: {
  view: HubConfigView;
  repo: string;
  service: string;
  /** The environment whose address gets the focus. */
  focusEnvironment?: string | undefined;
  /** The row that opened the panel: focus goes back to it on close. */
  openerRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSaved: (message: string, team: boolean) => void;
}) {
  const id = useId();
  const client = useQueryClient();
  const environments = view.environments.environments;
  const record = view.environments.services.find(
    (item) => item.repo === repo && item.name === service,
  );
  const label = serviceLabel(repo, service);
  const original = useMemo(() => {
    const found: Record<string, string> = {};
    for (const endpoint of record?.endpoints ?? [])
      found[endpoint.environment] = endpointText(endpoint);
    return found;
  }, [record]);
  const [values, setValues] = useState<Record<string, string>>(original);
  const [removed, setRemoved] = useState<ReadonlySet<string>>(new Set());
  const [kind, setKind] = useState(record?.kind ?? "");
  const [description, setDescription] = useState(record?.description ?? "");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"discard" | "remove" | null>(null);

  // The file that declares the service: the team's when any of its addresses is.
  const declaredByTeam = (record?.endpoints ?? []).some(
    (endpoint) => endpoint.source !== LOCAL_FILE,
  );

  const ops = useMemo((): SingleEdit[] => {
    if (!record) return [];
    const changes: SingleEdit[] = [];
    for (const environment of environments) {
      const existing = record.endpoints.find((item) => item.environment === environment.name);
      const value = (values[environment.name] ?? "").trim();
      const scope = existing
        ? existing.source === LOCAL_FILE
          ? "local"
          : "team"
        : isTeams(environment)
          ? "team"
          : "local";
      if (removed.has(environment.name) || (existing && value === "")) {
        if (existing)
          changes.push({
            op: "remove_endpoint",
            scope,
            repo,
            service,
            environment: environment.name,
          });
        continue;
      }
      if (value === "" || value === (existing ? endpointText(existing) : "")) continue;
      const isUrl = value.includes("://");
      changes.push({
        op: "add_endpoint",
        scope,
        repo,
        service,
        environment: environment.name,
        url: isUrl ? value : null,
        resource: isUrl ? null : value,
        note: existing ? (endpointValues(existing).note ?? null) : null,
        replace: existing !== undefined,
      });
    }
    if (kind !== (record.kind ?? "") || description.trim() !== (record.description ?? "")) {
      changes.push({
        op: "set_service",
        scope: declaredByTeam ? "team" : "local",
        repo,
        service,
        kind,
        description: description.trim(),
      });
    }
    return changes;
  }, [record, environments, values, removed, kind, description, declaredByTeam, repo, service]);

  if (!record) {
    return (
      <SidePanel
        title={label}
        closeLabel={`Close ${label}`}
        openerRef={openerRef}
        onClose={onClose}
      >
        <p className="ah-muted">No service {label}. It may have been renamed or removed.</p>
      </SidePanel>
    );
  }

  const touchesTeam = (edits: readonly SingleEdit[]) =>
    edits.some((edit) => "scope" in edit && edit.scope === "team");

  const write = (edits: SingleEdit[], message: string, after: () => void) => {
    setPending(true);
    setFailure(null);
    postEnvironmentEdits(client, view.project, edits)
      .then(() => {
        setPending(false);
        onSaved(message, touchesTeam(edits));
        after();
      })
      .catch((error: unknown) => {
        setPending(false);
        setFailure(refusalOf(error).summary);
      });
  };

  const save = () => {
    const addresses = ops.filter((edit) => edit.op !== "set_service").length;
    write(
      ops,
      addresses > 0 ? `Saved ${count(addresses, "address")} of ${label}` : `Saved ${label}`,
      onClose,
    );
  };

  const removeService = () => {
    const files = new Set(record.endpoints.map((endpoint) => endpoint.source));
    const edits: SingleEdit[] = [...files].map((file) => ({
      op: "remove_endpoint",
      scope: file === LOCAL_FILE ? "local" : "team",
      repo,
      service,
    }));
    write(edits, `Removed ${label}`, onClose);
  };

  const close = () => {
    if (ops.length > 0) setConfirm("discard");
    else onClose();
  };

  return (
    <>
      <SidePanel
        title={<span className="ah-mono">{label}</span>}
        closeLabel={`Close ${label}`}
        openerRef={openerRef}
        onClose={close}
        initialFocus={
          focusEnvironment ? `#${CSS.escape(`${id}-addresses-at-${focusEnvironment}`)}` : undefined
        }
        footer={
          <>
            <Button
              variant="ghost"
              icon="x"
              disabled={pending}
              onClick={() => {
                setFailure(null);
                setConfirm("remove");
              }}
            >
              Remove service
            </Button>
            <span className="ah-grow" />
            {ops.length > 0 && (
              <span className="ah-small ah-muted" aria-live="polite">
                {count(ops.length, "change")}
              </span>
            )}
            <Button variant="ghost" disabled={pending} onClick={close}>
              Cancel
            </Button>
            <Button variant="primary" disabled={pending || ops.length === 0} onClick={save}>
              {pending ? "Saving…" : "Save changes"}
            </Button>
          </>
        }
      >
        <div className="ah-stack" style={{ gap: 16 }}>
          <div className="ah-env-grid">
            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={`${id}-kind`} className="ah-config-field-label">
                Kind
              </label>
              <select
                id={`${id}-kind`}
                className="ah-input"
                value={kind}
                onChange={(event) => {
                  setKind(event.target.value);
                }}
              >
                <option value="">Not set</option>
                {SERVICE_KINDS.filter((candidate) => candidate.id !== "other").map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.label}
                  </option>
                ))}
                {kind !== "" && !serviceKind(kind) && <option value={kind}>{kind}</option>}
              </select>
            </div>
            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={`${id}-description`} className="ah-config-field-label">
                Description <span className="ah-muted">(optional)</span>
              </label>
              <input
                id={`${id}-description`}
                className="ah-input"
                value={description}
                maxLength={80}
                onChange={(event) => {
                  setDescription(event.target.value);
                }}
              />
            </div>
          </div>
          <div className="ah-stack" style={{ gap: 8 }}>
            <span className="ah-config-field-label">Addresses</span>
            <AddressList
              idPrefix={`${id}-addresses`}
              environments={environments}
              kind={serviceKind(kind)}
              values={values}
              removed={removed}
              onChange={(environment, value) => {
                setValues({ ...values, [environment]: value });
              }}
              rowNote={(environment) => {
                if (removed.has(environment.name))
                  return <span className="ah-config-error">Removed on save</span>;
                const existing = record.endpoints.find(
                  (item) => item.environment === environment.name,
                );
                return existing?.source === LOCAL_FILE ? (
                  <span>
                    <Icon name="laptop" /> Yours, in hub.local.json
                  </span>
                ) : null;
              }}
              rowEnd={(environment) => {
                const has = original[environment.name] !== undefined;
                if (!has) return <span />;
                return removed.has(environment.name) ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon="undo-2"
                    aria-label={`Keep the ${environment.name} address`}
                    onClick={() => {
                      const next = new Set(removed);
                      next.delete(environment.name);
                      setRemoved(next);
                    }}
                  >
                    Undo
                  </Button>
                ) : (
                  <IconButton
                    icon="x"
                    size="sm"
                    variant="ghost"
                    label={`Remove the ${environment.name} address`}
                    onClick={() => {
                      setRemoved(new Set([...removed, environment.name]));
                    }}
                  />
                );
              }}
            />
            <p className="ah-small ah-muted" style={{ margin: 0 }}>
              <Icon name="lock" /> Never a password: a URL takes no user or token.
            </p>
          </div>
          {failure && (
            <p role="alert" className="ah-config-error">
              {failure}
            </p>
          )}
        </div>
      </SidePanel>

      {confirm === "discard" && (
        <ConfirmDialog
          title={`Discard ${count(ops.length, "change")}?`}
          confirmLabel="Discard changes"
          cancelLabel="Keep editing"
          consequences={["Your changes to this service are not saved."]}
          onCancel={() => {
            setConfirm(null);
          }}
          onConfirm={() => {
            setConfirm(null);
            onClose();
          }}
        />
      )}
      {confirm === "remove" && (
        <ConfirmDialog
          title={`Remove ${label}?`}
          confirmLabel={pending ? "Removing…" : "Remove service"}
          pending={pending}
          consequences={[
            record.endpoints.length > 0
              ? `Its ${count(record.endpoints.length, "address")} go too. Agents stop seeing where it runs.`
              : "Agents stop seeing it.",
            ...(declaredByTeam ? ["hub.json changes; run ./hub sync and open a hub PR."] : []),
          ]}
          onCancel={() => {
            setConfirm(null);
          }}
          onConfirm={removeService}
        >
          {failure && (
            <p role="alert" className="ah-config-error">
              {failure}
            </p>
          )}
        </ConfirmDialog>
      )}
    </>
  );
}
