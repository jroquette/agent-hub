import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { apiGet, apiKey, apiPost, type ApiProblem } from "../../lib/api";
import type { SkillRef } from "../skills/queries";

type Schemas = components["schemas"];
export type ItemVersion = Schemas["ItemVersionView"];
export type ItemVersionPage = Schemas["ItemVersionPage"];
export type ItemVersionContent = Schemas["ItemVersionContent"];
export type VersionFile = Schemas["VersionFileView"];
export type ItemWriteResult = Schemas["ItemWriteResult"];

/** Whose history the panel shows: a Toolkit item, or a hub workflow (AGH-295). */
export type HistoryTarget =
  | { kind: "item"; project: string; item: SkillRef }
  | { kind: "workflow"; project: string; name: string };

const SKILL_VERSIONS = "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/versions";
const SKILL_VERSION =
  "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/versions/{version_id}";
const SKILL_RESTORE =
  "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/versions/{version_id}/restore";
const WORKFLOW_VERSIONS = "/api/v1/workflows/{project}/{name}/versions";
const WORKFLOW_VERSION = "/api/v1/workflows/{project}/{name}/versions/{version_id}";
const WORKFLOW_RESTORE = "/api/v1/workflows/{project}/{name}/versions/{version_id}/restore";

function skillPath(project: string, item: SkillRef) {
  return { project, kind: item.kind, source: item.source, name: item.name };
}

/** The list's query key, under the versions path, so a restore invalidates every page. */
function versionsKey(target: HistoryTarget) {
  return target.kind === "item"
    ? apiKey(SKILL_VERSIONS, { path: skillPath(target.project, target.item) })
    : apiKey(WORKFLOW_VERSIONS, { path: { project: target.project, name: target.name } });
}

/** Every version of the target's unit, newest first, a page at a time; idle while `enabled` is false. */
export function useItemVersions(target: HistoryTarget, enabled = true) {
  return useInfiniteQuery<
    ItemVersionPage,
    ApiProblem,
    { pages: ItemVersionPage[] },
    readonly unknown[],
    string | null
  >({
    queryKey: [...versionsKey(target), "pages"],
    initialPageParam: null,
    queryFn: ({ pageParam, signal }) =>
      target.kind === "item"
        ? apiGet(
            SKILL_VERSIONS,
            { path: skillPath(target.project, target.item), query: { cursor: pageParam } },
            signal,
          )
        : apiGet(
            WORKFLOW_VERSIONS,
            { path: { project: target.project, name: target.name }, query: { cursor: pageParam } },
            signal,
          ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled,
  });
}

/** One version's content (immutable, so never refetched); nothing is fetched while `id` is null. */
export function useItemVersion(target: HistoryTarget, id: string | null) {
  const versionId = id ?? "";
  const skill = target.kind === "item" ? skillPath(target.project, target.item) : null;
  const workflow = { project: target.project, name: target.kind === "workflow" ? target.name : "" };
  return useQuery<ItemVersionContent, ApiProblem>({
    queryKey: skill
      ? apiKey(SKILL_VERSION, { path: { ...skill, version_id: versionId } })
      : apiKey(WORKFLOW_VERSION, { path: { ...workflow, version_id: versionId } }),
    queryFn: ({ signal }) =>
      skill
        ? apiGet(SKILL_VERSION, { path: { ...skill, version_id: versionId } }, signal)
        : apiGet(WORKFLOW_VERSION, { path: { ...workflow, version_id: versionId } }, signal),
    enabled: id !== null,
    staleTime: Infinity,
  });
}

/** Restores a version (S7): `confirmManaged` is sent true only after the hub.lock warning (S9). */
export function useRestoreVersion(target: HistoryTarget) {
  const client = useQueryClient();
  return useMutation<ItemWriteResult, ApiProblem, { versionId: string; confirmManaged: boolean }>({
    mutationFn: ({ versionId, confirmManaged }) => {
      const body = { confirm_managed: confirmManaged };
      return target.kind === "item"
        ? apiPost(SKILL_RESTORE, body, {
            path: { ...skillPath(target.project, target.item), version_id: versionId },
          })
        : apiPost(WORKFLOW_RESTORE, body, {
            path: { project: target.project, name: target.name, version_id: versionId },
          });
    },
    onSettled: () => {
      // The restore (or the external version recorded before a refusal) changes the list, and
      // a written unit changes what the detail and the catalog read.
      void client.invalidateQueries({ queryKey: versionsKey(target) });
      if (target.kind === "item") {
        void client.invalidateQueries({
          queryKey: apiKey("/api/v1/projects/{project}/skills/{kind}/{source}/{name}", {
            path: skillPath(target.project, target.item),
          }),
        });
        void client.invalidateQueries({
          queryKey: apiKey("/api/v1/projects/{project}/skills", {
            path: { project: target.project },
          }),
        });
      } else {
        void client.invalidateQueries({
          queryKey: apiKey("/api/v1/workflows/{project}/{name}", {
            path: { project: target.project, name: target.name },
          }),
        });
      }
    },
  });
}
