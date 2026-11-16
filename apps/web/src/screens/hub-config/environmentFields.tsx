import type { ReactNode } from "react";

import { Banner, Icon, OptionRow, StatusBadge } from "../../components";
import { EnvFileVariables } from "./EnvFileVariables";
import { ACCESSES, ACCESS_LOOK, addressKind, exampleAddress, lineWithValue } from "./environments";
import type { Access, ServiceKind, SourcedEnvironment } from "./environments";

/* The answers adding and changing an environment or a service share: the same rows, words and
   inline fields, so the add flows and the in-place edits read alike. */

export type SecretsFrom = "file" | "shell" | "none";

/** What agents may do there: the three access rows, then whether it is production. */
export function AccessFields({
  idPrefix,
  legend,
  access,
  onAccess,
  production,
  onProduction,
  looser,
  productionLocked,
}: {
  idPrefix: string;
  legend: string;
  access: Access;
  onAccess: (access: Access) => void;
  production: boolean;
  onProduction: (production: boolean) => void;
  /** Why an access row is not available (stricter than the team's only), else null. */
  looser?: ((candidate: Access) => string | null) | undefined;
  /** Why "This is production" cannot change here, else undefined. */
  productionLocked?: string | undefined;
}) {
  return (
    <div className="ah-stack" style={{ gap: 16 }}>
      <fieldset className="ah-env-fieldset">
        <legend className="ah-sr">{legend}</legend>
        <div className="ah-options">
          {ACCESSES.map((candidate) => {
            const reason = looser?.(candidate) ?? null;
            return (
              <OptionRow
                key={candidate}
                type="radio"
                name={`${idPrefix}-access`}
                icon={ACCESS_LOOK[candidate].icon}
                label={ACCESS_LOOK[candidate].card}
                recommended={production && candidate === "read"}
                disabled={reason !== null}
                description={reason ?? ACCESS_LOOK[candidate].help}
                checked={access === candidate}
                onToggle={() => {
                  onAccess(candidate);
                }}
              />
            );
          })}
        </div>
      </fieldset>
      <div className="ah-options">
        <OptionRow
          type="checkbox"
          name={`${idPrefix}-production`}
          icon="shield-x"
          label="This is production"
          disabled={productionLocked !== undefined}
          description={
            productionLocked ??
            "Real customers and real data. Agents never write or delete here, whatever you pick above."
          }
          checked={production}
          onToggle={() => {
            onProduction(!production);
          }}
        />
      </div>
      {production && access !== "read" && (
        <Banner tone="warning" boxed>
          Production where agents can {access === "ask" ? "ask to change" : "change"} data: doctor
          will warn. Read only is recommended.
        </Banner>
      )}
    </div>
  );
}

/** Where the secrets of scripted actions live: an env file, the shell, or not yet; then the
 * optional AWS profile. Each choice's field sits inside its row. */
