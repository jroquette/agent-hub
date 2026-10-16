import { QueryClient, queryOptions, useQuery } from "@tanstack/react-query";
import type { UseQueryOptions } from "@tanstack/react-query";

import { client } from "../api/client";
import type { components, paths } from "../api/schema";

/* The data layer: typed GET queries over the generated client, and RFC 9457 problems as errors. */

export type ProblemDetails = components["schemas"]["ProblemDetails"];

type Operation<P extends keyof paths, M extends "get" | "post" | "delete"> = NonNullable<
  paths[P][M]
>;

/** API paths with a GET operation. */
export type GetPath = {
  [P in keyof paths]: [NonNullable<paths[P]["get"]>] extends [never] ? never : P;
}[keyof paths];
export type PostPath = {
  [P in keyof paths]: [NonNullable<paths[P]["post"]>] extends [never] ? never : P;
}[keyof paths];
export type DeletePath = {
  [P in keyof paths]: [NonNullable<paths[P]["delete"]>] extends [never] ? never : P;
}[keyof paths];

type JsonOf<R> = R extends { content: { "application/json": infer D } } ? D : undefined;
type SuccessOf<Op> = Op extends { responses: infer Rs }
  ? 200 extends keyof Rs
    ? JsonOf<Rs[200]>
    : 201 extends keyof Rs
      ? JsonOf<Rs[201]>
      : 202 extends keyof Rs
        ? JsonOf<Rs[202]>
        : undefined
  : never;

/** The JSON body a GET of `P` answers with. */
export type ApiData<P extends GetPath> = SuccessOf<Operation<P, "get">>;

type ParamsOf<Op> = Op extends { parameters: infer Prm }
  ? {
      [
        K in keyof Prm as K extends "path" | "query"
          ? [NonNullable<Prm[K]>] extends [never]
            ? never
            : K
          : never
      ]: Prm[K];
    }
  : never;

/** The path and query parameters of a GET of `P`. */
export type ApiParams<P extends GetPath> = ParamsOf<Operation<P, "get">>;

type BodyOf<Op> = Op extends {
  requestBody: { content: { "application/json": infer B } };
}
  ? B
  : undefined;

/** An RFC 9457 problem the API answered with, or a network failure (status 0). */
export class ApiProblem extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string | null;
  readonly type: string;
  readonly instance: string | null;

  constructor(problem: {
    status: number;
    title: string;
    detail?: string | null | undefined;
    type?: string | undefined;
    instance?: string | null | undefined;
  }) {
    super(problem.detail ? `${problem.title}: ${problem.detail}` : problem.title);
    this.name = "ApiProblem";
    this.status = problem.status;
    this.title = problem.title;
    this.detail = problem.detail ?? null;
    this.type = problem.type ?? "about:blank";
    this.instance = problem.instance ?? null;
  }
}

function isProblemBody(body: unknown): body is ProblemDetails {
  return (
    typeof body === "object" &&
    body !== null &&
    typeof (body as { title?: unknown }).title === "string" &&
    typeof (body as { status?: unknown }).status === "number"
  );
}

/** The problem an error stands for; anything unexpected becomes a generic one. */
export function toProblem(error: unknown): ApiProblem {
  if (error instanceof ApiProblem) return error;
  return new ApiProblem({
    status: 0,
    title: "Could not reach agent-hub",
    detail: "The request did not get an answer. Check that hub web is running.",
  });
}

function problemFrom(response: Response, body: unknown): ApiProblem {
  if (isProblemBody(body)) {
    return new ApiProblem({
      status: body.status,
      title: body.title,
      detail: body.detail,
      type: body.type,
      instance: body.instance,
    });
  }
  return new ApiProblem({
    status: response.status,
    title: response.statusText || `HTTP ${String(response.status)}`,
  });
}

