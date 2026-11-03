import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueries,
  useQueryClient,
} from "@tanstack/react-query";
import { useContext, useEffect, useRef, useState } from "react";

import type { components } from "../../api/schema";
import {
  apiGet,
  apiKey,
  apiPost,
  apiQuery,
  ScreenReadContext,
  useApi,
  type ApiParams,
  type ApiProblem,
} from "../../lib/api";
import { derivedWorkdirId, servedCheckout } from "../../lib/devCheckout";
import type { ScreenReadSeed } from "../../lib/screenRead";
import { openStream } from "../../lib/sse";
import { sessionControlUnavailable, type Unavailable } from "./control";
import type { SectionId } from "./sections";

export type Session = components["schemas"]["Session"];
type SessionPage = components["schemas"]["Page_Session_"];
type SessionsView = components["schemas"]["SessionsView"];
export type SessionQuery = NonNullable<ApiParams<"/api/v1/sessions">["query"]>;
type SectionQueries = Record<SectionId, SessionQuery | null>;

/** Rows per page ("Showing 50 of ~1,240"). */
export const PAGE_SIZE = 50;

/** The paged query of the sessions matching `query`: the key a section reads and the read seeds. */
const sessionPagesKey = (query: SessionQuery) =>
  [...apiKey("/api/v1/sessions", { query }), "pages"] as const;

/** The first page a screen read wrote under a paged key, if it wrote one. */
const firstPage = (data: unknown) => (data as { pages?: SessionPage[] } | undefined)?.pages?.[0];

