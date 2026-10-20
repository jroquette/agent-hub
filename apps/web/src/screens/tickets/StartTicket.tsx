import { useState } from "react";

import { Button } from "../../components";
import { useApi } from "../../lib/api";
import { useDriving } from "../sessions-list/DrivenControls";
import { StartSessionDialog } from "../sessions-list/StartSessionDialog";

/** The skill a ticket starts with; the dialog's skill buttons switch it to another. */
export const TICKET_PROMPT = "/fix ";

const NOTE =
  "Write the tracker issue after the skill, e.g. /fix ACME-12. Pick another skill below for a refactor, an upgrade, an incident or a triage. The session starts in the hub folder, and the skill makes the issue's worktree.";

/**
 * "Start ticket": the New session dialog opened on the project's hub folder with `/fix ` in the
 * prompt, so a single-ticket skill starts on an issue from here. Shown only where sessions can be
 * driven, as New session is.
 */
export function StartTicketControl({ scope }: { scope: string | null }) {
  const [open, setOpen] = useState(false);
  const projects = (useApi("/api/v1/projects").data?.items ?? []).map((item) => item.name);
  const { caps, canDrive, project, choices, workdirs } = useDriving(scope, projects);
  const folders = workdirs.data?.items;
  if (!canDrive || !caps || project === null || !folders) return null;
  const hub = folders.find((folder) => folder.kind === "hub");
  return (
    <>
      <Button
        variant="primary"
        size="sm"
        icon="plus"
        onClick={() => {
          setOpen(true);
        }}
      >
        Start ticket
      </Button>
      {open && (
        <StartSessionDialog
          title="Start ticket"
          project={project}
          projects={choices}
          workdirs={folders}
          capabilities={caps}
          initialWorkdirId={hub?.workdir_id}
          initialPrompt={TICKET_PROMPT}
          note={NOTE}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}
