import { useApi } from "../../lib/api";
import type { components } from "../../api/schema";

type Schemas = components["schemas"];
export type ItemKind = Schemas["ItemKind"];

/** What addresses an item (L5): its kind, the folder it comes from, and its name. */
export interface SkillRef {
  kind: ItemKind;
  source: string;
  name: string;
}

/** A project's skills, agents and hooks with 30-day usage (D3). */
export function useSkillCatalog(project: string) {
  return useApi("/api/v1/projects/{project}/skills", { path: { project } });
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
