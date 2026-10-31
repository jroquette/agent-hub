/* The ticket page's route, kept apart so the Tickets list and the Project overview link to a
 * ticket without loading the ticket page, whose code loads on demand (AGH-614). */

/** The in-app route of one tracker issue's ticket page. */
export function ticketHref(project: string, issue: string): string {
  return `/tickets/${encodeURIComponent(project)}/${encodeURIComponent(issue)}`;
}