/** Sessions matching `query` (null: not asked), page by page; "Load more" asks for the next cursor (spec 14). */
export function useSessionPages(query: SessionQuery | null) {
  const screenRead = useContext(ScreenReadContext);
  return useInfiniteQuery<
    SessionPage,
    ApiProblem,
    { pages: SessionPage[] },
    readonly unknown[],
    string | null
  >({
    queryKey: sessionPagesKey(query ?? {}),
    enabled: query !== null,
    initialPageParam: null,
    queryFn: ({ pageParam, queryKey, signal }) => {
      const read = () =>
        apiGet(
          "/api/v1/sessions",
          { query: { ...(query ?? {}), limit: PAGE_SIZE, cursor: pageParam } },
          signal,
        );
      // The first page waits for a screen read above that brings it (ADR 0056).
      const held = pageParam === null ? screenRead?.hold(queryKey) : null;
      if (!held) return read();
      return held.then((data) => firstPage(data) ?? read());
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    // A filter or sort change keeps the shown pages until the new ones arrive: no flash, no jump.
    placeholderData: keepPreviousData,
  });
}

/** One paged query per status section (ADR 0033 D4); a section not asked stays idle. */
export function useSectionPages(queries: Record<SectionId, SessionQuery | null>) {
  return {
    waiting: useSessionPages(queries.waiting),
    live: useSessionPages(queries.live),
    idle: useSessionPages(queries.idle),
    ended: useSessionPages(queries.ended),
  };
}

/** The live-tile stream of `project` (null: all); Sessions refetches its sections when it reports a change. */
export function tileStreamUrl(project: string | null): string {
  return `/api/v1/live-sessions/stream${project ? `?project=${encodeURIComponent(project)}` : ""}`;
}

/** Sections refetch at most this often on stream changes (AC-234.9). */
export const STREAM_REFETCH_MS = 2_000;

/** A section asked for: collapsed or busy ones are not refetched, only marked to catch up later. */
export interface SectionTarget {
  id: SectionId;
  collapsed: boolean;
  /** A fetch (e.g. Load more) is running: refetching now would cancel it. */
  fetching: boolean;
  refetch: (options: { cancelRefetch: boolean }) => unknown;
}

/**
 * Refetches the open sections on tile-stream changes and when the agent-list poll brings data
 * (`agentsUpdatedAt`), at most once per STREAM_REFETCH_MS on the trailing edge (a burst is one
 * refetch). A tile does not say which section it left, so every open section refetches; a
 * collapsed or fetching one refetches once it is open and idle. `onRefetch` gets the sections
 * asked, before they are. The stream keeps no state, so its messages never re-render the screen.
 */
export function useSectionRefresh(
  project: string | null,
  targets: readonly SectionTarget[],
  agentsUpdatedAt: number,
  onRefetch: (ids: SectionId[]) => void,
): void {
  const latest = useRef({ targets, onRefetch });
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  /** Sections a tick skipped, and why: opening one catches up at once, a fetch at the next edge. */
  const missed = useRef(new Map<SectionId, "collapsed" | "fetching">());
  const refetch = (ids: SectionTarget[]) => {
    if (ids.length === 0) return;
    latest.current.onRefetch(ids.map((target) => target.id));
    for (const target of ids) void target.refetch({ cancelRefetch: false });
  };
  const schedule = useRef(() => {
    if (timer.current !== undefined) return;
    timer.current = setTimeout(() => {
      timer.current = undefined;
      const due = latest.current.targets.filter((target) => {
        if (target.collapsed) missed.current.set(target.id, "collapsed");
        else if (target.fetching) missed.current.set(target.id, "fetching");
        else missed.current.delete(target.id);
        return !target.collapsed && !target.fetching;
      });
      refetch(due);
    }, STREAM_REFETCH_MS);
  });
  useEffect(() => {
    latest.current = { targets, onRefetch };
    const idle = targets.filter((target) => !target.collapsed && !target.fetching);
    if (idle.some((target) => missed.current.get(target.id) === "fetching")) schedule.current();
    refetch(
      idle.filter(
        (target) =>
          missed.current.get(target.id) === "collapsed" && missed.current.delete(target.id),
      ),
    );
  });
  // Only a newer answer for the same project's list: a project switch changes the query, not data.
  const seen = useRef({ project, at: agentsUpdatedAt });
  useEffect(() => {
    const last = seen.current;
    if (last.project === project && last.at !== 0 && agentsUpdatedAt > last.at) {
      schedule.current();
    }
    seen.current = { project, at: agentsUpdatedAt };
  }, [project, agentsUpdatedAt]);
  useEffect(() => {
    const changed = () => {
      schedule.current();
    };
    const close = openStream(
      tileStreamUrl(project),
      { "tile.upsert": changed, "tile.remove": changed, reset: changed },
      () => undefined,
    );
    return () => {
      close();
      clearTimeout(timer.current);
      timer.current = undefined;
    };
  }, [project]);
}

/** The registered projects, for the Project facet. */
export function useProjects() {
  return useApi("/api/v1/projects");
}

/** Sessions' screen read (ADR 0056): the sections' first pages and what the inbox reads beside. */
export const SESSIONS_READ = "/api/v1/screens/sessions";

/** The section query fields the read answers for: its scope, sort and status, Finished's start. */
const READ_FIELDS: ReadonlySet<string> = new Set(["project", "sort", "status", "from"]);

/** Whether the sessions read answers every section `queries` asks: no filter is set but the
 * period, the sort and the status tab. */
export function readCovers(queries: SectionQueries): boolean {
  return Object.values(queries).every(
    (query) => query !== null && Object.keys(query).every((field) => READ_FIELDS.has(field)),
  );
}

/** The sessions read of the view `queries` describe: the scope, the sort, Finished's start. */
export function sessionsReadParams(
  queries: SectionQueries,
  scope: string | null,
): ApiParams<typeof SESSIONS_READ> {
  const { sort, from } = queries.ended ?? {};
  return { query: { project: scope, ...(sort ? { sort } : {}), ...(from ? { from } : {}) } };
}

/**
 * The sessions read's parts, each under the key its region's query reads: the sections' first
 * pages, every project's card, every project's features (as the inbox's ticket names read them)
 * and, when the read carries them, `scope`'s agent sessions and whether this machine can drive
 * sessions. A `null` agent part (no access, or `claude` still being checked) is not written, so
 * its query reads its route once the read has answered.
 */
export function sessionsSeeds(
  queries: SectionQueries,
  scope: string | null,
  read: SessionsView,
): ScreenReadSeed[] {
  const sections = (Object.keys(queries) as SectionId[]).flatMap((id): ScreenReadSeed[] => {
    const query = queries[id];
    return query === null
      ? []
      : [[sessionPagesKey(query), { pages: [read[id]], pageParams: [null] }]];
  });
  // Only a null part is left out: the answer that names the covered keys has no parts at all.
  const agentParts: ScreenReadSeed[] = [];
  if (read.agent_sessions !== null) {
    agentParts.push([apiKey(AGENT_SESSIONS, agentSessionsParams(scope)), read.agent_sessions]);
  }
  if (read.capabilities !== null) {
    agentParts.push([apiKey("/api/v1/agent-sessions/capabilities"), read.capabilities]);
  }
  return [
    ...sections,
    [apiKey("/api/v1/projects"), read.projects],
    [apiKey("/api/v1/features", { query: { project: null } }), read.features],
    ...agentParts,
  ];
}

/* ---------- Sessions hub web drives (AGH-165) ---------- */

export type AgentSession = components["schemas"]["AgentSession"];
export type CreateAgentSession = components["schemas"]["CreateAgentSession"];
export type CloudSession = components["schemas"]["CloudSession"];

/** While a listed session is live, the list refreshes this often (statuses, waiting). */
export const AGENT_LIST_REFRESH_MS = 5_000;

const live = (s: AgentSession) => s.status !== "ended" && s.status !== "failed";

const AGENT_SESSIONS = "/api/v1/agent-sessions";
const agentSessionsParams = (project: string | null): ApiParams<typeof AGENT_SESSIONS> => ({
  query: project ? { project } : {},
});

/** The agent sessions of `project` (null: every project), newest first. */
export function useAgentSessions(project: string | null) {
  return useApi(AGENT_SESSIONS, agentSessionsParams(project), {
    retry: false,
    refetchInterval: (query) =>
      (query.state.data?.items ?? []).some(live) ? AGENT_LIST_REFRESH_MS : false,
  });
}

/** Whether this machine can drive sessions, and why not. */
export function useAgentCapabilities() {
  return useApi("/api/v1/agent-sessions/capabilities", undefined, {
    staleTime: 60_000,
    retry: false,
  });
}

/** The folders a session of `project` may start in (D6). */
export function useWorkdirs(project: string | null, enabled: boolean) {
  return useApi(
    "/api/v1/agent-sessions/workdirs",
    { query: { project: project ?? "" } },
    { enabled: enabled && project !== null, retry: false },
  );
}

/** What a screen needs to start a Claude session in a project's hub folder. */
export interface HubSessionStart {
  /** The hub folder's workdir id, or null while unknown or when the project has none. */
  hubWorkdirId: string | null;
  /** Why this machine cannot drive sessions at all, or null. */
  unavailable: Unavailable | null;
  /** Why a start cannot happen right now (unavailable, still checking, no hub), or null. */
  reason: string | null;
}

/**
 * Whether a session can start in `project`'s hub folder, and where: the capability check, then the
 * hub workdir, each with the sentence a disabled control shows while it is not ready.
 */
export function useHubSessionStart(project: string): HubSessionStart {
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const canDrive = capabilities.data !== undefined && unavailable === null;
  const workdirs = useWorkdirs(project, canDrive);
  const hub = workdirs.data?.items.find((w) => w.kind === "hub") ?? null;
  const reason = unavailable
    ? `${unavailable.title}.`
    : !canDrive
      ? "Checking whether this machine can drive Claude…"
      : workdirs.isPending
        ? "Looking for the hub folder…"
        : hub === null
          ? `Project ${project} has no hub folder to work in.`
          : null;
  return { hubWorkdirId: hub?.workdir_id ?? null, unavailable, reason };
}

/** The workdir ids the served checkout has as a repo or a worktree (E6), or null outside `make dev`. */
function useServedIds(): ReadonlySet<string> | null {
  const root = servedCheckout();
  const [ids, setIds] = useState<ReadonlySet<string> | null>(null);
  useEffect(() => {
    if (root === null) return;
    // No ids is the honest fallback when they cannot be derived (no crypto.subtle).
    Promise.all([derivedWorkdirId("repo", root), derivedWorkdirId("worktree", root)])
      .then((derived) => {
        setIds(new Set(derived));
      })
      .catch(() => undefined);
  }, [root]);
  return ids;
}

/**
 * Under `make dev`, `make live` or `make playground`, the registered project that lists the served
 * checkout as a folder, and that folder's id, so a session started from the dev app (a shake or New
 * session) edits what the dev server shows; both null otherwise.
 */
export function useServedFolder(
  projects: readonly string[],
  canDrive: boolean,
): { project: string | null; workdirId: string | null } {
  const ids = useServedIds();
  const listings = useQueries({
    queries: projects.map((project) => ({
      ...apiQuery("/api/v1/agent-sessions/workdirs", { query: { project } }),
      enabled: canDrive && ids !== null,
      retry: false,
    })),
  });
  if (ids !== null) {
    for (const [at, listing] of listings.entries()) {
      const folder = listing.data?.items.find((w) => ids.has(w.workdir_id));
      if (folder) return { project: projects[at] ?? null, workdirId: folder.workdir_id };
    }
  }
  return { project: null, workdirId: null };
}

/** The cloud starts of `project`, newest first. */
export function useCloudSessions(project: string | null, enabled: boolean) {
  return useApi(
    "/api/v1/agent-sessions/cloud",
    { query: { project: project ?? "" } },
    { enabled: enabled && project !== null, retry: false },
  );
}

/**
 * `POST /agent-sessions`; the caller navigates to the new session's chat. `release` drops the mutation
 * (its body, a base64 screenshot included) from the cache as soon as its dialog unmounts (AGH-260).
 */
export function useCreateAgentSession({ release = false }: { release?: boolean } = {}) {
  const queryClient = useQueryClient();
  return useMutation<AgentSession, ApiProblem, CreateAgentSession>({
    mutationFn: (body) => apiPost("/api/v1/agent-sessions", body),
    ...(release ? { gcTime: 0 } : {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiKey("/api/v1/agent-sessions") });
    },
  });
}
