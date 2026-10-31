import type { ReactElement } from "react";

// The page the shell shows in `main#main` when a route's code fails to load, or when its screen
// throws while rendering (AGH-614, AC-7).

/** The routes' error element: "This page could not load" or "This page could not be shown". */
export function RouteError(): ReactElement {
  throw new Error("RouteError is not implemented yet");
}
