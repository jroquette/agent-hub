import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";

import { Banner, Button, CopyButton, Toast } from "../../components";
import { useDiscuss } from "../../shell/discuss";
import type { SavedState } from "./environments";

const TOAST_MS = 4000;

/**
 * The feedback after a write on a screen that edits environments (Hub configuration,
 * Environments): a toast with what was done, and, once hub.json changed, a notice that stays
 * until dismissed, since that change is not committed. A setup flow hands its result over in the
 * location's state; it is read once and cleared, so a reload or Back does not show it again.
 */
export function useSaveNotices() {
  const location = useLocation();
  const navigate = useNavigate();
  const handed = location.state as SavedState | null;
  const [saved, setSaved] = useState<string | null>(handed?.saved ?? null);
  const [teamChanged, setTeamChanged] = useState(handed?.team ?? false);
  // The next steps of each write since the notice last opened (a repo added or removed).
  const [lines, setLines] = useState<readonly string[]>([]);

  useEffect(() => {
    if (handed)
      void navigate(`${location.pathname}${location.hash}`, { replace: true, state: null });
  }, [handed, location.pathname, location.hash, navigate]);
  useEffect(() => {
    if (saved === null) return;
    const timer = setTimeout(() => {
      setSaved(null);
    }, TOAST_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [saved]);

  return {
    saved,
    teamChanged,
    /** The notice's next-step lines, one set per write that has some. */
    lines,
    /** A write's words, whether it changed hub.json, and its next steps for the notice. */
    onSaved: (message: string, team = false, next: readonly string[] = []) => {
      setSaved(message);
      if (team) setTeamChanged(true);
      if (next.length > 0) setLines((current) => [...current, ...next]);
    },
    dismissTeamChanged: () => {
      setTeamChanged(false);
      setLines([]);
    },
  };
}

/** The toast of the screen's last write. */
export function SavedToast({ message }: { message: string | null }) {
  if (message === null) return null;
  return (
    <div className="ah-config-toast">
      <Toast>{message}</Toast>
    </div>
  );
}

/** hub.json changed from the app and is not committed: sync, review, open a hub PR. */
export function UncommittedNotice({
  blocked,
  onDismiss,
  lines = [],
}: {
  /** Why Claude cannot be asked here, else null. */
  blocked: string | null;
  onDismiss: () => void;
  /** What else to run after the writes, under the sync sentence. */
  lines?: readonly string[] | undefined;
}) {
  const { setOpen, addReference } = useDiscuss();
  return (
    <Banner
      tone="info"
      onDismiss={onDismiss}
      action={
        <span className="ah-row" style={{ gap: 8 }}>
          <CopyButton text="./hub sync" label="Copy ./hub sync" />
          <Button
            size="sm"
            icon="message-square"
            disabled={blocked !== null}
            onClick={() => {
              addReference({
                id: "config:hub.json-environments",
                label: "Uncommitted hub.json",
                source: "hub.json",
                quote:
                  "hub.json has changes made from hub web that are not committed. Run ./hub sync, show me the diff, and open a hub PR after I agree.",
              });
              setOpen(true);
            }}
          >
            Ask Claude to open the hub PR
          </Button>
        </span>
      }
    >
      hub.json has changes that are not committed. Run ./hub sync to update AGENTS.md and
      .claude/settings.json, then review the diff and open a hub PR.
      {lines.length > 0 && (
        <ul className="ah-config-notice-lines">
          {lines.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}
    </Banner>
  );
}
