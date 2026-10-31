import "./RouteError.css";

import type { ReactElement } from "react";
import { Link, useLocation, useRouteError } from "react-router";

import { Button } from "../components/core";
import { RouteCodeError } from "./routeLoading";

// The page the shell shows in `main#main` when a route's code fails to load, or when its screen
// throws while rendering (AGH-614, AC-7).

/** At most this much of an error's first line is shown. */
const MESSAGE_LIMIT = 200;

interface RouteErrorCopy {
  overline: string;
  title: string;
  line: string;
  hint: string;
}

/** The first line of the error's message, at most `MESSAGE_LIMIT` characters, as plain text. */
function firstLine(error: Error): string {
  const line = error.message.split(/\r?\n/, 1)[0] ?? "";
  return Array.from(line.trim()).slice(0, MESSAGE_LIMIT).join("").trimEnd();
}

/** The asset a failed `import()` names (`assets/<chunk>.js`), or null: Safari's message names none. */
function chunkFile(error: RouteCodeError): string | null {
  return /\bhttps?:\/\/[^/\s]+\/([^\s"'<>]+)/.exec(firstLine(error))?.[1] ?? null;
}

/**
 * A screen that threw while drawing says so, with the first line of its error. A route whose code
 * did not load, or an error of unknown kind, gets the "could not load" copy: reloading fixes both.
 */
function copyFor(error: unknown): RouteErrorCopy {
  if (error instanceof Error && !(error instanceof RouteCodeError)) {
    const line = firstLine(error).replace(/\.$/, "");
    return {
      overline: "Page error",
      title: "This page could not be shown",
      line: line === "" ? "It failed while drawing." : `It failed while drawing: ${line}.`,
      hint: "Other pages still work. Reload the page to try again.",
    };
  }
  return {
    overline: "Page did not load",
    title: "This page could not load",
    line: "The app could not fetch this page from hub web.",
    hint: "The app may have been updated since this tab opened, or hub web stopped. Reloading gets the current version.",
  };
}

/** The routes' error element: "This page could not load" or "This page could not be shown". */
export function RouteError(): ReactElement {
  const error = useRouteError();
  const { pathname, search } = useLocation();
  const copy = copyFor(error);
  const file = error instanceof RouteCodeError ? chunkFile(error) : null;
  return (
    <div className="ah-route-error">
      <div className="ah-route-error-column">
        <div className="ah-overline">{copy.overline}</div>
        <div className="ah-route-error-alert" role="alert">
          <h1 className="ah-h1">{copy.title}</h1>
          <p>{copy.line}</p>
        </div>
        <p className="ah-muted">{copy.hint}</p>
        <div className="ah-row ah-wrap ah-route-error-actions">
          <Button
            variant="primary"
            icon="refresh-cw"
            onClick={() => {
              location.reload();
            }}
          >
            Reload page
          </Button>
          <Link className="ah-btn" to="/">
            Go to Portfolio
          </Link>
        </div>
        <div className="ah-small ah-subtle">
          Requested: <span className="ah-mono">{pathname + search}</span>
          {file !== null && (
            <>
              {" · file "}
              <span className="ah-mono">{file}</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
