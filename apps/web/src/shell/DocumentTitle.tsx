import { useEffect } from "react";
import { useLocation, useMatch } from "react-router";

import { useScreenTitle } from "./screenContext";

export const APP_NAME = "agent-hub";

/**
 * The browser tab's text: the screen's own name, its project when the route has one, then the
 * app name, so a row of tabs tells the pages apart ("Sessions · agent-hub",
 * "Environments · demo-api · agent-hub"). The name is the one the screen shows (its heading,
 * else the breadcrumb's current page), re-read while data arrives.
 */
export function documentTitle(screen: string | null, project: string | null): string {
  return [screen, project, APP_NAME]
    .filter(
      (part, i, parts): part is string => part !== null && part !== "" && parts.indexOf(part) === i,
    )
    .join(" · ");
}

/** Keeps `document.title` in step with the screen on show; the shell mounts it once. */
export function DocumentTitle() {
  const { pathname } = useLocation();
  const screen = useScreenTitle(pathname);
  const project = useMatch("/projects/:project/*")?.params.project ?? null;
  useEffect(() => {
    document.title = documentTitle(screen, project);
  }, [screen, project]);
  return null;
}
