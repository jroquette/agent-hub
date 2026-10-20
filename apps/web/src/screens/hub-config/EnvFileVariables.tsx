import { useEffect, useState } from "react";

import { Icon } from "../../components";
import { useApi } from "../../lib/api";

const DEBOUNCE_MS = 400;

/** ``value`` once it stopped changing for ``ms``. */
function useSettled(value: string, ms: number): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSettled(value);
    }, ms);
    return () => {
      clearTimeout(timer);
    };
  }, [value, ms]);
  return settled;
}

/**
 * What an env file holds, by name only: the server reads the file and sends back its variable
 * names, never a value. Says when there is no file yet, when it is outside the hub and its repos,
 * and when git does not ignore it (its secrets could be committed).
 */
export function EnvFileVariables({ project, path }: { project: string; path: string }) {
  const settled = useSettled(path.trim(), DEBOUNCE_MS);
  const found = useApi(
    "/api/v1/projects/{project}/env-file-keys",
    { path: { project }, query: { path: settled } },
    { enabled: settled !== "", retry: false, staleTime: 0 },
  );

  if (settled === "") return null;
  if (found.isPending)
    return (
      <p className="ah-small ah-muted ah-env-keys" aria-live="polite">
        <Icon name="loader" /> Looking at the file…
      </p>
    );
  if (found.isError)
    return (
      <p className="ah-small ah-config-error ah-env-keys" aria-live="polite">
        {found.error.status === 400
          ? "Not a path agent-hub accepts: relative to the workspace, no .., no leading / or ~."
          : "Could not look at the file."}
      </p>
    );

  const file = found.data;
  return (
    <div className="ah-env-keys" aria-live="polite">
      {file.problem ? (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          <Icon name="info" /> {file.problem}{" "}
          {!file.exists && file.holder !== null && "Create it there; agent-hub will read it then."}
        </p>
      ) : (
        <>
          <p className="ah-small" style={{ margin: 0 }}>
            <Icon name="circle-check" /> Found {file.keys.length}{" "}
            {file.keys.length === 1 ? "variable" : "variables"}
            {file.truncated ? " (only the first are listed)" : ""}. Scripted actions get all of
            them; the screen never sees their values.
          </p>
          {file.keys.length > 0 && (
            <ul className="ah-env-key-list" aria-label="Variables in the env file">
              {file.keys.map((key) => (
                <li key={key}>
                  <code className="ah-mono">{key}</code>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {file.exists && file.ignored === false && (
        <p className="ah-small ah-config-error" style={{ margin: 0 }}>
          <Icon name="triangle-alert" /> git does not ignore this file in {file.holder}: add it to
          .gitignore so its secrets are never committed.
        </p>
      )}
    </div>
  );
}
