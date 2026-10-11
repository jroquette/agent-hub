import type { components } from "../../api/schema";
import { useApi } from "../../lib/api";

export type Approval = components["schemas"]["Approval"];
export type ApprovalKind = components["schemas"]["ApprovalKind"];

export function useApprovals(
  project: string | null,
  status: "open" | "decided",
  kind: ApprovalKind | null,
) {
  return useApi("/api/v1/approvals", { query: { project, status, kind, limit: 200 } });
}

export function useApproval(id: string | undefined, placeholder: Approval | undefined) {
  return useApi(
    "/api/v1/approvals/{approval_id}",
    { path: { approval_id: id ?? "" } },
    { enabled: id !== undefined, placeholderData: () => placeholder },
  );
}
