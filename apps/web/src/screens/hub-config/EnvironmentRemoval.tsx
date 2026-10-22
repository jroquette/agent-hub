import { useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "../../components";
import { Mono } from "./parts";
import {
  ACCESS_LOOK,
  LOCAL_FILE,
  count,
  endpointText,
  endpointsIn,
  isMine,
  isTeams,
  postEnvironmentEdits,
  refusalOf,
  serviceLabel,
} from "./environments";
import type { HubConfigView, SingleEdit, SourcedEnvironment } from "./environments";

type Removal =
  | { kind: "remove"; environment: SourcedEnvironment }
  | { kind: "loosen"; environment: SourcedEnvironment };

/**
 * Removing an environment, wherever it is shown (the overview's row, its own page): one
 * confirmation that lists the addresses going with it, the name typed for production, and the
 * one write that removes them all. A team environment I tightened offers "Use the team's access"
 * instead, which removes only my stricter setting.
 */
export function useEnvironmentRemoval({
  view,
  onSaved,
  onDone,
}: {
  view: HubConfigView;
  onSaved: (message: string, team: boolean) => void;
  /** After a removal is written: move focus, or leave a page that no longer exists. */
  onDone?: (removal: Removal) => void;
}): {
  startRemove: (environment: SourcedEnvironment) => void;
  startLoosen: (environment: SourcedEnvironment) => void;
  dialogs: ReactNode;
} {
  const client = useQueryClient();
  const [removal, setRemoval] = useState<Removal | null>(null);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const open = (next: Removal) => {
    setFailure(null);
    setRemoval(next);
  };

  const run = (current: Removal) => {
    const environment = current.environment;
    const used = endpointsIn(view.environments, environment.name);
    // A tightened team environment, loosened: only my own setting goes.
    const scope = isMine(environment) ? "local" : "team";
    const ops: SingleEdit[] =
      current.kind === "loosen"
        ? [{ op: "remove_environment", scope: "local", name: environment.name }]
        : [
            ...used.map(({ service, endpoint }): SingleEdit => ({
              op: "remove_endpoint",
              scope: endpoint.source === LOCAL_FILE ? "local" : "team",
              repo: service.repo,
              service: service.name,
              environment: environment.name,
            })),
            { op: "remove_environment", scope, name: environment.name },
          ];
    const team =
      current.kind !== "loosen" &&
      (scope === "team" || used.some(({ endpoint }) => endpoint.source !== LOCAL_FILE));
    setPending(true);
    postEnvironmentEdits(client, view.project, ops)
      .then(() => {
        setPending(false);
        setRemoval(null);
        onSaved(
          current.kind === "loosen"
            ? `${environment.name} is back to the team's access`
            : `Removed ${environment.name}`,
          team,
        );
        onDone?.(current);
      })
      .catch((error: unknown) => {
        setPending(false);
        setFailure(refusalOf(error).summary);
      });
  };

  let dialogs: ReactNode = null;
  if (removal?.kind === "remove") {
    const environment = removal.environment;
    const used = endpointsIn(view.environments, environment.name);
    dialogs = (
      <ConfirmDialog
        title={
          used.length > 0
            ? `Remove ${environment.name} and its ${count(used.length, "address")}?`
            : `Remove environment ${environment.name}?`
        }
        confirmLabel={
          pending
            ? "Removing…"
            : used.length > 0
              ? `Remove environment and ${count(used.length, "address")}`
              : "Remove environment"
        }
        pending={pending}
        requireText={environment.production ? environment.name : undefined}
        consequences={[
          used.length > 0
            ? `Agents stop seeing ${environment.name} and where each service runs there.`
            : `Agents stop seeing ${environment.name}.`,
          ...(isMine(environment) ? [] : ["hub.json changes; run ./hub sync and open a hub PR."]),
          ...(environment.production ? [`Type ${environment.name} to confirm.`] : []),
        ]}
        onCancel={() => {
          setRemoval(null);
        }}
        onConfirm={() => {
          run(removal);
        }}
      >
        {used.length > 0 && (
          <ul className="ah-consequences">
            {used.map(({ service, endpoint }) => (
              <li key={`${service.repo}/${service.name}`}>
                {serviceLabel(service.repo, service.name)} · <Mono>{endpointText(endpoint)}</Mono>
              </li>
            ))}
          </ul>
        )}
        {failure && (
          <p role="alert" className="ah-config-error">
            {failure}
          </p>
        )}
      </ConfirmDialog>
    );
  } else if (removal?.kind === "loosen") {
    const environment = removal.environment;
    dialogs = (
      <ConfirmDialog
        title={`Use the team's access for ${environment.name}?`}
        tone="primary"
        confirmLabel={pending ? "Saving…" : "Use the team's access"}
        pending={pending}
        consequences={[
          `Your agents ${ACCESS_LOOK[environment.team_access ?? "write"].short} in ${environment.name} again, as the team set it.`,
          "Your stricter setting is removed from hub.local.json.",
        ]}
        onCancel={() => {
          setRemoval(null);
        }}
        onConfirm={() => {
          run(removal);
        }}
      >
        {failure && (
          <p role="alert" className="ah-config-error">
            {failure}
          </p>
        )}
      </ConfirmDialog>
    );
  }

  return {
    startRemove: (environment) => {
      open({ kind: "remove", environment });
    },
    startLoosen: (environment) => {
      // Only a team environment I tightened has a stricter setting to drop.
      if (isTeams(environment)) open({ kind: "loosen", environment });
    },
    dialogs,
  };
}
