import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useState } from "react";
import type { ComponentType, ReactElement } from "react";
import { Outlet, useNavigation } from "react-router";
import type { RouteObject } from "react-router";

import { SKELETON_DELAY_MS, Skeleton, useDelayed, useSkeleton } from "../components/feedback";

// Each routed screen loads on demand, in its own chunk; while its code loads, `main#main` shows the
// page skeleton after 300 ms, and once shown, for at least 300 ms.

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

/** The module `load` imports; a failure to fetch it is a `RouteCodeError`. */
function loadCode<Module>(load: () => Promise<Module>): Promise<Module> {
  return load().catch((error: unknown) => {
    throw new RouteCodeError(error);
  });
}

/** What `main#main` knows of the page skeleton in it, and how a skeleton tells it. */
export interface PageSkeleton {
  /** When the bars of the skeleton shown now appeared (`Date.now()`), or null while none show. */
  shownAt: number | null;
  /** The skeleton's bars appear (true) or go away (false). */
  setShown: (shown: boolean) => void;
  /** "Loading page" is said (true) or taken back (false). */
  setAnnounced: (announced: boolean) => void;
}

export const PageSkeletonContext = createContext<PageSkeleton>({
  shownAt: null,
  setShown: () => undefined,
  setAnnounced: () => undefined,
});

/**
 * `main#main`'s side of the page skeleton: `page` for the skeletons in it, `busy` while their bars
 * show, and `status`, what to say outside `main`, since a screen reader may hold back what changes
 * inside a busy element.
 */
export function usePageSkeleton(): { page: PageSkeleton; busy: boolean; status: string } {
  const [shownAt, setShownAt] = useState<number | null>(null);
  const [announced, setAnnounced] = useState(false);
  const setShown = useCallback((shown: boolean) => {
    setShownAt(shown ? Date.now() : null);
  }, []);
  const page = useMemo(() => ({ shownAt, setShown, setAnnounced }), [shownAt, setShown]);
  return { page, busy: shownAt !== null, status: announced ? "Loading page" : "" };
}

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
  const { setShown, setAnnounced } = useContext(PageSkeletonContext);
  useLayoutEffect(() => {
    if (!shown) return undefined;
    setShown(true);
    return () => {
      setShown(false);
    };
  }, [shown, setShown]);
  useLayoutEffect(() => {
    if (!announced) return undefined;
    setAnnounced(true);
    return () => {
      setAnnounced(false);
    };
  }, [announced, setAnnounced]);
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
    </div>
  );
}

/**
 * A routed page: a screen, or a redirect to one. When it mounts while a page skeleton shows, it
 * keeps the skeleton until that has shown for the skeleton delay: on a first load the router
 * drops its fallback as soon as the page's code arrives, however briefly the fallback's bars have
 * shown. After a navigation `RouteOutlet` has already waited, so the page draws at once.
 */
function RoutedScreen({ page }: { page: ReactElement }): ReactElement {
  const { shownAt } = useContext(PageSkeletonContext);
  // How long the skeleton has shown when the page mounts, or null when none shows.
  const [shownFor] = useState(() => (shownAt === null ? null : Date.now() - shownAt));
  const done = useDelayed(shownFor === null ? 0 : SKELETON_DELAY_MS - shownFor);
  return done ? page : <RouteSkeleton waited={SKELETON_DELAY_MS + (shownFor ?? 0)} />;
}

/** The route fields that load the screen `name` exports from the module `load` imports, on demand. */
export function lazyScreen<Name extends string>(
  load: () => Promise<Record<Name, ComponentType>>,
  name: Name,
): Pick<RouteObject, "lazy"> {
  return {
    lazy: async () => {
      const Screen: ComponentType = (await loadCode(load))[name];
      // One element for the route, so a new skeleton state never draws the screen again.
      return { element: <RoutedScreen page={<Screen />} /> };
    },
  };
}

/**
 * The route fields of a redirect to a screen that loads on demand: `redirect` draws only once the
 * module `load` imports, the target screen's, has arrived, and on a first load once a page
 * skeleton shown meanwhile has had its time. Drawn at once, it would empty `main#main`, and move
 * the address and the nav, while the target's code still loads.
 */
export function lazyRedirect(
  load: () => Promise<unknown>,
  redirect: ReactElement,
): Pick<RouteObject, "lazy"> {
  return {
    lazy: async () => {
      await loadCode(load);
      return { element: <RoutedScreen page={redirect} /> };
    },
  };
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
