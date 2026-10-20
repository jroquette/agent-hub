import { useEffect, useId, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { Banner, Button, Icon, OptionRow, ProblemError, Skeleton } from "../../components";
import { useApi } from "../../lib/api";
import { EnvFileVariables } from "./EnvFileVariables";
import { ChoiceTile, SetupFlow } from "./SetupFlow";
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
  const [secretsFrom, setSecretsFrom] = useState<"file" | "shell" | "none">("none");
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
  const credentialNames = [
    sentFile && `env file ${sentFile}`,
    sentVariables.length > 0 && `shell variables ${sentVariables.join(", ")}`,
    awsProfile.trim() && `AWS profile ${awsProfile.trim()}`,
  ].filter(Boolean);
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
        setFailure(refusalOf(error).summary);
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
      summary: credentialNames.length > 0 ? credentialNames.join(", ") : "Skipped",
    },
    { title: STEPS[5] },
  ];

  const preview = (
    <div className="ah-stack" style={{ gap: 10 }}>
      <code className="ah-flow-preview-line">
        `{name.trim() || "name"}` ({access}
        {production ? ", PRODUCTION" : ""}){description.trim() ? `: ${description.trim()}` : ""}
      </code>
      <p className="ah-small" style={{ margin: 0 }}>
        <Icon name={ACCESS_LOOK[access].icon} /> {ACCESS_LOOK[access].help}
        {production ? " Actions never write or delete here." : ""}
      </p>
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        {scope === "team"
          ? "Every developer's agents get it, in AGENTS.md and their session brief."
          : "Only your agents get it, in their session brief."}
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
      help =
        "Pick the closest one. It fills in sensible answers that you can change on the next steps.";
      canContinue = preset !== undefined;
      blocked = "Pick one to go on.";
      body = (
        <div className="ah-flow-tiles">
          {ENVIRONMENT_PRESETS.map((candidate) => (
            <ChoiceTile
              key={candidate.id}
              name={fieldId("preset")}
              icon={candidate.icon}
              label={candidate.label}
              hint={candidate.hint}
              checked={presetId === candidate.id}
              onPick={() => {
                pickPreset(candidate.id);
              }}
            />
          ))}
        </div>
      );
      break;
    case 1:
      question = "What do you call it?";
      help =
        "Use the name your team already says, like local, staging or production. Agents and people will refer to it by this name.";
      canContinue = nameProblem === null;
      body = (
        <div className="ah-stack" style={{ gap: 16 }}>
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId("name")} className="ah-config-field-label">
              Name
            </label>
            <input
              id={fieldId("name")}
              className="ah-input ah-mono ah-flow-input"
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
              className="ah-input ah-flow-input"
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
      help = "Scripted actions follow this strictly. Free commands follow it as an instruction.";
      body = (
        <div className="ah-stack" style={{ gap: 16 }}>
          <div className="ah-options">
            {ACCESSES.map((candidate) => (
              <OptionRow
                key={candidate}
                type="radio"
                name={fieldId("access")}
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
        </div>
      );
      break;
    case 3:
      question = "Who is it for?";
      help = "Decide whether the whole team uses this environment, or only you.";
      body = (
        <div className="ah-flow-tiles ah-flow-tiles-2">
          <ChoiceTile
            name={fieldId("scope")}
            icon="users"
            label="The whole team"
            hint={
              <>
                Saved in <code className="ah-mono">hub.json</code>, shared with everyone. You review
                it, run <code className="ah-mono">./hub sync</code> and open a hub PR.
              </>
            }
            checked={scope === "team"}
            onPick={() => {
              setScope("team");
            }}
          />
          <ChoiceTile
            name={fieldId("scope")}
            icon="laptop"
            label="Only me"
            hint={
              localBroken ? (
                "Not available: your hub.local.json has a problem. Fix it on the Hub configuration page."
              ) : (
                <>
                  Saved in <code className="ah-mono">hub.local.json</code> on this machine. Never
                  committed; nothing to review.
                </>
              )
            }
            checked={scope === "local"}
            onPick={() => {
              if (!localBroken) setScope("local");
            }}
          />
        </div>
      );
      break;
    case 4: {
      question = "Where do the secrets for scripted actions live?";
      help =
        "Scripted actions need passwords and keys to reach this environment. Tell agent-hub where they are, by name only. Not sure? Pick Not yet: you can add it later.";
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
          <div className="ah-flow-tiles">
            <ChoiceTile
              name={fieldId("secrets")}
              icon="file-text"
              label="In an env file (recommended)"
              hint="A .env file in a repo, ignored by git. Actions get all its variables."
              checked={secretsFrom === "file"}
              onPick={() => {
                setSecretsFrom("file");
              }}
            />
            <ChoiceTile
              name={fieldId("secrets")}
              icon="square-terminal"
              label="In my shell"
              hint="Variables you export in your terminal, like in ~/.zshrc."
              checked={secretsFrom === "shell"}
              onPick={() => {
                setSecretsFrom("shell");
              }}
            />
            <ChoiceTile
              name={fieldId("secrets")}
              icon="circle-dashed"
              label="Not yet"
              hint="Actions get no secrets here for now."
              checked={secretsFrom === "none"}
              onPick={() => {
                setSecretsFrom("none");
              }}
            />
          </div>

          {secretsFrom === "file" && (
            <div className="ah-stack" style={{ gap: 6 }}>
              <label htmlFor={fieldId("file")} className="ah-config-field-label">
                Env file path
              </label>
              <input
                id={fieldId("file")}
                className="ah-input ah-mono ah-flow-input"
                value={envFile}
                autoComplete="off"
                spellCheck={false}
                placeholder={`${view.repos[0]?.dir ?? "my-repo"}/.env.${name.trim() || "staging"}`}
                onChange={(event) => {
                  setEnvFile(event.target.value);
                }}
              />
              <span className="ah-small ah-muted">
                Relative to the folder that holds the hub and its repos. Only scripted actions read
                it; agents never do.
              </span>
              <EnvFileVariables project={project} path={envFile} />
            </div>
          )}

          {secretsFrom === "shell" && (
            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={fieldId("variables")} className="ah-config-field-label">
                Variable names
              </label>
              <textarea
                id={fieldId("variables")}
                className="ah-input ah-mono ah-config-textarea ah-flow-input"
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
                className={valueLine !== null ? "ah-small ah-config-error" : "ah-small ah-muted"}
              >
                {valueLine !== null
                  ? `Line ${String(valueLine)}: only the name. Remove = and what follows.`
                  : "One per line, just the name. agent-hub keeps these out of agent sessions."}
              </span>
            </div>
          )}

          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId("aws")} className="ah-config-field-label">
              AWS profile <span className="ah-muted">(optional, if it runs on AWS)</span>
            </label>
            <input
              id={fieldId("aws")}
              className="ah-input ah-mono ah-flow-input"
              value={awsProfile}
              autoComplete="off"
              spellCheck={false}
              placeholder={`${project}-${name.trim() || "staging"}`}
              onChange={(event) => {
                setAwsProfile(event.target.value);
              }}
            />
            <span className="ah-small ah-muted">
              The profile name in ~/.aws/config, not its keys. Actions run with it.
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
          <dl className="ah-flow-review">
            {steps.slice(0, -1).map((step, position) => (
              <div key={step.title} className="ah-flow-review-row">
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
          <div className="ah-flow-next">
            <strong className="ah-small">What happens next</strong>
            <ol className="ah-small">
              {scope === "team" ? (
                <>
                  <li>
                    agent-hub writes it to <code className="ah-mono">hub.json</code> in the hub.
                    Nothing is committed.
                  </li>
                  <li>
                    Run <code className="ah-mono">./hub sync</code> so AGENTS.md lists it.
                  </li>
                  <li>Review the diff and open a hub PR.</li>
                </>
              ) : (
                <>
                  <li>
                    agent-hub writes it to <code className="ah-mono">hub.local.json</code> on this
                    machine.
                  </li>
                  <li>Your agents see it in their next session.</li>
                </>
              )}
              <li>Then add the services that run there, like an API or a database.</li>
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
      intro="An environment is a place where your systems run: your machine, a test stack, production. Agents learn where they are and what they may do there."
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
      preview={preview}
    >
      {body}
    </SetupFlow>
  );
}
