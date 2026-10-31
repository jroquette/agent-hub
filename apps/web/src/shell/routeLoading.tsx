import { createContext, useContext, useLayoutEffect } from "react";
import type { ComponentType, ReactElement } from "react";
import { Outlet, useNavigation } from "react-router";
import type { RouteObject } from "react-router";

import { SKELETON_DELAY_MS, Skeleton, useDelayed, useSkeleton } from "../components/feedback";

// Each routed screen loads on demand, in its own chunk; while its code loads, `main#main` shows the
// page skeleton after 300 ms (AGH-614, AC-1, AC-6).

/** "Loading page" is said only once a route's code has been loading this long (spec 22). */
const ANNOUNCE_AFTER_MS = 1_000;
/** From this long on, a line under the skeleton says the page is still loading. */
const STILL_LOADING_AFTER_MS = 10_000;

/** A routed screen's module that did not load: `RouteError` says the page could not load. */
export class RouteCodeError extends Error {
  override name = "RouteCodeError";

  constructor(cause: unknown) {
    super(cause instanceof Error ? cause.message : String(cause), { cause });
  }
}

/** The route fields that load the screen `name` exports from the module `load` imports, on demand. */
export function lazyScreen<Name extends string>(
  load: () => Promise<Record<Name, ComponentType>>,
  name: Name,
): Pick<RouteObject, "lazy"> {
  return {
    lazy: async () => {
      const screens = await load().catch((error: unknown) => {
        throw new RouteCodeError(error);
      });
      return { Component: screens[name] };
    },
  };
}

/** Marks `main#main` busy while a page skeleton's bars show in it (`aria-busy`). */
export const PageBusyContext = createContext<(busy: boolean) => void>(() => undefined);

export interface RouteSkeletonProps {
  /**
   * How long the route's code has been loading when the skeleton mounts, in milliseconds. A first
   * load's fallback mounts at once and waits the skeleton delay itself; `RouteOutlet` mounts it
   * once a navigation has lasted that delay.
   */
  waited?: number;
}

/** The page skeleton `main#main` shows while a routed screen's code loads. */
export function RouteSkeleton({ waited = 0 }: RouteSkeletonProps): ReactElement {
  const shown = useDelayed(SKELETON_DELAY_MS - waited);
  const announced = useDelayed(ANNOUNCE_AFTER_MS - waited);
  const stillLoading = useDelayed(STILL_LOADING_AFTER_MS - waited);
  const setBusy = useContext(PageBusyContext);
  useLayoutEffect(() => {
    if (!shown) return undefined;
    setBusy(true);
    return () => {
      setBusy(false);
    };
  }, [shown, setBusy]);
  return (
    <div className="ah-page">
      {shown && (
        <>
          <Skeleton width={120} height={12} delay={0} style={{ margin: "3px 0" }} />
          <div className="ah-stack" style={{ gap: 4 }}>
            <Skeleton width={240} height={24} delay={0} style={{ margin: "4px 0" }} />
            <Skeleton width="50%" height={12} delay={0} style={{ margin: "3px 0" }} />
          </div>
          <div className="ah-card ah-card-body">
            <Skeleton lines={6} delay={0} />
          </div>
          {stillLoading && (
            <p className="ah-small ah-muted" style={{ margin: 0 }}>
              Still loading this page. Check that hub web is still running.
            </p>
          )}
        </>
      )}
      <span className="ah-sr" role="status">
        {announced ? "Loading page" : ""}
      </span>
    </div>
  );
}

/**
 * The routed screen. While a navigation loads the next screen's code, the previous screen stays
 * for the skeleton delay, then the page skeleton takes its place, for at least as long.
 */
export function RouteOutlet(): ReactElement {
  const navigating = useNavigation().state !== "idle";
  const skeleton = useSkeleton(navigating);
  return skeleton ? <RouteSkeleton waited={SKELETON_DELAY_MS} /> : <Outlet />;
}
