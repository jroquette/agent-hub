import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { components } from "../../api/schema";
import { apiKey, apiPost, useApi, type ApiProblem } from "../../lib/api";
import { useGlobalStream } from "../../shell/GlobalStream";

export type LearningStatus = components["schemas"]["LearningStatus"];
export type LearningActionResult = components["schemas"]["LearningActionResult"];

/** An accept (to a folder or `.md` path under `brain/`, with the edited note body when there is
 * one) or a reject (with its reason). */
export type Decision =
  | { action: "accept"; target: string; noteBody?: string | undefined }
  | { action: "reject"; reason: string };

/** The learnings of one status, for every hub or the scoped project. */
export function useLearnings(project: string | null, status: LearningStatus) {
  return useApi("/api/v1/learnings", { query: { project, status, limit: 200 } });
}

/** Refetches when the global stream's count of proposed learnings changes (Live). */
export function useLiveLearnings(): void {
  const client = useQueryClient();
  const { counts } = useGlobalStream();
  const proposed = counts?.learnings_proposed;
  const seen = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (proposed === undefined) return;
    if (seen.current !== undefined && seen.current !== proposed) {
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/learnings") });
    }
    seen.current = proposed;
  }, [client, proposed]);
}

/** One learning with its note, suggested target and target choices. */
export function useLearning(id: string) {
  return useApi("/api/v1/learnings/{learning_id}", { path: { learning_id: id } });
}

/** The project's header: its `hub_repo` names where a decision's pull request opens. */
export function useHubRepo(project: string | null): string | null {
  const detail = useApi(
    "/api/v1/projects/{project}",
    { path: { project: project ?? "" } },
    { enabled: project !== null },
  );
  return detail.data?.hub_repo ?? null;
}

/** Accepts or rejects a learning: a JSON POST that opens a hub pull request (AC-201.23, 201.24). */
export function useDecideLearning(id: string) {
  const client = useQueryClient();
  const path = { path: { learning_id: id } };
  return useMutation<LearningActionResult, ApiProblem, Decision>({
    mutationFn: (decision) =>
      decision.action === "accept"
        ? apiPost(
            "/api/v1/learnings/{learning_id}/accept",
            decision.noteBody === undefined
              ? { target: decision.target }
              : { target: decision.target, note_body: decision.noteBody },
            path,
          )
        : apiPost("/api/v1/learnings/{learning_id}/reject", { reason: decision.reason }, path),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/learnings") });
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/learnings/{learning_id}", path) });
    },
  });
}