export function SecretsFields({
  idPrefix,
  legend,
  project,
  firstRepo,
  environmentName,
  secretsFrom,
  onSecretsFrom,
  envFile,
  onEnvFile,
  variables,
  onVariables,
  awsProfile,
  onAwsProfile,
  shellLocked,
}: {
  idPrefix: string;
  legend: string;
  project: string;
  firstRepo: string | undefined;
  environmentName: string;
  secretsFrom: SecretsFrom;
  onSecretsFrom: (from: SecretsFrom) => void;
  envFile: string;
  onEnvFile: (path: string) => void;
  variables: string;
  onVariables: (names: string) => void;
  awsProfile: string;
  onAwsProfile: (profile: string) => void;
  /** Why the shell names and the AWS profile cannot change here (they need Ask Claude). */
  shellLocked?: string | undefined;
}) {
  const valueLine = lineWithValue(variables);
  const shownName = environmentName || "staging";
  return (
    <div className="ah-stack" style={{ gap: 20 }}>
      <fieldset className="ah-env-fieldset">
        <legend className="ah-sr">{legend}</legend>
        <div className="ah-options">
          <OptionRow
            type="radio"
            name={`${idPrefix}-secrets`}
            icon="file-text"
            label="In an env file"
            recommended
            description="A .env file in a repo, ignored by git. Actions get its variables."
            checked={secretsFrom === "file"}
            onToggle={() => {
              onSecretsFrom("file");
            }}
          >
            {secretsFrom === "file" && (
              <span className="ah-stack ah-setup-inline" style={{ gap: 6 }}>
                <label htmlFor={`${idPrefix}-file`} className="ah-config-field-label">
                  Env file path
                </label>
                <input
                  id={`${idPrefix}-file`}
                  className="ah-input ah-mono ah-setup-input"
                  value={envFile}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={`${firstRepo ?? "my-repo"}/.env.${shownName}`}
                  onChange={(event) => {
                    onEnvFile(event.target.value);
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
            name={`${idPrefix}-secrets`}
            icon="square-terminal"
            label="In my shell"
            disabled={shellLocked !== undefined && secretsFrom !== "shell"}
            description={
              shellLocked !== undefined && secretsFrom !== "shell"
                ? shellLocked
                : "Variables you export in your terminal, like in ~/.zshrc."
            }
            checked={secretsFrom === "shell"}
            onToggle={() => {
              onSecretsFrom("shell");
            }}
          >
            {secretsFrom === "shell" && (
              <span className="ah-stack ah-setup-inline" style={{ gap: 4 }}>
                <label htmlFor={`${idPrefix}-variables`} className="ah-config-field-label">
                  Variable names
                </label>
                <textarea
                  id={`${idPrefix}-variables`}
                  className="ah-input ah-mono ah-config-textarea ah-setup-input"
                  rows={3}
                  value={variables}
                  readOnly={shellLocked !== undefined}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder="DATABASE_URL"
                  aria-invalid={valueLine !== null ? true : undefined}
                  onChange={(event) => {
                    onVariables(event.target.value);
                  }}
                />
                <span
                  aria-live="polite"
                  className={valueLine !== null ? "ah-small ah-config-error" : "ah-small ah-muted"}
                >
                  {valueLine !== null
                    ? `Line ${String(valueLine)}: only the name. Remove = and what follows.`
                    : (shellLocked ?? "Names only, never a value. One per line.")}
                </span>
              </span>
            )}
          </OptionRow>
          <OptionRow
            type="radio"
            name={`${idPrefix}-secrets`}
            icon="circle-dashed"
            label="Not yet"
            description="Actions get no secrets here for now. You can add them later."
            checked={secretsFrom === "none"}
            onToggle={() => {
              onSecretsFrom("none");
            }}
          />
        </div>
      </fieldset>
      <div className="ah-stack" style={{ gap: 4 }}>
        <label htmlFor={`${idPrefix}-aws`} className="ah-config-field-label">
          AWS profile <span className="ah-muted">(optional)</span>
        </label>
        <input
          id={`${idPrefix}-aws`}
          className="ah-input ah-mono ah-setup-input ah-setup-input-short"
          value={awsProfile}
          readOnly={shellLocked !== undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder={`${project}-${shownName}`}
          onChange={(event) => {
            onAwsProfile(event.target.value);
          }}
        />
        <span className="ah-small ah-muted">
          {shellLocked ?? "If it runs on AWS: the profile name in ~/.aws/config, never its keys."}
        </span>
      </div>
    </div>
  );
}

/** One row per environment: its name and access on the left, the service's address on the right. */
export function AddressList({
  idPrefix,
  environments,
  kind,
  values,
  onChange,
  rowEnd,
  rowNote,
  removed,
}: {
  idPrefix: string;
  environments: readonly SourcedEnvironment[];
  kind: ServiceKind | undefined;
  values: Record<string, string>;
  onChange: (environment: string, value: string) => void;
  /** Something at the end of a row, such as its remove button. */
  rowEnd?: ((environment: SourcedEnvironment) => ReactNode) | undefined;
  /** A line under a row's input, else its URL or name hint. */
  rowNote?: ((environment: SourcedEnvironment) => ReactNode) | undefined;
  /** Rows marked to be removed on save. */
  removed?: ReadonlySet<string> | undefined;
}) {
  return (
    <div className="ah-setup-addresses">
      {environments.map((environment) => {
        const value = values[environment.name] ?? "";
        const look = ACCESS_LOOK[environment.access];
        const inputId = `${idPrefix}-at-${environment.name}`;
        const gone = removed?.has(environment.name) ?? false;
        return (
          <div
            key={environment.name}
            className="ah-setup-address"
            data-removed={gone || undefined}
            data-has-end={rowEnd ? true : undefined}
          >
            <div className="ah-stack" style={{ gap: 4 }}>
              <span className="ah-env-name">
                <code className="ah-mono">{environment.name}</code>
                {environment.production && <StatusBadge status="guard" label="Production" quiet />}
              </span>
              <span className="ah-small ah-muted ah-env-access">
                <Icon name={look.icon} /> {look.short}
              </span>
            </div>
            <div className="ah-stack" style={{ gap: 4 }}>
              <input
                id={inputId}
                className="ah-input ah-mono ah-setup-input"
                aria-label={`Address in ${environment.name}`}
                value={value}
                disabled={gone}
                autoComplete="off"
                spellCheck={false}
                placeholder={kind ? exampleAddress(kind, environment) : "address"}
                aria-describedby={`${inputId}-kind`}
                onChange={(event) => {
                  onChange(environment.name, event.target.value);
                }}
              />
              <span id={`${inputId}-kind`} className="ah-small ah-muted">
                {rowNote?.(environment) ??
                  (value.trim() === ""
                    ? "Empty: it does not run here."
                    : addressKind(value.trim()) === "url"
                      ? "A URL."
                      : "A resource name.")}
              </span>
            </div>
            {rowEnd?.(environment)}
          </div>
        );
      })}
    </div>
  );
}
