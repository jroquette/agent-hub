import { IconButton, Kbd } from "../components/core";

/** The keyboard map of Phase 2 (spec 01), grouped as the design shows it. */
export const SHORTCUTS: readonly { title: string; rows: readonly [string, string][] }[] = [
  {
    title: "Go to",
    rows: [
      ["Portfolio", "g p"],
      ["Sessions", "g s"],
      ["Workflow runs", "g r"],
      ["Approvals", "g a"],
      ["Command palette", "Ctrl K"],
    ],
  },
  {
    title: "Lists and timelines",
    rows: [
      ["Next / previous", "j k"],
      ["Open", "↵"],
      ["Focus filter", "/"],
      ["Search in session", "Ctrl F"],
      ["Follow live tail", "f"],
      ["Expand / collapse", "o"],
    ],
  },
  {
    title: "Anywhere",
    rows: [
      ["Close panel", "Esc"],
      ["Features", "g f"],
      ["Health", "g h"],
      ["Settings", "g ,"],
      ["Toggle UTC", "t"],
      ["This sheet", "?"],
    ],
  },
  {
    // An agent session's chat (AC-234.29): `/` at the start of the message, the oldest
    // pending request; Ctrl is Cmd on a Mac.
    title: "Chat",
    rows: [
      ["Commands", "/"],
      ["Allow oldest", "Ctrl Alt ↵"],
      ["Deny oldest", "Ctrl Alt ⌫"],
      ["Allow / deny focused", "a d"],
      ["Focus message", "Shift Esc"],
      ["Recall last prompt", "↑"],
      ["Stop (empty box)", "Esc"],
    ],
  },
];

export function ShortcutSheet({ onClose }: { onClose: () => void }) {
  return (
    <div className="ah-scrim" style={{ zIndex: "var(--z-palette)" }}>
      <div
        className="ah-sheet"
        role="dialog"
        aria-modal="true"
        data-shell-layer=""
        aria-label="Keyboard shortcuts"
      >
        <div className="ah-row">
          <h2 className="ah-h3 ah-grow">Keyboard shortcuts</h2>
          <IconButton icon="x" label="Close (Esc)" onClick={onClose} />
        </div>
        <div className="ah-sheet-cols">
          {SHORTCUTS.map((column) => (
            <div key={column.title}>
              <div className="ah-overline" style={{ marginBottom: 6 }}>
                {column.title}
              </div>
              {column.rows.map(([label, keys]) => (
                <div key={label} className="ah-sheet-row">
                  <span>{label}</span>
                  <span className="ah-row" style={{ gap: 3 }}>
                    {keys.split(" ").map((key, i) => (
                      <Kbd key={i}>{key}</Kbd>
                    ))}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
