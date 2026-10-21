import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiPost, useApi, type ApiProblem } from "../../lib/api";
import type { components } from "../../api/schema";
import { draftKind } from "./draft";
import { saveDraft } from "./studioDrafts";

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
const ITEM = "/api/v1/projects/{project}/skills/{kind}/{source}/{name}";
const ITEM_FILE = `${ITEM}/files/{file_id}`;

type KeyParams = { path?: Record<string, unknown> } | undefined;

/** Whether a query key `["api", path, params]` reads the project's Toolkit (catalog, details,
 * files, histories), which a publish may change; a version's content never changes. */
function readsToolkit(project: string, key: readonly unknown[]): boolean {
  const [scope, path, params] = key;
  if (scope !== "api" || typeof path !== "string" || path.includes("{version_id}")) return false;
  return path.startsWith(TOOLKIT) && (params as KeyParams)?.path?.project === project;
}

/** Whether a query key reads the edited item itself (its detail or a bundled file): a rename
 * or a removal makes it 404 under the Studio that edits it. */
function readsItem(project: string, item: SkillRef, key: readonly unknown[]): boolean {
  const [scope, path, params] = key;
  if (scope !== "api" || (path !== ITEM && path !== ITEM_FILE)) return false;
  const named = (params as KeyParams)?.path;
  return (
    named?.project === project &&
    named.kind === item.kind &&
    named.source === item.source &&
    named.name === item.name
  );
}

/** Whether a failed publish spent its draft: already published (A20), or published with its
 * folder kept (`published: true`); either way it can only be discarded. */
export function spentBy(problem: ApiProblem): boolean {
  return problem.code === "draft_already_published" || problem.published;
}

/** Publishes a Studio draft on the server (AGH-295, S5): `target` is the item an edit changes,
 * null for a new item (always sent); `confirmManaged` only after the hub.lock warning (S9).
 * What it did is stored on the draft here, so it is kept when the Studio is left meanwhile. */
export function usePublishDraft(project: string, draftId: string) {
  const client = useQueryClient();
  const kind = draftKind(draftId);
  const store = (patch: { published: true } | { spent: true; spentDetail: string }) => {
    if (kind) saveDraft(draftId, { project, kind }, patch);
  };
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
    onSuccess: () => {
      store({ published: true });
    },
    onError: (problem) => {
      if (spentBy(problem)) store({ spent: true, spentDetail: problem.detail ?? problem.title });
    },
    onSettled: (_result, _problem, { target }) => {
      // A publish (or a failure that still landed it) changes the catalog, the items and their
      // histories. The edited item itself is only marked stale: it may be gone (a rename), and
      // reading it again would 404 under its Studio; the next visit reads it.
      const own = (key: readonly unknown[]) => target !== null && readsItem(project, target, key);
      void client.invalidateQueries({
        predicate: (query) => readsToolkit(project, query.queryKey) && !own(query.queryKey),
      });
      if (target)
        void client.invalidateQueries({
          predicate: (query) => own(query.queryKey),
          refetchType: "none",
        });
    },
  });
}
