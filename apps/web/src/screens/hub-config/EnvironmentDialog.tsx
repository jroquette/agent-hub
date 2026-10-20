import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Banner, Button, Dialog, OptionRow } from "../../components";
import {
  ACCESSES,
  ACCESS_LOOK,
  STRICTNESS,
  isTeams,
  postEnvironmentEdit,
  refusalOf,
} from "./environments";
import type {
  Access,
  EnvironmentEdit,
  HubConfigView,
  Refusal,
  SourcedEnvironment,
} from "./environments";

type Scope = "local" | "team";
const DESCRIPTION_MAX = 80;

/**
 * Change an environment (adding one is the Add environment flow). The developer's own changes in
 * hub.local.json; a team environment changes for the team (hub.json, left uncommitted), or, for
 * me only, its access may get stricter. The name and credential names change through Ask Claude.
 */
export function EnvironmentDialog({
  view,
  editing,
  onClose,
  onSaved,
}: {
  view: HubConfigView;
  editing: SourcedEnvironment;
  onClose: () => void;
  /** Called with the toast's words and whether hub.json changed. */
  onSaved: (message: string, team: boolean) => void;
}) {
  const id = useId();
  const client = useQueryClient();
  const teams = isTeams(editing);
  const teamAccess = editing.team_access ?? null;
  const [scope, setScope] = useState<Scope>(teams ? "team" : "local");
  const [access, setAccess] = useState<Access>(teams && teamAccess ? teamAccess : editing.access);
  const [production, setProduction] = useState(editing.production);
  const [description, setDescription] = useState(editing.description ?? "");
  const [envFile, setEnvFile] = useState(editing.credentials?.env_file ?? "");
  const [pending, setPending] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  const localBroken = view.local_file.problems.length > 0;
  // "Only me" on a team environment: only a stricter access, every other field is the team's.
  const tightening = teams && scope === "local";
  const fieldId = (key: string) => `${id}-${key}`;
  const looser = (candidate: Access) =>
    tightening && teamAccess !== null && STRICTNESS[candidate] < STRICTNESS[teamAccess];
  const shownError = (key: string) => refusal?.fields[key];
  const credentialNames = [
    editing.credentials?.aws_profile && `AWS profile ${editing.credentials.aws_profile}`,
    ...(editing.credentials?.env ?? []),
  ].filter(Boolean);

  const body = (): EnvironmentEdit | null => {
    if (tightening) {
      // Back to the team's access: the local tightening goes away.
      if (access === teamAccess)
        return editing.access === teamAccess
          ? null
          : { op: "remove_environment", scope: "local", name: editing.name };
      return { op: "set_environment", scope: "local", name: editing.name, access };
    }
    return {
      op: "set_environment",
      scope,
      name: editing.name,
      access,
      production,
      description: description.trim(),
      env_file: envFile.trim(),
    };
  };

  const save = () => {
    const edit = body();
    if (edit === null) {
      onClose();
      return;
    }
    setPending(true);
    setRefusal(null);
    postEnvironmentEdit(client, view.project, edit)
      .then(() => {
        onClose();
        onSaved(`Saved ${editing.name}`, scope === "team");
      })
      .catch((error: unknown) => {
        setPending(false);
        setRefusal(refusalOf(error));
      });
  };

  return (
    <Dialog
      title={`Edit environment ${editing.name}`}
      size="md"
      onClose={onClose}
      pending={pending}
      initialFocus={`input[name="${CSS.escape(fieldId("access"))}"]:checked`}
      footer={
        <>
          <Button disabled={pending} onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={pending} onClick={save}>
            {pending ? "Saving…" : `Save ${scope === "team" ? "for the team" : "for me"}`}
          </Button>
        </>
      }
    >
      <form
        className="ah-stack ah-config-form"
        style={{ gap: 16 }}
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        {refusal && (
          <p role="alert" className="ah-config-error">
            {refusal.summary}
          </p>
        )}

        {teams ? (
          <fieldset className="ah-env-fieldset">
            <legend className="ah-config-field-label">Change it for</legend>
            <div className="ah-options">
              <OptionRow
                type="radio"
                name={fieldId("scope")}
                label="The whole team"
                description="Saved in hub.json. You review the change, run ./hub sync and open a hub PR."
                checked={scope === "team"}
                onToggle={() => {
                  setScope("team");
                  if (teamAccess) setAccess(teamAccess);
                }}
              />
              <OptionRow
                type="radio"
                name={fieldId("scope")}
                label="Only me"
                disabled={localBroken}
                description={
                  localBroken
                    ? "Not available: your hub.local.json has a problem (see the notice above)."
                    : "Saved in hub.local.json on this machine. You can only make the team's access stricter for your agents."
                }
                checked={scope === "local"}
                onToggle={() => {
                  setScope("local");
                  setAccess(editing.access);
                }}
              />
            </div>
          </fieldset>
        ) : (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            Saved in hub.local.json: {editing.name} is yours. To share it with the team, ask Claude
            to move it to hub.json.
          </p>
        )}

        <fieldset className="ah-env-fieldset">
          <legend className="ah-config-field-label">What may agents do there?</legend>
          <div className="ah-options">
            {ACCESSES.map((candidate) => (
              <OptionRow
                key={candidate}
                type="radio"
                name={fieldId("access")}
                label={ACCESS_LOOK[candidate].card}
                recommended={production && candidate === "read"}
                disabled={looser(candidate)}
                description={
                  looser(candidate)
                    ? `Looser than the team's (${ACCESS_LOOK[teamAccess ?? "write"].short}): you can only tighten.`
                    : tightening && candidate === teamAccess
                      ? `${ACCESS_LOOK[candidate].help} The team's access.`
                      : ACCESS_LOOK[candidate].help
                }
                checked={access === candidate}
                onToggle={() => {
                  setAccess(candidate);
                }}
              />
            ))}
          </div>
          <span className={shownError("access") ? "ah-small ah-config-error" : "ah-small ah-muted"}>
            {shownError("access") ??
              "Scripted actions follow this strictly. Free commands follow it as an instruction."}
          </span>
        </fieldset>

        {tightening ? (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            Everything else stays as the team set it in hub.json.
          </p>
        ) : (
          <>
            <div className="ah-options">
              <OptionRow
                type="checkbox"
                name={fieldId("production")}
                label="This is production"
                description="Real customers and real data. Actions never write or delete here, whatever the access."
                checked={production}
                onToggle={() => {
                  setProduction(!production);
                }}
              />
            </div>
            {production && access !== "read" && (
              <Banner tone="warning" boxed>
                Production where agents can {access === "ask" ? "ask to change" : "change"} data:
                doctor will warn. Read only is recommended.
              </Banner>
            )}

            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={fieldId("description")} className="ah-config-field-label">
                Short description <span className="ah-muted">(optional)</span>
              </label>
              <input
                id={fieldId("description")}
                className="ah-input"
                value={description}
                maxLength={DESCRIPTION_MAX}
                aria-invalid={shownError("description") ? true : undefined}
                aria-describedby={`${fieldId("description")}-help`}
                onChange={(event) => {
                  setDescription(event.target.value);
                }}
              />
              <span
                id={`${fieldId("description")}-help`}
                className={
                  shownError("description") ? "ah-small ah-config-error" : "ah-small ah-muted"
                }
              >
                {shownError("description") ??
                  `Helps agents tell environments apart. ${String(description.length)} / ${String(DESCRIPTION_MAX)}`}
              </span>
            </div>

            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={fieldId("env_file")} className="ah-config-field-label">
                Env file path <span className="ah-muted">(optional)</span>
              </label>
              <input
                id={fieldId("env_file")}
                className="ah-input ah-mono"
                value={envFile}
                autoComplete="off"
                spellCheck={false}
                aria-invalid={shownError("env_file") ? true : undefined}
                onChange={(event) => {
                  setEnvFile(event.target.value);
                }}
              />
              <span
                className={
                  shownError("env_file") ? "ah-small ah-config-error" : "ah-small ah-muted"
                }
              >
                {shownError("env_file") ??
                  "Relative to the workspace. Only scripted actions read it; agents never do."}
              </span>
            </div>
            <p className="ah-small ah-muted" style={{ margin: 0 }}>
              {credentialNames.length > 0
                ? `Credential names: ${credentialNames.join(", ")}. `
                : ""}
              To rename it or change its AWS profile or variable names, ask Claude.
            </p>
          </>
        )}
      </form>
    </Dialog>
  );
}
