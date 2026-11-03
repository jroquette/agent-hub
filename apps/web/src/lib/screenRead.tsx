/**
 * The screen-read provider (ADR 0056): a screen's read, fetched once per visit, whose parts are
 * written under the query keys of the resources the screen's components read.
 *
 * RED stub for AGH-623 (plan SCREEN-1 commit 36): the names the tests use, with no logic yet.
 */
import type { QueryKey } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";

import type { ApiData, ApiParams, GetPath } from "./api";

/** How long the covered queries wait for the screen read before they read their resources. */
export const SCREEN_READ_TIMEOUT_MS = 5_000;

/** A part of a screen read and the resource's query key it is written under. */
export type ScreenReadSeed = readonly [QueryKey, unknown];

export interface ScreenReadProviderProps<P extends GetPath> {
  /** The screen read, under `/api/v1/screens/`. */
  path: P;
  params?: ApiParams<P>;
  /** The parts to write once the read has answered, each under its resource's key. */
  seeds: (read: ApiData<P>) => readonly ScreenReadSeed[];
  /** Off: no read and no key covered, the children still mounted (default on). */
  enabled?: boolean;
  children?: ReactNode;
}

export function ScreenReadProvider<P extends GetPath>({
  path,
}: ScreenReadProviderProps<P>): ReactElement {
  throw new Error(`ScreenReadProvider is not built yet (${path})`);
}
