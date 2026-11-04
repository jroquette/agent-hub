/**
 * The screen-read provider (ADR 0056): a screen's read, fetched once per visit, whose parts are
 * written under the query keys of the resources the screen's components read, so those
 * components stay as they are.
 *
 * While the read is on its way, a query of a key it covers sends no request: `useApi` waits for
 * the read (`ScreenReadContext`) and takes the part written under its key. When the read fails,
 * does not answer within `SCREEN_READ_TIMEOUT_MS`, is switched off or its screen is left, each
 * such query reads its resource route as before, so a failure stays in its region; so does a
 * query whose part the answer leaves out (a `null` part is not written). A part is written only
 * from this visit's read, and never over an entry updated after that read started or over a paged
 * entry holding more pages than the part. A derived part, never written under a resource's key,
 * is read from the answer itself with `useScreenRead`. A provider told to `keep` its answer also
 * writes it whole under the read's own key, which is no resource's key, so a return to the screen
 * can draw a derived part from the last answer (`useKeptScreenRead`) while its own read is on its
 * way.
 */
import {
  hashKey,
  skipToken,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

import {
  apiGet,
  apiKey,
  ScreenReadContext,
  type ApiData,
  type ApiParams,
  type GetPath,
  type ScreenReadHold,
} from "./api";

/** How long the covered queries wait for the screen read before they read their resources. */
export const SCREEN_READ_TIMEOUT_MS = 5_000;

/** A part of a screen read and the resource's query key it is written under. */
export type ScreenReadSeed = readonly [QueryKey, unknown];

type Seeds<P extends GetPath> = (read: ApiData<P>) => readonly ScreenReadSeed[];

export interface ScreenReadProviderProps<P extends GetPath> {
  /** The screen read, under `/api/v1/screens/`. */
  path: P;
  params?: ApiParams<P>;
  /** The parts to write once the read has answered, each under its resource's key. It is also
   * called when the visit begins, with an answer that has no parts, to learn the keys the read
   * covers: it picks each part by name. A part it leaves out of the answer (a `null` one) lets
   * that key's query read its route. */
  seeds: Seeds<P>;
  /** Off: no read and no key covered, the children still mounted (default on). A provider off
   * when its visit begins covers nothing for that visit, even once turned on. */
  enabled?: boolean;
  /** On: an answer this visit uses is also kept in the query cache under the read's own key, for
   * `useKeptScreenRead` on the next visit (default off). */
  keep?: boolean;
  children?: ReactNode;
}

/** This visit's answer, for its derived parts: the read's key, and the read once it has
 * answered (undefined while on its way, null when it failed, timed out or was switched off). */
interface ScreenAnswer {
  key: string;
  read: unknown;
}

const ScreenAnswerContext = createContext<ScreenAnswer | null>(null);

export function ScreenReadProvider<P extends GetPath>({
  path,
  params,
  seeds,
  enabled = true,
  keep = false,
  children,
}: ScreenReadProviderProps<P>): ReactElement {
  const client = useQueryClient();
  const [read, setRead] = useState<unknown>(undefined);
  const [visit] = useState(() =>
    enabled ? new ScreenVisit(client, { path, params, seeds, keep, onAnswer: setRead }) : null,
  );
  useEffect(() => visit?.read(), [visit]);
  useEffect(() => {
    if (!enabled) visit?.release();
  }, [visit, enabled]);
  const answer = useMemo(() => (visit ? { key: visit.key, read } : null), [visit, read]);
  return (
    <ScreenReadContext.Provider value={visit}>
      <ScreenAnswerContext.Provider value={answer}>{children}</ScreenAnswerContext.Provider>
    </ScreenReadContext.Provider>
  );
}

/**
 * The screen read above, for a derived part (one never written under a resource's key, such as the
 * overview's recent sessions): undefined while it is on its way, the read once it has answered,
 * and null when there is none to use, so the caller reads its resource route instead: no visit of
 * this read with these `params` above, or the read failed, did not answer in time or was switched
 * off.
 */
export function useScreenRead<P extends GetPath>(
  path: P,
  params?: ApiParams<P>,
): ApiData<P> | null | undefined {
  const answer = useContext(ScreenAnswerContext);
  if (answer?.key !== hashKey(apiKey(path, params))) return null;
  return answer.read as ApiData<P> | null | undefined;
}

/** A kept answer (undefined when none is kept) and when it was kept (0 when none is). */
export interface KeptScreenRead<P extends GetPath> {
  read: ApiData<P> | undefined;
  updatedAt: number;
}

/**
 * The last answer a provider told to `keep` it used for this read with these `params`, from the
 * query cache under the read's own key. It reads the cache only and never sends a request: a
 * return to the screen draws a derived part from it while `useScreenRead` is still undefined,
 * then from this visit's answer. While mounted it observes that entry with a query that can never
 * fetch (`skipToken`: no invalidation, refetch, focus or reconnect makes it send a request), so
 * the cache lets the kept answer go `gcTime` after the screen is left, as it does every other
 * entry, not `gcTime` after the answer was first kept.
 */
export function useKeptScreenRead<P extends GetPath>(
  path: P,
  params?: ApiParams<P>,
): KeptScreenRead<P> {
  const { data, dataUpdatedAt } = useQuery<ApiData<P>>({
    queryKey: apiKey(path, params),
    queryFn: skipToken,
  });
  return { read: data, updatedAt: dataUpdatedAt };
}

interface ScreenRequest<P extends GetPath> {
  path: P;
  params: ApiParams<P> | undefined;
  seeds: Seeds<P>;
  /** Whether a used answer is also written under the read's own key. */
  keep: boolean;
  /** Told once, when the visit settles: the read, or null when its parts are not to be used. */
  onAnswer: (read: ApiData<P> | null) => void;
}

/** One visit's screen read: the keys it covers and the queries waiting for its answer. */
class ScreenVisit<P extends GetPath> implements ScreenReadHold {
  /** The screen read's own query key, hashed: what `useScreenRead` asks for. */
  readonly key: string;
  readonly #client: QueryClient;
  readonly #request: ScreenRequest<P>;
  readonly #covered: ReadonlySet<string>;
  /** What the answer brought for each key, as the query waiting for that key takes it; nothing
   * when the visit settled without an answer. */
  readonly #answer: Promise<ReadonlyMap<string, unknown>>;
  #settle: (parts: ReadonlyMap<string, unknown>) => void = () => undefined;
  #settled = false;
  /** The reads started and not yet dropped by their cleanup. */
  #reading = 0;

  constructor(client: QueryClient, request: ScreenRequest<P>) {
    this.key = hashKey(apiKey(request.path, request.params));
    this.#client = client;
    this.#request = request;
    this.#covered = coveredKeys(request.seeds);
    this.#answer = new Promise((resolve) => {
      this.#settle = resolve;
    });
  }

  hold(key: QueryKey): Promise<unknown> | null {
    const hashed = hashKey(key);
    if (this.#settled || !this.#covered.has(hashed)) return null;
    return this.#answer.then((parts) => parts.get(hashed));
  }

  /** Reads the screen once and settles the visit. The cleanup drops that read; unless a read
   * starts again at once (React's strict mode mounts twice), the screen is left, and the cleanup
   * settles the visit too, so a waiting query that a component outside the screen also reads
   * gets its route's answer instead of waiting for good. */
  read(): () => void {
    const controller = new AbortController();
    const startedAt = Date.now();
    let current = true;
    this.#reading += 1;
    const timer = setTimeout(() => {
      controller.abort();
      this.release();
    }, SCREEN_READ_TIMEOUT_MS);
    apiGet(this.#request.path, this.#request.params, controller.signal).then(
      (read) => {
        clearTimeout(timer);
        if (!current || this.#settled) return;
        const { path, params, seeds, keep } = this.#request;
        if (keep) this.#client.setQueryData(apiKey(path, params), read);
        this.#finish(read, writeSeeds(this.#client, seeds(read), startedAt));
      },
      () => {
        clearTimeout(timer);
        if (current) this.release();
      },
    );
    return () => {
      current = false;
      clearTimeout(timer);
      controller.abort();
      this.#reading -= 1;
      // Strict mode's second mount reads again before this runs.
      queueMicrotask(() => {
        if (this.#reading === 0) this.release();
      });
    };
  }

  /** Lets every waiting query read its resource route, and covers nothing from then on. */
  release(): void {
    this.#finish(null, new Map());
  }

  #finish(read: ApiData<P> | null, parts: ReadonlyMap<string, unknown>): void {
    if (this.#settled) return;
    this.#settled = true;
    this.#settle(parts);
    this.#request.onAnswer(read);
  }
}

/** The keys `seeds` writes: given an answer with no parts, it names the keys alone. */
function coveredKeys<P extends GetPath>(seeds: Seeds<P>): ReadonlySet<string> {
  const noParts = new Proxy({}, { get: () => undefined }) as ApiData<P>;
  return new Set(seeds(noParts).map(([key]) => hashKey(key)));
}

/**
 * Writes each part under its key and returns, by key, what the query waiting for it takes. A key
 * that holds data updated after the read started keeps it, and its query takes that data. A paged
 * entry holding more pages than its part (pages loaded with Load more) stays whole too: the read's
 * first page beside the kept further pages could list a row twice or miss one. A refetch waiting
 * for it, which reads the further pages again from the first, takes the read's first page.
 */
function writeSeeds(
  client: QueryClient,
  seeds: readonly ScreenReadSeed[],
  startedAt: number,
): ReadonlyMap<string, unknown> {
  const parts = new Map<string, unknown>();
  for (const [key, data] of seeds) {
    const state = client.getQueryState(key);
    let part = data;
    if ((state?.dataUpdatedAt ?? 0) > startedAt) part = state?.data;
    else if (pageCount(state?.data) <= pageCount(data)) part = client.setQueryData(key, data);
    parts.set(hashKey(key), part);
  }
  return parts;
}

/** The pages a paged entry (`{ pages, pageParams }`) holds; 0 for any other data. */
function pageCount(data: unknown): number {
  return (data as { pages?: readonly unknown[] } | null | undefined)?.pages?.length ?? 0;
}