interface LooseInit {
  params?: object | undefined;
  body?: unknown;
  signal?: AbortSignal | undefined;
  baseUrl: string;
  fetch: (request: Request) => Promise<Response>;
}
type LooseMethod = (
  path: string,
  init: LooseInit,
) => Promise<{ data?: unknown; error?: unknown; response: Response }>;

async function send(
  method: LooseMethod,
  path: string,
  init: { params?: object | undefined; body?: unknown; signal?: AbortSignal | undefined },
): Promise<unknown> {
  let result: Awaited<ReturnType<LooseMethod>>;
  try {
    result = await method(path, {
      ...init,
      // Same origin only (D25). The base and the fetch are read per call so tests can stub them.
      baseUrl: window.location.origin,
      fetch: (request) => globalThis.fetch(request),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw toProblem(error);
  }
  if (!result.response.ok) throw problemFrom(result.response, result.error);
  return result.data;
}

const GET = client.GET as unknown as LooseMethod;
const POST = client.POST as unknown as LooseMethod;
const DELETE = client.DELETE as unknown as LooseMethod;

/** GETs `path`; resolves with its body or rejects with an ApiProblem. */
export async function apiGet<P extends GetPath>(
  path: P,
  params?: ApiParams<P>,
  signal?: AbortSignal,
): Promise<ApiData<P>> {
  return (await send(GET, path, { params, signal })) as ApiData<P>;
}

/** POSTs a JSON body to `path` (Phase 2 writes: registering a hub). */
export async function apiPost<P extends PostPath>(
  path: P,
  body: BodyOf<Operation<P, "post">>,
  params?: ParamsOf<Operation<P, "post">>,
): Promise<SuccessOf<Operation<P, "post">>> {
  return (await send(POST, path, { params, body })) as SuccessOf<Operation<P, "post">>;
}

/** POSTs an empty JSON object to a command route that takes no body (a run's cancel, resume or
 * abandon): a strict write needs a JSON body (S7), which a cross-site form cannot send. */
export async function apiCommand<P extends PostPath>(
  path: P,
  params: ParamsOf<Operation<P, "post">>,
): Promise<SuccessOf<Operation<P, "post">>> {
  return (await send(POST, path, { params, body: {} })) as SuccessOf<Operation<P, "post">>;
}

/** DELETEs `path` (Phase 2 writes: removing a hub). */
export async function apiDelete<P extends DeletePath>(
  path: P,
  params: ParamsOf<Operation<P, "delete">>,
): Promise<void> {
  await send(DELETE, path, { params });
}

/** The query key of a GET: `["api", path, params]`, so a path prefix invalidates its family. */
export function apiKey<P extends GetPath>(path: P, params?: ApiParams<P>) {
  return ["api", path, params ?? {}] as const;
}

/** Query options of a GET, for useQuery, prefetching or invalidation. */
export function apiQuery<P extends GetPath>(path: P, params?: ApiParams<P>) {
  return queryOptions({
    queryKey: apiKey(path, params),
    queryFn: ({ signal }) => apiGet(path, params, signal),
  });
}

type ExtraOptions<P extends GetPath> = Omit<
  UseQueryOptions<ApiData<P>, ApiProblem, ApiData<P>, ReturnType<typeof apiKey<P>>>,
  "queryKey" | "queryFn"
>;

/** A GET as a TanStack query; `error` is always an ApiProblem. */
export function useApi<P extends GetPath>(
  path: P,
  params?: ApiParams<P>,
  options?: ExtraOptions<P>,
) {
  return useQuery<ApiData<P>, ApiProblem, ApiData<P>, ReturnType<typeof apiKey<P>>>({
    ...options,
    queryKey: apiKey(path, params),
    queryFn: ({ signal }) => apiGet(path, params, signal),
  });
}

/** Retries network failures and 503s (busy database) twice; never a 4xx or a 500. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  const status = error instanceof ApiProblem ? error.status : 0;
  return failureCount < 2 && (status === 0 || status === 503);
}

/** The app's query client: live views refresh through SSE, so data stays fresh for 10 s. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 10_000, retry: shouldRetry, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}
