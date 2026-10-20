import { useEffect, useId, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { Banner, Button, Icon, OptionRow, ProblemError, Skeleton } from "../../components";
import { useApi } from "../../lib/api";
import { EnvFileVariables } from "./EnvFileVariables";
import { SetupFlow } from "./SetupFlow";
import {
  ACCESSES,
  ACCESS_LOOK,
  ENVIRONMENT_PRESETS,
  NAME_PATTERN,
  flowOrigin,
  lineWithValue,
  linesOf,
  postEnvironmentEdit,
  refusalOf,
} from "./environments";
import type { Access, HubConfigView, SavedState } from "./environments";
import "./hub-config.css";

type Scope = "local" | "team";
type SecretsFrom = "file" | "shell" | "none";

const STEPS = ["Kind", "Name", "Access", "Who it is for", "Secrets", "Review"] as const;
const DESCRIPTION_MAX = 80;

/** `/projects/:project/environments/new`: add an environment, one question at a time. */
export function AddEnvironmentScreen() {
  const { project = "" } = useParams();
  const config = useApi("/api/v1/projects/{project}/config", { path: { project } });
  useEffect(() => {
    document.title = `Add environment · ${project}`;
  }, [project]);
  if (config.isError)
    return (
      <div className="ah-page">
        <ProblemError
          title="Could not read this project's configuration"
          detail={config.error.detail}
          status={config.error.status}
          onRetry={() => void config.refetch()}
        />
      </div>
    );
  if (!config.data)
    return (
      <div className="ah-page" aria-busy="true">
        <Skeleton height={320} />
      </div>
    );
  return <AddEnvironmentFlow view={config.data} />;
}

function AddEnvironmentFlow({ view }: { view: HubConfigView }) {
  const id = useId();
  const navigate = useNavigate();
  const client = useQueryClient();
  const project = view.project;
  const origin = flowOrigin(useLocation().state, project);
  const localBroken = view.local_file.problems.length > 0;

  const [index, setIndex] = useState(0);
  const [presetId, setPresetId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [description, setDescription] = useState("");
  const [access, setAccess] = useState<Access>("read");
  const [production, setProduction] = useState(false);
  const [scope, setScope] = useState<Scope>("team");
  const [awsProfile, setAwsProfile] = useState("");
  const [variables, setVariables] = useState("");
  const [envFile, setEnvFile] = useState("");
  const [secretsFrom, setSecretsFrom] = useState<SecretsFrom>("none");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const preset = ENVIRONMENT_PRESETS.find((candidate) => candidate.id === presetId);
  const shownName = name.trim() || "this environment";
  const taken = view.environments.environments.find(
    (environment) => environment.name.toLowerCase() === name.trim().toLowerCase(),
  );
  const nameProblem =
    name.trim() === ""
      ? "Give it a name."
      : taken
        ? `${taken.name} already exists. Pick another name.`
        : NAME_PATTERN.test(name.trim())
          ? null
          : "Letters, digits, - and _ only, starting with a letter or digit; up to 40.";
  const valueLine = lineWithValue(variables);
  // Only the chosen place counts: a path typed, then a switch to the shell, is not sent.
  const sentFile = secretsFrom === "file" ? envFile.trim() : "";
  const sentVariables = secretsFrom === "shell" ? linesOf(variables) : [];
  const secretsSummary =
    sentFile !== ""
      ? `Env file ${sentFile}`
      : sentVariables.length > 0
        ? `Shell: ${sentVariables.join(", ")}`
        : "Not yet";
  const fieldId = (key: string) => `${id}-${key}`;

  const pickPreset = (next: string) => {
    const chosen = ENVIRONMENT_PRESETS.find((candidate) => candidate.id === next);
    if (!chosen) return;
    setPresetId(next);
    if (!nameTouched) setName(chosen.name);
    if (!description || ENVIRONMENT_PRESETS.some((other) => other.description === description))
      setDescription(chosen.description);
    setAccess(chosen.access);
    setProduction(chosen.production);
    setScope(localBroken ? "team" : chosen.scope);
  };

  const save = () => {
    setPending(true);
    setFailure(null);
    postEnvironmentEdit(client, project, {
      op: "add_environment",
      scope,
      name: name.trim(),
      access,
      production,
      description: description.trim() || null,
      aws_profile: awsProfile.trim() || null,
      credential_env: sentVariables,
      env_file: sentFile || null,
    })
      .then(() => {
        const state: SavedState = {
          saved: `Added ${name.trim()} ${scope === "team" ? "for the team" : "for you"}`,
          team: scope === "team",
        };
        void navigate(origin.returnTo, { state });
      })
      .catch((error: unknown) => {
        setPending(false);
        setFailure(
          `Could not save: ${refusalOf(error).summary.replace(/^Nothing was saved: /, "")} Your answers are kept; try again.`,
        );
      });
  };

  const steps = [
    { title: STEPS[0], summary: preset?.label },
    { title: STEPS[1], summary: name.trim() },
    {
      title: STEPS[2],
      summary: `${ACCESS_LOOK[access].card}${production ? " · Production" : ""}`,
    },
    { title: STEPS[3], summary: scope === "team" ? "The whole team" : "Only me" },
    {
      title: STEPS[4],
      summary: `${secretsSummary}${awsProfile.trim() ? ` · AWS profile ${awsProfile.trim()}` : ""}`,
    },
    { title: STEPS[5] },
  ];

  const preview = (
    <div className="ah-stack" style={{ gap: 8 }}>
      <div className="ah-setup-preview-line">
        <code className="ah-mono">{name.trim() || "name"}</code>{" "}
        <span className="ah-muted">
          ({access}
          {production ? ", production" : ""})
        </span>
        {description.trim() ? `: ${description.trim()}` : ""}
      </div>
      <p className="ah-small" style={{ margin: 0 }}>
        <Icon name={ACCESS_LOOK[access].icon} /> {ACCESS_LOOK[access].help}
        {production ? " Actions never write or delete here." : ""}
      </p>
    </div>
  );

  let question = "";
  let help = "";
  let body = null;
  let canContinue = true;
  let blocked: string | undefined;
  let nextLabel = "Continue";

  switch (index) {
    case 0:
      question = "What kind of environment is it?";
      help = "Pick the closest one. It fills in sensible answers you can change later.";
      canContinue = preset !== undefined;
      blocked = "Pick one to go on.";
      body = (
        <fieldset className="ah-env-fieldset">
          <legend className="ah-sr">{question}</legend>
          <div className="ah-options">
            {ENVIRONMENT_PRESETS.map((candidate) => (
              <OptionRow
                key={candidate.id}
                type="radio"
                name={fieldId("preset")}
                icon={candidate.icon}
                label={candidate.label}
                description={candidate.hint}
                checked={presetId === candidate.id}
                onToggle={() => {
                  pickPreset(candidate.id);
                }}
              />
            ))}
          </div>
        </fieldset>
      );
      break;
    case 1:
      question = "What do you call it?";
      help =
        "Use the name your team already says, like local, staging or production. Agents and people refer to it by this name.";
      canContinue = nameProblem === null;
      body = (
        <div className="ah-stack" style={{ gap: 16 }}>
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId("name")} className="ah-config-field-label">
              Name
            </label>
            <input
              id={fieldId("name")}
              className="ah-input ah-mono ah-setup-input ah-setup-input-short"
              value={name}
              autoComplete="off"
              spellCheck={false}
              maxLength={40}
              aria-invalid={name.trim() !== "" && nameProblem ? true : undefined}
              aria-describedby={`${fieldId("name")}-help`}
              onChange={(event) => {
                setNameTouched(true);
                setName(event.target.value);
              }}
            />
            <span
              id={`${fieldId("name")}-help`}
              className={
                name.trim() !== "" && nameProblem ? "ah-small ah-config-error" : "ah-small ah-muted"
              }
            >
              {name.trim() !== "" && nameProblem
                ? nameProblem
                : "Letters, digits, - and _, up to 40."}
            </span>
          </div>
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId("description")} className="ah-config-field-label">
              Short description <span className="ah-muted">(optional)</span>
            </label>
            <input
              id={fieldId("description")}
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
        </div>
      );
      break;
    case 2:
      question = `What may agents do in ${shownName}?`;
      help =
        "Scripted actions follow this strictly. Free commands like aws or psql follow it as an instruction.";
      body = (
        <div className="ah-stack" style={{ gap: 16 }}>
          <fieldset className="ah-env-fieldset">
            <legend className="ah-sr">{question}</legend>
            <div className="ah-options">
              {ACCESSES.map((candidate) => (
                <OptionRow
                  key={candidate}
                  type="radio"
                  name={fieldId("access")}
                  icon={ACCESS_LOOK[candidate].icon}
                  label={ACCESS_LOOK[candidate].card}
                  recommended={production && candidate === "read"}
                  description={ACCESS_LOOK[candidate].help}
                  checked={access === candidate}
                  onToggle={() => {
                    setAccess(candidate);
                  }}
                />
              ))}
            </div>
          </fieldset>
          <div className="ah-options">
            <OptionRow
              type="checkbox"
              name={fieldId("production")}
              icon="shield-x"
              label="This is production"
              description="Real customers and real data. Agents never write or delete here, whatever you pick above."
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
        </div>
      );
      break;
    case 3:
      question = "Who is it for?";
      help = "Decide whether the whole team uses it, or only you.";
      body = (
        <fieldset className="ah-env-fieldset">
          <legend className="ah-sr">{question}</legend>
          <div className="ah-options">
            <OptionRow
              type="radio"
              name={fieldId("scope")}
              icon="users"
              label="The whole team"
              description="Saved in hub.json. Every developer's agents see it once you open a hub PR."
              checked={scope === "team"}
              onToggle={() => {
                setScope("team");
              }}
            />
            <OptionRow
              type="radio"
              name={fieldId("scope")}
              icon="laptop"
              label="Only me"
              disabled={localBroken}
              description={
                localBroken
                  ? "Your hub.local.json has a problem; fix it first."
                  : "Saved in hub.local.json on this machine. Never committed."
              }
              checked={scope === "local"}
              onToggle={() => {
                setScope("local");
              }}
            />
          </div>
        </fieldset>
      );
      break;
    case 4: {
      question = "Where do the secrets for scripted actions live?";
      help = `Scripted actions need passwords and keys to reach ${shownName}. Tell agent-hub where they are, by name only. Not sure? Pick Not yet.`;
      const fileMissing = secretsFrom === "file" && envFile.trim() === "";
      const shellMissing = secretsFrom === "shell" && linesOf(variables).length === 0;
      canContinue =
        !fileMissing && !shellMissing && (secretsFrom !== "shell" || valueLine === null);
      blocked = fileMissing
        ? "Give the file's path, or pick Not yet."
        : shellMissing
          ? "Give at least one variable name, or pick Not yet."
          : "Remove the value after = first.";
      nextLabel = secretsFrom === "none" && awsProfile.trim() === "" ? "Skip" : "Continue";
      body = (
        <div className="ah-stack" style={{ gap: 20 }}>
          <fieldset className="ah-env-fieldset">
            <legend className="ah-sr">{question}</legend>
            <div className="ah-options">
              <OptionRow
                type="radio"
                name={fieldId("secrets")}
                icon="file-text"
                label="In an env file"
                recommended
                description="A .env file in a repo, ignored by git. Actions get its variables."
                checked={secretsFrom === "file"}
                onToggle={() => {
                  setSecretsFrom("file");
                }}
              >
                {secretsFrom === "file" && (
                  <span className="ah-stack ah-setup-inline" style={{ gap: 6 }}>
                    <label htmlFor={fieldId("file")} className="ah-config-field-label">
                      Env file path
                    </label>
                    <input
                      id={fieldId("file")}
                      className="ah-input ah-mono ah-setup-input"
                      value={envFile}
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={`${view.repos[0]?.dir ?? "my-repo"}/.env.${name.trim() || "staging"}`}
                      onChange={(event) => {
                        setEnvFile(event.target.value);
                      }}
                    />
                    <span className="ah-small ah-muted">
                      Relative to the folder that holds the hub and its repos. Only scripted actions
                      read it; agents never do.
                    </span>
                    <EnvFileVariables project={project} path={envFile} />
                  </span>
                )}
              </OptionRow>
              <OptionRow
                type="radio"
                name={fieldId("secrets")}
                icon="square-terminal"
                label="In my shell"
                description="Variables you export in your terminal, like in ~/.zshrc."
                checked={secretsFrom === "shell"}
                onToggle={() => {
                  setSecretsFrom("shell");
                }}
              >
                {secretsFrom === "shell" && (
                  <span className="ah-stack ah-setup-inline" style={{ gap: 4 }}>
                    <label htmlFor={fieldId("variables")} className="ah-config-field-label">
                      Variable names
                    </label>
                    <textarea
                      id={fieldId("variables")}
                      className="ah-input ah-mono ah-config-textarea ah-setup-input"
                      rows={3}
                      value={variables}
                      spellCheck={false}
                      autoComplete="off"
                      placeholder="DATABASE_URL"
                      aria-invalid={valueLine !== null ? true : undefined}
                      onChange={(event) => {
                        setVariables(event.target.value);
                      }}
                    />
                    <span
                      aria-live="polite"
                      className={
                        valueLine !== null ? "ah-small ah-config-error" : "ah-small ah-muted"
                      }
                    >
                      {valueLine !== null
                        ? `Line ${String(valueLine)}: only the name. Remove = and what follows.`
                        : "Names only, never a value. One per line."}
                    </span>
                  </span>
                )}
              </OptionRow>
              <OptionRow
                type="radio"
                name={fieldId("secrets")}
                icon="circle-dashed"
                label="Not yet"
                description="Actions get no secrets here for now. You can add them later."
                checked={secretsFrom === "none"}
                onToggle={() => {
                  setSecretsFrom("none");
                }}
              />
            </div>
          </fieldset>
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId("aws")} className="ah-config-field-label">
              AWS profile <span className="ah-muted">(optional)</span>
            </label>
            <input
              id={fieldId("aws")}
              className="ah-input ah-mono ah-setup-input ah-setup-input-short"
              value={awsProfile}
              autoComplete="off"
              spellCheck={false}
              placeholder={`${project}-${name.trim() || "staging"}`}
              onChange={(event) => {
                setAwsProfile(event.target.value);
              }}
            />
            <span className="ah-small ah-muted">
              If it runs on AWS: the profile name in ~/.aws/config, never its keys.
            </span>
          </div>
        </div>
      );
      break;
    }
    default:
      question = `Add ${shownName}?`;
      help = "Check your answers. Change any of them before you add it.";
      body = (
        <div className="ah-stack" style={{ gap: 16 }}>
          <dl className="ah-setup-review">
            {steps.slice(0, -1).map((step, position) => (
              <div key={step.title} className="ah-setup-review-row">
                <dt>{step.title}</dt>
                <dd>{step.summary}</dd>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Change ${step.title.toLowerCase()}`}
                  onClick={() => {
                    setIndex(position);
                  }}
                >
                  Change
                </Button>
              </div>
            ))}
          </dl>
          <div className="ah-setup-next">
            <strong className="ah-small">What happens next</strong>
            <ol className="ah-small">
              {scope === "team" ? (
                <>
                  <li>
                    agent-hub writes it to <code className="ah-mono">hub.json</code>. Nothing is
                    committed yet.
                  </li>
                  <li>
                    Run <code className="ah-mono">./hub sync</code> so AGENTS.md lists it.
                  </li>
                  <li>Review the diff and open a hub PR.</li>
                </>
              ) : (
                <li>
                  agent-hub writes it to <code className="ah-mono">hub.local.json</code> on this
                  machine. Your agents see it from their next session.
                </li>
              )}
            </ol>
          </div>
        </div>
      );
  }

  return (
    <SetupFlow
      project={project}
      origin={origin}
      title="Add environment"
      intro="Tell agents about a place where your systems run, and what they may do there."
      noun="environment"
      steps={steps}
      index={index}
      onIndex={setIndex}
      question={question}
      help={help}
      canContinue={canContinue}
      blocked={blocked}
      nextLabel={nextLabel}
      onFinish={save}
      finishLabel={`Add environment ${scope === "team" ? "for the team" : "for me"}`}
      pending={pending}
      failure={failure}
      previewWhere={scope === "team" ? "In AGENTS.md" : "In your session brief"}
      preview={preview}
    >
      {body}
    </SetupFlow>
  );
}
