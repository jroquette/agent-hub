import type { ComponentType, ReactElement } from "react";
import type { RouteObject } from "react-router";

// Each routed screen loads on demand, in its own chunk; while its code loads, `main#main` shows the
// page skeleton after 300 ms (AGH-614, AC-1, AC-6).

/** The route fields that load the screen `name` exports from the module `load` imports, on demand. */
export function lazyScreen<Name extends string>(
  load: () => Promise<Record<Name, ComponentType>>,
  name: Name,
): Pick<RouteObject, "lazy"> {
  throw new Error(`lazyScreen is not implemented yet (${name}, ${typeof load})`);
}

/** The page skeleton `main#main` shows while a routed screen's code loads. */
export function RouteSkeleton(): ReactElement {
  throw new Error("RouteSkeleton is not implemented yet");
}
