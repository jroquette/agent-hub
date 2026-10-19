/* What the list view needs of a row beyond its view: the text search reads and where a row opens. */
import { sessionIdentity } from "../../components";
import { rowHref } from "./drivenRows";
import { isDriven, type SectionRow } from "./sections";
import { waitingLink } from "./tiles";

/** A row whose session waits for the owner. */
function isWaiting(row: SectionRow): boolean {
  return isDriven(row) ? row.status === "waiting_permission" : row.status === "waiting";
}

/** The searchable text of a row: name, issue, repo, branch, folder. */
export function searchText(row: SectionRow): string {
  if (isDriven(row)) return [row.title, row.workdir_label, row.project].join(" ");
  const { title, detail } = sessionIdentity(row);
  return [title, detail, row.label?.issue, row.issue, row.repo, row.label?.branch, row.project]
    .filter(Boolean)
    .join(" ");
}

/** Lower-case, accents stripped, so "sessoes" finds "sessões". */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Where Enter or `o` takes the owner from a row. */
export function openHref(row: SectionRow): string {
  if (isWaiting(row) && !isDriven(row)) return waitingLink(row).href;
  return rowHref(row);
}
