import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button, Dialog, Icon, StatusBadge } from "../../components";
import { cx } from "../../lib/cx";
import {
  SERVICE_KINDS,
  exampleAddress,
  isTeams,
  postEnvironmentEdit,
  refusalOf,
  serviceKind,
  serviceLabel,
} from "./environments";
import type { HubConfigView, Refusal } from "./environments";

const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;

/**
 * Add a service in three questions a person can answer: what runs (an API, a portal, a
 * database…), which repo runs it, and where it is in each environment. One address per
 * environment, any left empty; each is saved in its environment's file.
 */
export function ServiceDialog({
  view,
  repo: givenRepo,
  onClose,
  onSaved,
}: {
  view: HubConfigView;
  /** The repo the person started from, when they did. */
  repo?: string | undefined;
  onClose: () => void;
  onSaved: (message: string, team: boolean) => void;
}) {
  const id = useId();
  const client = useQueryClient();
  const environments = view.environments.environments;
  const [kindId, setKindId] = useState<string | null>(null);
  const [repo, setRepo] = useState(givenRepo ?? view.repos[0]?.dir ?? "");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [addresses, setAddresses] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  const kind = serviceKind(kindId);
  const fieldId = (key: string) => `${id}-${key}`;
  const taken = view.environments.services.some(
    (service) => service.repo === repo && service.name === name.trim(),
  );
  const nameProblem =
    name.trim() === ""
      ? null
      : taken
        ? `${repo} already has a service named ${name.trim()}: add its addresses in the table.`
        : NAME_PATTERN.test(name.trim())
          ? null
          : "Letters, digits, - and _ only, up to 40.";
  const filled = environments.filter((environment) => (addresses[environment.name] ?? "").trim());

  const pickKind = (next: string) => {
    setKindId(next);
    if (!nameTouched) setName(serviceKind(next)?.name ?? "");
  };

  const save = () => {
    const missing: Record<string, string> = {};
    if (!kind) missing.kind = "Pick what runs.";
    if (name.trim() === "") missing.name = "Name the service.";
    if (filled.length === 0) missing.addresses = "Give its address in at least one environment.";
    if (Object.keys(missing).length > 0 || nameProblem) {
      setRefusal({ summary: "Nothing was saved: fix the fields marked below.", fields: missing });
      return;
    }
    setPending(true);
    setRefusal(null);
    postEnvironmentEdit(client, view.project, {
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
        onClose();
        onSaved(
          `Added ${serviceLabel(repo, name.trim())}`,
          filled.some((environment) => isTeams(environment)),
        );
      })
      .catch((error: unknown) => {
        setPending(false);
        setRefusal(refusalOf(error));
      });
  };

  const shownError = (key: string) => refusal?.fields[key];

  return (
    <Dialog
      title="Add service"
      size="md"
      onClose={onClose}
      pending={pending}
      footer={
        <>
          <Button disabled={pending} onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={pending} onClick={save}>
            {pending ? "Saving…" : "Add service"}
          </Button>
        </>
      }
    >
      <form
        className="ah-stack ah-config-form"
        style={{ gap: 18 }}
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          A service is something a repo runs: an API, a portal, a database. Tell agents where to
          find it in each environment.
        </p>
        {refusal && (
          <p role="alert" className="ah-config-error">
            {refusal.summary}
          </p>
        )}

        <fieldset className="ah-env-fieldset">
          <legend className="ah-config-field-label">1. What runs?</legend>
          <div className="ah-env-kinds">
            {SERVICE_KINDS.map((candidate) => (
              <label
                key={candidate.id}
                className={cx("ah-env-kind", kindId === candidate.id && "ah-env-kind-checked")}
              >
                <input
                  type="radio"
                  name={fieldId("kind")}
                  className="ah-env-kind-input"
                  checked={kindId === candidate.id}
                  onChange={() => {
                    pickKind(candidate.id);
                  }}
                />
                <Icon name={candidate.icon} />
                <span className="ah-stack" style={{ gap: 2 }}>
                  <span className="ah-env-kind-label">{candidate.label}</span>
                  <span className="ah-small ah-muted">{candidate.hint}</span>
                </span>
              </label>
            ))}
          </div>
          {shownError("kind") && (
            <span className="ah-small ah-config-error">{shownError("kind")}</span>
          )}
        </fieldset>

        <fieldset className="ah-env-fieldset">
          <legend className="ah-config-field-label">2. Which repo runs it, and its name</legend>
          <div className="ah-env-grid">
            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={fieldId("repo")} className="ah-small">
                Repo
              </label>
              <select
                id={fieldId("repo")}
                className="ah-input"
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
            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={fieldId("name")} className="ah-small">
                Service name
              </label>
              <input
                id={fieldId("name")}
                className="ah-input ah-mono"
                value={name}
                autoComplete="off"
                spellCheck={false}
                placeholder={kind && kind.name !== "" ? kind.name : "orders-api"}
                aria-invalid={nameProblem || shownError("name") ? true : undefined}
                aria-describedby={`${fieldId("name")}-help`}
                onChange={(event) => {
                  setNameTouched(true);
                  setName(event.target.value);
                }}
              />
            </div>
          </div>
          <span
            id={`${fieldId("name")}-help`}
            className={
              nameProblem || shownError("name") ? "ah-small ah-config-error" : "ah-small ah-muted"
            }
          >
            {nameProblem ??
              shownError("name") ??
              "How agents and people refer to it, e.g. api, admin-portal, orders-db."}
          </span>
        </fieldset>

        <fieldset className="ah-env-fieldset">
          <legend className="ah-config-field-label">3. Where is it in each environment?</legend>
          <span className="ah-small ah-muted">
            A URL like <code className="ah-mono">http://localhost:8000</code>, or a name like{" "}
            <code className="ah-mono">orders-table</code>. Leave an environment empty if it does not
            run there. Never a password: a URL takes no user or token.
          </span>
          <div className="ah-env-addresses">
            {environments.map((environment) => (
              <div key={environment.name} className="ah-env-address">
                <label htmlFor={fieldId(`at-${environment.name}`)} className="ah-env-name">
                  <code className="ah-mono">{environment.name}</code>
                  {environment.production && (
                    <StatusBadge status="guard" label="Production" quiet />
                  )}
                </label>
                <input
                  id={fieldId(`at-${environment.name}`)}
                  className="ah-input ah-mono"
                  value={addresses[environment.name] ?? ""}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={kind ? exampleAddress(kind, environment) : "address"}
                  onChange={(event) => {
                    setAddresses({ ...addresses, [environment.name]: event.target.value });
                  }}
                />
              </div>
            ))}
          </div>
          <span
            className={
              shownError("addresses") || shownError("url") || shownError("resource")
                ? "ah-small ah-config-error"
                : "ah-small ah-muted"
            }
          >
            {shownError("addresses") ??
              shownError("url") ??
              shownError("resource") ??
              (filled.length > 0
                ? `Agents will know where ${name.trim() || "it"} is in ${filled.map((environment) => environment.name).join(", ")}.`
                : "Fill at least one.")}
          </span>
        </fieldset>
      </form>
    </Dialog>
  );
}
