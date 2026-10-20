import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Banner, Button, Dialog, OptionRow } from "../../components";
import {
  ACCESSES,
  ACCESS_LOOK,
  NAME_PATTERN,
  STRICTNESS,
  isMine,
  isTeams,
  lineWithValue,
  linesOf,
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
 * Add an environment, or change one: who it is for (only me: hub.local.json; the team: hub.json,
 * left uncommitted), what agents may do there, whether it is production, and its credentials by
 * name only. On a team environment "Only me" may only tighten its access.
 */
export function EnvironmentDialog({
  view,
  editing,
  onClose,
  onSaved,
}: {
  view: HubConfigView;
  /** The environment to change; null adds one. */
  editing: SourcedEnvironment | null;
  onClose: () => void;
  /** Called with the toast's words and whether hub.json changed. */
  onSaved: (message: string, team: boolean) => void;
}) {
  const id = useId();
  const client = useQueryClient();
  const teams = editing !== null && isTeams(editing);
  const teamAccess = editing?.team_access ?? null;
  const [scope, setScope] = useState<Scope>(editing === null ? "local" : teams ? "team" : "local");
  const [name, setName] = useState(editing?.name ?? "");
  const [access, setAccess] = useState<Access>(
    editing === null ? "read" : scope === "team" && teamAccess ? teamAccess : editing.access,
  );
  const [production, setProduction] = useState(editing?.production ?? false);
  const [description, setDescription] = useState(editing?.description ?? "");
  const [awsProfile, setAwsProfile] = useState(editing?.credentials?.aws_profile ?? "");
  const [variables, setVariables] = useState((editing?.credentials?.env ?? []).join("\n"));
  const [envFile, setEnvFile] = useState(editing?.credentials?.env_file ?? "");
  const [pending, setPending] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  const localBroken = view.local_file.problems.length > 0;
  // "Only me" on a team environment: only a stricter access, every other field is the team's.
  const tightening = teams && scope === "local";
  const fieldId = (key: string) => `${id}-${key}`;
  const nameTaken =
    editing === null &&
    name.trim() !== "" &&
    view.environments.environments.find(
      (environment) => environment.name.toLowerCase() === name.trim().toLowerCase(),
    );
  const nameProblem =
    editing !== null || name.trim() === ""
      ? null
      : nameTaken
        ? `${nameTaken.name} is already used by ${isMine(nameTaken) && !isTeams(nameTaken) ? "you" : "the team"}.`
        : NAME_PATTERN.test(name.trim())
          ? null
          : "Letters, digits, - and _ only, starting with a letter or digit; up to 40.";
  const valueLine = lineWithValue(variables);
  const looser = (candidate: Access) =>
    tightening && teamAccess !== null && STRICTNESS[candidate] < STRICTNESS[teamAccess];
  const shownError = (key: string) => refusal?.fields[key];

  const body = (): EnvironmentEdit | null => {
    if (editing === null)
      return {
        op: "add_environment",
        scope,
        name: name.trim(),
        access,
        production,
        description: description.trim() || null,
        aws_profile: awsProfile.trim() || null,
        credential_env: linesOf(variables),
        env_file: envFile.trim() || null,
      };
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
    if (nameProblem || valueLine !== null || (editing === null && name.trim() === "")) {
      setRefusal({
        summary: "Nothing was saved: fix the fields marked below.",
        fields: name.trim() === "" ? { name: "Give the environment a name." } : {},
      });
      return;
    }
    const edit = body();
    if (edit === null) {
      onClose();
      return;
    }
    setPending(true);
    setRefusal(null);
    postEnvironmentEdit(client, view.project, edit)
      .then(() => {
        const shown = editing?.name ?? name.trim();
        const who = scope === "team" ? "for the team" : "for you";
        onClose();
        onSaved(editing === null ? `Added ${shown} ${who}` : `Saved ${shown}`, scope === "team");
      })
      .catch((error: unknown) => {
        setPending(false);
        setRefusal(refusalOf(error));
      });
  };

  const verb = editing === null ? "Add environment" : "Save";
  const saveLabel = `${verb} ${scope === "team" ? "for the team" : "for me"}`;

  return (
    <Dialog
      title={editing === null ? "Add environment" : `Edit environment ${editing.name}`}
      size="md"
      onClose={onClose}
      pending={pending}
      initialFocus={
        editing === null
          ? `#${CSS.escape(fieldId("name"))}`
          : `input[name="${CSS.escape(fieldId("access"))}"]:checked`
      }
      footer={
        <>
          <Button disabled={pending} onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={pending} onClick={save}>
            {pending ? "Saving…" : saveLabel}
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

        {editing !== null && !teams ? (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            Saved in hub.local.json: {editing.name} is yours. To share it with the team, ask Claude
            to move it to hub.json.
          </p>
        ) : (
          <fieldset className="ah-env-fieldset">
            <legend className="ah-config-field-label">Who is this for</legend>
            <div className="ah-options">
              <OptionRow
                type="radio"
                name={fieldId("scope")}
                label="Only me"
                disabled={localBroken}
                description={
                  localBroken
                    ? "Not available: your hub.local.json has a problem (see the notice above)."
                    : teams
                      ? "Saved in hub.local.json on this machine. You can only make the team's access stricter for your agents."
                      : "Saved in hub.local.json on this machine. Your agents get it in their brief. Nothing to commit."
                }
                checked={scope === "local"}
                onToggle={() => {
                  setScope("local");
                  if (teams) setAccess(editing.access);
                }}
              />
              <OptionRow
                type="radio"
                name={fieldId("scope")}
                label="The whole team"
                disabled={editing !== null && !teams}
                description={
                  editing !== null && !teams
                    ? "This environment is yours. To share it, ask Claude to move it to hub.json."
                    : "Saved in hub.json. You review the change, run ./hub sync and open a hub PR."
                }
                checked={scope === "team"}
                onToggle={() => {
                  setScope("team");
                  if (teams && teamAccess) setAccess(teamAccess);
                }}
              />
            </div>
          </fieldset>
        )}

        <div className="ah-stack" style={{ gap: 4 }}>
          <label htmlFor={fieldId("name")} className="ah-config-field-label">
            Name
          </label>
          <input
            id={fieldId("name")}
            className="ah-input ah-mono"
            value={name}
            readOnly={editing !== null}
            autoComplete="off"
            spellCheck={false}
            maxLength={40}
            placeholder="staging"
            aria-invalid={nameProblem || shownError("name") ? true : undefined}
            aria-describedby={`${fieldId("name")}-help`}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
          <span
            id={`${fieldId("name")}-help`}
            className={
              nameProblem || shownError("name") ? "ah-small ah-config-error" : "ah-small ah-muted"
            }
          >
            {nameProblem ??
              shownError("name") ??
              (editing === null
                ? "Letters, digits, - and _, up to 40. Not used by another environment, in any case."
                : "Rename it with Ask Claude.")}
          </span>
        </div>

        <fieldset className="ah-env-fieldset">
          <legend className="ah-config-field-label">Access</legend>
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
              "Actions follow this strictly. Free commands follow it as an instruction, plus blocked words."}
          </span>
        </fieldset>

        {!tightening && (
          <>
            <div className="ah-options">
              <OptionRow
                type="checkbox"
                name={fieldId("production")}
                label="Production"
                description="Real customer data. Actions never write or delete here, whatever the access."
                checked={production}
                onToggle={() => {
                  setProduction(!production);
                }}
              />
            </div>
            {production && access !== "read" && (
              <Banner tone="warning" boxed>
                Production with {ACCESS_LOOK[access].card.toLowerCase()} access: doctor will warn.
                Read only is recommended.
              </Banner>
            )}

            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={fieldId("description")} className="ah-config-field-label">
                Description <span className="ah-muted">(optional)</span>
              </label>
              <input
                id={fieldId("description")}
                className="ah-input"
                value={description}
                maxLength={DESCRIPTION_MAX}
                placeholder="docker compose stack on this machine"
                aria-describedby={`${fieldId("description")}-help`}
                aria-invalid={shownError("description") ? true : undefined}
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
                  `What it is, so agents can tell environments apart. ${String(description.length)} / ${String(DESCRIPTION_MAX)}`}
              </span>
            </div>

            <fieldset
              className="ah-env-fieldset"
              aria-describedby={`${fieldId("credentials")}-help`}
            >
              <legend className="ah-config-field-label">Credentials</legend>
              <span id={`${fieldId("credentials")}-help`} className="ah-small ah-muted">
                Names only. Never paste a password, key or token: agent-hub refuses values that look
                like a secret.
              </span>
              <div className="ah-stack" style={{ gap: 4 }}>
                <label htmlFor={fieldId("aws_profile")} className="ah-small">
                  AWS profile name
                </label>
                <input
                  id={fieldId("aws_profile")}
                  className="ah-input ah-mono"
                  value={awsProfile}
                  readOnly={editing !== null}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="demo-staging"
                  aria-invalid={shownError("aws_profile") ? true : undefined}
                  onChange={(event) => {
                    setAwsProfile(event.target.value);
                  }}
                />
                {shownError("aws_profile") && (
                  <span className="ah-small ah-config-error">{shownError("aws_profile")}</span>
                )}
              </div>
              <div className="ah-stack" style={{ gap: 4 }}>
                <label htmlFor={fieldId("variables")} className="ah-small">
                  Variable names
                </label>
                <textarea
                  id={fieldId("variables")}
                  className="ah-input ah-mono ah-config-textarea"
                  rows={2}
                  value={variables}
                  readOnly={editing !== null}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder="DEMO_DB_URL"
                  aria-invalid={
                    valueLine !== null || shownError("credential_env") ? true : undefined
                  }
                  onChange={(event) => {
                    setVariables(event.target.value);
                  }}
                />
                <span
                  aria-live="polite"
                  className={
                    valueLine !== null || shownError("credential_env")
                      ? "ah-small ah-config-error"
                      : "ah-small ah-muted"
                  }
                >
                  {valueLine !== null
                    ? `Line ${String(valueLine)}: only the name. Remove = and what follows.`
                    : (shownError("credential_env") ??
                      "One per line: the variables that hold this environment's secrets.")}
                </span>
              </div>
              <div className="ah-stack" style={{ gap: 4 }}>
                <label htmlFor={fieldId("env_file")} className="ah-small">
                  Env file path
                </label>
                <input
                  id={fieldId("env_file")}
                  className="ah-input ah-mono"
                  value={envFile}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="demo-api/.env.staging"
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
                    "Relative to the workspace. Only actions read it; agents never do."}
                </span>
              </div>
              {editing !== null && (
                <span className="ah-small ah-muted">
                  To change the AWS profile or variable names, ask Claude.
                </span>
              )}
            </fieldset>
          </>
        )}
        {tightening && (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            Everything else stays as the team set it in hub.json.
          </p>
        )}
      </form>
    </Dialog>
  );
}
