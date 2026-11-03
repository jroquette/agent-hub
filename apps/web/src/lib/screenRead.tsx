/**
 * The screen-read provider (ADR 0056): a screen's read, fetched once per visit, whose parts are
 * written under the query keys of the resources the screen's components read, so those
 * components stay as they are.
 *
 * While the read is on its way, a query of a key it covers sends no request: `useApi` waits for
 * the read (`ScreenReadContext`) and takes the part written under its key. When the read fails,
 * does not answer within `SCREEN_READ_TIMEOUT_MS` or is switched off, each such query reads its
 * resource route as before, so a failure stays in its region. A part is written only from this
 * visit's read, and never over an entry updated after that read started.
 */
import { hashKey, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { useContext, useEffect, useState, type ReactElement, type ReactNode } from "react";

import {
  apiGet,
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
   * covers: it picks each part by name. */
  seeds: Seeds<P>;
  /** Off: no read and no key covered, the children still mounted (default on). A provider off
   * when its visit begins covers nothing for that visit, even once turned on. */
  enabled?: boolean;
  children?: ReactNode;
}

export function ScreenReadProvider<P extends GetPath>({
  path,
  params,
  seeds,
  enabled = true,
  children,
}: ScreenReadProviderProps<P>): ReactElement {
  const client = useQueryClient();
  const outer = useContext(ScreenReadContext);
  const [visit] = useState(() =>
    enabled ? new ScreenVisit(client, { path, params, seeds }, outer) : null,
  );
  useEffect(() => visit?.read(), [visit]);
  useEffect(() => {
    if (!enabled) visit?.release();
  }, [visit, enabled]);
  return <ScreenReadContext.Provider value={visit ?? outer}>{children}</ScreenReadContext.Provider>;
}

interface ScreenRequest<P extends GetPath> {
  path: P;
  params: ApiParams<P> | undefined;
  seeds: Seeds<P>;
}

/** One visit's screen read: the keys it covers and the queries waiting for its answer. */
class ScreenVisit<P extends GetPath> implements ScreenReadHold {
  readonly #client: QueryClient;
  readonly #request: ScreenRequest<P>;
  readonly #outer: ScreenReadHold | null;
  readonly #covered: ReadonlySet<string>;
  readonly #answer: Promise<boolean>;
  #settle: (seeded: boolean) => void = () => undefined;
  #settled = false;

  constructor(client: QueryClient, request: ScreenRequest<P>, outer: ScreenReadHold | null) {
    this.#client = client;
    this.#request = request;
    this.#outer = outer;
    this.#covered = coveredKeys(request.seeds);
    this.#answer = new Promise((resolve) => {
      this.#settle = resolve;
    });
  }

  hold(key: QueryKey): Promise<unknown> | null {
    if (this.#settled || !this.#covered.has(hashKey(key))) return this.#outer?.hold(key) ?? null;
    return this.#answer.then((seeded) => (seeded ? this.#client.getQueryData(key) : undefined));
  }

  /** Reads the screen once and settles the visit. The cleanup drops that read and leaves the
   * queries waiting, for a read started again (React's strict mode mounts twice). */
  read(): () => void {
    const controller = new AbortController();
    const startedAt = Date.now();
    let current = true;
    const timer = setTimeout(() => {
      controller.abort();
      this.release();
    }, SCREEN_READ_TIMEOUT_MS);
    apiGet(this.#request.path, this.#request.params, controller.signal).then(
      (read) => {
        clearTimeout(timer);
        if (!current || this.#settled) return;
        writeSeeds(this.#client, this.#request.seeds(read), startedAt);
        this.#finish(true);
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
    };
  }

  /** Lets every waiting query read its resource route, and covers nothing from then on. */
  release(): void {
    this.#finish(false);
  }

  #finish(seeded: boolean): void {
    if (this.#settled) return;
    this.#settled = true;
    this.#settle(seeded);
  }
}

/** The keys `seeds` writes: given an answer with no parts, it names the keys alone. */
function coveredKeys<P extends GetPath>(seeds: Seeds<P>): ReadonlySet<string> {
  const noParts = new Proxy({}, { get: () => undefined }) as ApiData<P>;
  return new Set(seeds(noParts).map(([key]) => hashKey(key)));
}

/** Writes each part under its key, unless that key holds data updated after the read started. */
function writeSeeds(client: QueryClient, seeds: readonly ScreenReadSeed[], startedAt: number) {
  for (const [key, data] of seeds) {
    if ((client.getQueryState(key)?.dataUpdatedAt ?? 0) > startedAt) continue;
    client.setQueryData(key, data);
  }
}
