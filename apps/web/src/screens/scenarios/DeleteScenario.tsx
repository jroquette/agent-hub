import { useEffect, useRef, useState } from "react";

import {
  ConfirmDialog,
  CopyButton,
  Icon,
  IconButton,
  MenuItem,
  PathText,
  Popover,
  Toast,
} from "../../components";
import { useDeleteScenario, type ScenarioRef } from "./queries";

/* Delete scenario: the "⋯" menu of a list row and of the scenario's header, the confirm that
 * names the file, and the toast with the command that restores it (spec 23). */

/** The scenario a delete removes: its name, its pack and where its file is in the hub. */
export interface DeleteTarget extends ScenarioRef {
  pack: string;
  path: string;
}

/** The file a scenario loads from: the path the server reads, else the pack's folder. */
export function scenarioPath(item: { pack: string; name: string; path?: string | null }): string {
  return item.path ?? `scenarios/${item.pack}/${item.name}.yaml`;
}

/** What a deleted scenario's toast says, and the command that brings the file back. */
export interface DeletedNotice {
  message: string;
  restore: string | null;
}

const IN_PROGRESS = "A scenario run of it is in progress. Let it end or cancel it first.";

/** A scenario's "⋯" menu (the session menu's shape): Open scenario on a list row, then Delete
 * scenario…, which is off while a scenario run of it is in progress. */
export function ScenarioMenu({
  name,
  openHref,
  inProgress,
  onDelete,
}: {
  name: string;
  openHref?: string | undefined;
  inProgress: boolean;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: PointerEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      wrap.current?.querySelector<HTMLButtonElement>("button")?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open]);
  const label = openHref === undefined ? "Scenario actions" : `Actions for ${name}`;
  return (
    // The menu keeps its clicks and keys: the list row around it opens the scenario.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <span
      ref={wrap}
      className="sc-menu"
      onClick={(event) => {
        event.stopPropagation();
      }}
      onKeyDown={(event) => {
        event.stopPropagation();
      }}
    >
      <IconButton
        icon="ellipsis"
        label={label}
        size="sm"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      />
      <Popover open={open} label={label} style={{ top: 30, right: 0, minWidth: 260 }}>
        {openHref !== undefined && (
          <>
            <MenuItem icon="clipboard-list" href={openHref}>
              Open scenario
            </MenuItem>
            <div className="ah-menu-sep" role="separator" />
          </>
        )}
        {inProgress ? (
          <div className="sc-menu-off">
            <span className="ah-row" style={{ gap: 8 }}>
              <Icon name="trash" />
              Delete scenario…
            </span>
            <span className="ah-small ah-subtle">{IN_PROGRESS}</span>
          </div>
        ) : (
          <MenuItem
            icon="trash"
            danger
            onClick={() => {
              setOpen(false);
              onDelete();
            }}
          >
            Delete scenario…
          </MenuItem>
        )}
      </Popover>
    </span>
  );
}

/** Asks before Delete scenario removes the file: what goes, what stays, how to get it back. A
 * 401 or another refusal keeps it open with the reason; a 404 counts as already gone. */
export function DeleteScenarioDialog({
  target,
  onCancel,
  onDeleted,
}: {
  target: DeleteTarget;
  onCancel: () => void;
  onDeleted: (notice: DeletedNotice) => void;
}) {
  const remove = useDeleteScenario();
  const restore = `git restore ${target.path}`;
  const error = remove.error;
  return (
    <ConfirmDialog
      title={`Delete scenario ${target.name}?`}
      consequences={[
        "Its recorded scenario runs stay.",
        `The actions it calls in actions/${target.pack}/ stay.`,
        <>
          hub web cannot undo this. Until you commit the removal, restore it in the hub with{" "}
          <span className="ah-mono">{restore}</span>.
        </>,
      ]}
      confirmLabel={remove.isPending ? "Deleting…" : "Delete scenario"}
      pending={remove.isPending}
      onCancel={onCancel}
      onConfirm={() => {
        remove.mutate(
          { project: target.project, name: target.name },
          {
            onSuccess: (result) => {
              onDeleted(
                result === "gone"
                  ? {
                      message: `${target.name} was already gone from the hub folder.`,
                      restore: null,
                    }
                  : { message: `Deleted scenario ${target.name}.`, restore },
              );
            },
          },
        );
      }}
    >
      <span className="ah-stack" style={{ gap: 8 }}>
        <span>
          This removes <PathText path={target.path} max={64} /> from the {target.project} hub
          folder.
        </span>
        {error && (
          <span style={{ color: "var(--failed)" }} role="alert">
            {error.status === 401
              ? "Deleting is locked in this browser. Open the link hub web printed when it started (it ends with ?token=…) once in this browser."
              : `Could not delete the scenario. ${error.detail ?? error.title} Nothing was deleted.`}
          </span>
        )}
      </span>
    </ConfirmDialog>
  );
}

/** A deleted scenario's toast, bottom right, with the command that restores the file (the
 * screen that shows it hides it after a while). */
export function DeletedToast({ notice }: { notice: DeletedNotice | null }) {
  if (notice === null) return null;
  return (
    <div className="sc-toast">
      <Toast
        action={
          notice.restore === null ? undefined : (
            <CopyButton text={notice.restore} label="Copy restore command" />
          )
        }
      >
        {notice.message}
      </Toast>
    </div>
  );
}
