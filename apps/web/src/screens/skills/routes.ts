/* The Toolkit's routes, a workflow's page among them, kept apart so the Workflows screen can link
 * here without an import cycle, and the Toolkit can link to a workflow without loading the
 * Workflows screen, whose code loads on demand. */

/** Where Toolkit goes with All projects in scope: a project picker (AGH-164). */
export const SKILLS_PICKER = "/knowledge/skills";

/** The in-app route of a project's Toolkit catalog. */
export function skillsHome(project: string): string {
  return `/projects/${encodeURIComponent(project)}/skills`;
}

/** Where a project's new workflow is described, inside its Toolkit. */
export function newWorkflowRoute(project: string): string {
  return `${skillsHome(project)}/workflows/new`;
}

/** A workflow's page, inside its project's Toolkit. */
export function workflowHref(item: { project: string; name: string }): string {
  return `${skillsHome(item.project)}/workflows/${encodeURIComponent(item.name)}`;
}

/** The Toolkit's Workflows tab of a project. */
export function workflowsTab(project: string): string {
  return `${skillsHome(project)}?view=workflows`;
}
