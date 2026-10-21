import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiPost, useApi, type ApiProblem } from "../../lib/api";
import type { components } from "../../api/schema";

type Schemas = components["schemas"];
export type ItemKind = Schemas["ItemKind"];
export type ItemWriteResult = Schemas["ItemWriteResult"];

/** What addresses an item (L5): its kind, the folder it comes from, and its name. */
export interface SkillRef {
  kind: ItemKind;
  source: string;
  name: string;
}

/** A project's skills, agents and hooks with 30-day usage (D3); nothing is fetched while
 * `enabled` is false. */
export function useSkillCatalog(project: string, enabled = true) {
  return useApi("/api/v1/projects/{project}/skills", { path: { project } }, { enabled });
}

/** One item's detail by its id `kind/source/name` (D4). */
export function useSkillDetail(project: string, item: SkillRef) {
  return useApi("/api/v1/projects/{project}/skills/{kind}/{source}/{name}", {
    path: { project, kind: item.kind, source: item.source, name: item.name },
  });
}

/** One bundled file's inert text by the id the detail issued; nothing is fetched while
 * `enabled` is false. */
export function useSkillFile(project: string, item: SkillRef, fileId: string, enabled = true) {
  return useApi(
    "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/files/{file_id}",
    {
      path: { project, kind: item.kind, source: item.source, name: item.name, file_id: fileId },
    },
    { enabled },
  );
}

/** The in-app route of an item's detail: `/projects/<project>/skills/<kind>/<source>/<name>`. */
export function skillRoute(project: string, item: SkillRef): string {
  const segments = [project, "skills", item.kind, item.source, item.name];
  return `/projects/${segments.map(encodeURIComponent).join("/")}`;
}

const PUBLISH = "/api/v1/projects/{project}/skills/drafts/{draft_id}/publish";
const TOOLKIT = "/api/v1/projects/{project}/skills";

/** Whether a query key `["api", path, params]` reads the project's Toolkit (catalog, details,
 * files, histories), which a publish may change; a version's content never changes. */
function readsToolkit(project: string, key: readonly unknown[]): boolean {
  const [scope, path, params] = key;
  if (scope !== "api" || typeof path !== "string" || path.includes("{version_id}")) return false;
  const named = (params as { path?: { project?: unknown } } | undefined)?.path?.project;
  return path.startsWith(TOOLKIT) && named === project;
}

/** Publishes a Studio draft on the server (AGH-295, S5): `target` is the item an edit changes,
 * null for a new item (always sent); `confirmManaged` only after the hub.lock warning (S9). */
export function usePublishDraft(project: string, draftId: string) {
  const client = useQueryClient();
  return useMutation<
    ItemWriteResult,
    ApiProblem,
    { target: SkillRef | null; confirmManaged: boolean }
  >({
    mutationFn: ({ target, confirmManaged }) =>
      apiPost(
        PUBLISH,
        {
          target: target && { kind: target.kind, source: target.source, name: target.name },
          confirm_managed: confirmManaged,
        },
        { path: { project, draft_id: draftId } },
      ),
    onSettled: () => {
      // A publish (or a failure that still landed it) changes the catalog, the item and its
      // history; a refusal changes nothing, and a read again costs little.
      void client.invalidateQueries({
        predicate: (query) => readsToolkit(project, query.queryKey),
      });
    },
  });
}
