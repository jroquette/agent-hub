import { createContext, useContext, useLayoutEffect, useMemo, useState } from "react";
import type { ComponentType, ReactElement } from "react";
import { Navigate, Outlet, useNavigation } from "react-router";
import type { RouteObject, To } from "react-router";

import { SKELETON_DELAY_MS, Skeleton, useDelayed, useSkeleton } from "../components/feedback";

// Each routed screen loads on demand, in its own chunk; while its code loads, `main#main` shows the
// page skeleton after 300 ms, and once shown, for at least 300 ms.

/** "Loading page" is said only once a route's code has been loading this long (spec 22). */
const ANNOUNCE_AFTER_MS = 1_000;
/** From this long on, a line under the skeleton, and the status, say the page is still loading. */
const STILL_LOADING_AFTER_MS = 10_000;
const STILL_LOADING = "Still loading this page. Check that hub web is still running.";

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
  /** The skeleton's bars appeared at `shownAt`, or went away (null). */
  setShownAt: (shownAt: number | null) => void;
  /** What the status beside `main#main` says for the skeleton, "" for nothing. */
  setStatus: (status: string) => void;
}

export const PageSkeletonContext = createContext<PageSkeleton>({
  shownAt: null,
  setShownAt: () => undefined,
  setStatus: () => undefined,
});

/**
 * `main#main`'s side of the page skeleton: `page` for the skeletons in it, `busy` while their bars
 * show, and `status`, what to say outside `main`, since a screen reader may hold back what changes
 * inside a busy element.
 */
export function usePageSkeleton(): { page: PageSkeleton; busy: boolean; status: string } {
  const [shownAt, setShownAt] = useState<number | null>(null);
  const [status, setStatus] = useState("");
  const page = useMemo(() => ({ shownAt, setShownAt, setStatus }), [shownAt]);
  return { page, busy: shownAt !== null, status };
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
  const { setShownAt, setStatus } = useContext(PageSkeletonContext);
  useLayoutEffect(() => {
    if (!shown) return undefined;
    // A page's bars appear the skeleton delay into its load. So bars that take over from others
    // already shown, later into the load, go on with their time: the page after them then waits
    // only for what is left of the 300 ms the user has seen.
    setShownAt(Date.now() - Math.max(0, waited - SKELETON_DELAY_MS));
    return () => {
      setShownAt(null);
    };
  }, [shown, waited, setShownAt]);
  // "Loading page" after 1 s, then the line the skeleton shows after 10 s, which inside the busy
  // `main` a screen reader would not read.
  const status = stillLoading ? STILL_LOADING : announced ? "Loading page" : "";
  useLayoutEffect(() => {
    if (status === "") return undefined;
    setStatus(status);
    return () => {
      setStatus("");
    };
  }, [status, setStatus]);
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
              {STILL_LOADING}
            </p>
          )}
        </>
      )}
    </div>
  );
}

/**
 * A routed page: a screen, a redirect to one, or the error page of a route. When it mounts while
 * a page skeleton shows, it keeps the skeleton until that has shown for the skeleton delay: on a
 * first load the router drops its fallback as soon as the page's code arrives, or fails to,
 * however briefly the fallback's bars have shown. After a navigation `RouteOutlet` has already
 * waited, so the page draws at once.
 */
export function RoutedPage({ page }: { page: ReactElement }): ReactElement {
  const { shownAt } = useContext(PageSkeletonContext);
  // How long the skeleton has shown when the page mounts, or null when none shows.
  const [shownFor] = useState(() => (shownAt === null ? null : Date.now() - shownAt));
  const done = useDelayed(shownFor === null ? 0 : SKELETON_DELAY_MS - shownFor);
  return done ? page : <RouteSkeleton waited={SKELETON_DELAY_MS + (shownFor ?? 0)} />;
}

/**
 * A page that only redirects: it goes to `to` in place of the current entry, as
 * `<Navigate replace>` does. A page skeleton that shows as it is drawn stays until the router
 * lands on `to`, whose code may still be loading: alone, the redirect would draw an empty
 * `main#main` meanwhile. A page that shows something before it redirects keeps that drawn next to
 * its `<Navigate>` instead.
 */
export function Redirect({ to }: { to: To }): ReactElement {
  const { shownAt } = useContext(PageSkeletonContext);
  // Read once, when drawn: from then on the skeleton kept is the redirect's own.
  const [shownFor] = useState(() => (shownAt === null ? null : Date.now() - shownAt));
  return (
    <>
      {shownFor !== null && <RouteSkeleton waited={SKELETON_DELAY_MS + shownFor} />}
      <Navigate to={to} replace />
    </>
  );
}

/**
 * The route fields that load the screen `name` exports from the module `load` imports, on demand.
 * For a screen that only redirects to a screen of another module, `opens` imports that module too,
 * so both are in before the route draws, and the previous screen stays until then.
 */
export function lazyScreen<Name extends string>(
  load: () => Promise<Record<Name, ComponentType>>,
  name: Name,
  opens?: () => Promise<unknown>,
): Pick<RouteObject, "lazy"> {
  return {
    lazy: async () => {
      const [screens] = await Promise.all([
        loadCode(load),
        opens === undefined ? undefined : loadCode(opens),
      ]);
      const Screen: ComponentType = screens[name];
      // One element for the route, so a new skeleton state never draws the screen again.
      return { element: <RoutedPage page={<Screen />} /> };
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
      return { element: <RoutedPage page={redirect} /> };
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
