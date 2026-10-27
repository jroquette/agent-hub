import { useContext, useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Banner, Button, ConfirmDialog, Tooltip } from "../../components";
import { useDiscuss } from "../../shell/discuss";
import { AskBlocked, SectionForm } from "./parts";
import {
  EMPTY_REPO,
  REPO_FIELDS,
  addBody,
  blockedReason,
  duplicateOf,
  postRepoEdit,
  repoRefusalOf,
  setBody,
  startValues,
} from "./repos";
import type { RepoConfigView, RepoField, RepoRefusal, RepoValues } from "./repos";
import type { HubConfigView } from "./environments";

/* The Repositories section's writes (24-hub-config-repos.md): the repo form of add and change,
   and the remove confirmation. Each sends one POST …/config/repos and shows a refusal line by
   line, as the API sends it. */

interface FieldLook {
  label: string;
  help: (view: HubConfigView) => string;
  required?: boolean;
  placeholder?: string;
  suffix?: string;
}

const LOOK: Record<RepoField, FieldLook> = {
  dir: {
    label: "Folder",
    help: () =>
      "The repo's folder next to the hub, ../{folder}. Letters, digits and _, joined by . or -.",
    required: true,
    placeholder: "demo-web",
  },
  github: { label: "GitHub repo", help: () => "owner/name, e.g. acme/demo-web.", required: true },
  check: {
    label: "Full check",
    help: () => "The command agents run before a PR, e.g. make check.",
    required: true,
  },
  check_fast: {
    label: "Fast check (optional)",
    help: () =>
      "The command the Stop hook runs while agents work, e.g. make check-fast. Empty: no fast check; agents stop without one.",
  },
  check_fast_timeout: {
    label: "Fast check timeout (optional)",
    help: () => "Seconds the Stop hook gives the fast check, 1 to 160. Empty: 150 (built-in).",
    suffix: "seconds",
  },
  role: {
    label: "Role (optional)",
    help: () => "A word for what the repo is, e.g. api or web. Empty: app.",
  },
  default_branch: {
    label: "Default branch (optional)",
    help: (view) =>
      view.default_branch.value
        ? `The base of its worktrees and PRs. Empty: the project's ${view.default_branch.value}.`
        : "The base of its worktrees and PRs. Empty: the project's default branch.",
  },
};

/** The refusal block: the problem's title, then each line as sent. */
function RefusalBlock({ refusal, idPrefix }: { refusal: RepoRefusal; idPrefix: string }) {
  return (
    <Banner tone="error" boxed>
      {refusal.title && <strong>{refusal.title}</strong>}
      <ul className="ah-config-refusal">
        {refusal.lines.map((line, index) => (
          <li key={index} id={`${idPrefix}-problem-${String(index)}`}>
            {line.message}
          </li>
        ))}
      </ul>
    </Banner>
  );
}

export interface RepoFormProps {
  view: HubConfigView;
  /** The repo changed, as the config shows it now; null: a new repo. */
  repo: RepoConfigView | null;
  /** The id of the heading that names the form. */
  labelledBy: string;
  onCancel: () => void;
  /** After a 200: the repo's folder. */
  onSaved: (dir: string) => void;
}

/** Add or change one repo: the fields of hub.json's repo entry, Cancel and the save verb. */
export function RepoForm({ view, repo, labelledBy, onCancel, onSaved }: RepoFormProps) {
  const client = useQueryClient();
  const id = useId();
  const start = repo === null ? null : startValues(repo);
  const [values, setValues] = useState<RepoValues>(() => start ?? EMPTY_REPO);
  const [touched, setTouched] = useState<ReadonlySet<RepoField>>(() => new Set());
  const [pending, setPending] = useState(false);
  const [refusal, setRefusal] = useState<RepoRefusal | null>(null);
  const first = useRef<HTMLInputElement>(null);

  // The config reloaded (hub.json changed on disk): untouched fields take the file's values, so
  // Save never undoes a change someone else made to another key. Adjusted while rendering, as
  // React advises for state that follows a prop.
  const startKey = start === null ? "" : JSON.stringify(start);
  const [seenStart, setSeenStart] = useState(startKey);
  if (start !== null && startKey !== seenStart) {
    setSeenStart(startKey);
    const next = { ...values };
    for (const field of REPO_FIELDS) if (!touched.has(field)) next[field] = start[field];
    setValues(next);
  }

  useEffect(() => {
    first.current?.focus();
    const form = first.current?.closest("form");
    if (repo === null && form && "scrollIntoView" in form)
      form.scrollIntoView({ block: "nearest" });
    // On open only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const duplicate = repo === null ? duplicateOf(values.dir, view.repos) : null;
  const reason = blockedReason(values, start);
  const fields = REPO_FIELDS.filter((field) => repo === null || field !== "dir");

  const submit = () => {
    if (reason !== null || pending) return;
    const body = start === null ? addBody(values) : setBody(start, values);
    if (body === null) return;
    setPending(true);
    setRefusal(null);
    postRepoEdit(client, view.project, body)
      .then(() => {
        setPending(false);
        onSaved(body.dir);
      })
      .catch((error: unknown) => {
        setPending(false);
        setRefusal(repoRefusalOf(error));
      });
  };

  const problemIds = (field: RepoField): string[] =>
    (refusal?.lines ?? []).flatMap((line, index) =>
      line.field === field ? [`${id}-problem-${String(index)}`] : [],
    );

  return (
    <SectionForm
      className="ah-repo-form"
      labelledBy={labelledBy}
      saveLabel={repo === null ? "Add repo" : "Save repo"}
      pendingLabel={repo === null ? "Adding…" : "Saving…"}
      pending={pending}
      canSave={reason === null}
      reason={reason}
      refusal={refusal && <RefusalBlock refusal={refusal} idPrefix={id} />}
      onCancel={onCancel}
      onSave={submit}
    >
      <div className="ah-stack ah-small ah-muted" style={{ gap: 2 }}>
        {repo === null ? (
          <span>
            Saved to hub.json, the team&apos;s file. hub web does not clone the repo: run ./hub
            setup after.
          </span>
        ) : (
          <>
            <span>
              Saved to hub.json, the team&apos;s file. It stays uncommitted until you open a hub PR.
            </span>
            <span>The folder cannot change here: remove the repo and add it again.</span>
          </>
        )}
      </div>
      {fields.map((field, index) => {
        const look = LOOK[field];
        const inputId = `${id}-${field}`;
        const helpId = `${inputId}-help`;
        const dupId = `${inputId}-duplicate`;
        const named = problemIds(field);
        const flagged = field === "dir" && duplicate !== null;
        const describedBy = [helpId, ...(flagged ? [dupId] : []), ...named].join(" ");
        return (
          <div key={field} className="ah-stack ah-repo-field">
            <label htmlFor={inputId} className="ah-config-field-label">
              {look.label}
            </label>
            <span className="ah-repo-input">
              <input
                ref={index === 0 ? first : undefined}
                id={inputId}
                className="ah-input ah-mono"
                value={values[field]}
                maxLength={200}
                placeholder={look.placeholder}
                inputMode={field === "check_fast_timeout" ? "numeric" : undefined}
                aria-required={look.required ? true : undefined}
                aria-invalid={named.length > 0 || flagged ? true : undefined}
                aria-describedby={describedBy}
                disabled={pending}
                onChange={(event) => {
                  setValues({ ...values, [field]: event.target.value });
                  if (!touched.has(field)) setTouched(new Set([...touched, field]));
                }}
              />
              {look.suffix && <span className="ah-small ah-muted">{look.suffix}</span>}
            </span>
            <span id={helpId} className="ah-small ah-muted">
              {look.help(view)}
            </span>
            {flagged && (
              <span id={dupId} className="ah-small ah-config-error">
                Already a repo here: {duplicate} (folders are compared ignoring case).
              </span>
            )}
          </div>
        );
      })}
      {repo !== null && (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          Branch, commit title and PR title patterns: ask Claude to change them.
        </p>
      )}
    </SectionForm>
  );
}

/** The services that go with a repo removed from hub.json: the ones it declares there. */
function teamServices(view: HubConfigView, dir: string): string[] {
  return view.environments.services
    .filter(
      (service) =>
        service.repo === dir &&
        (service.endpoints.length === 0 ||
          service.endpoints.some((endpoint) => endpoint.source !== "hub.local.json")),
    )
    .map((service) => service.name);
}

export interface RepoRemovalProps {
  view: HubConfigView;
  dir: string;
  onCancel: () => void;
  onRemoved: (dir: string) => void;
}

/** Remove one repo: what goes with it and what stays; a refusal lists each reference. */
export function RepoRemoval({ view, dir, onCancel, onRemoved }: RepoRemovalProps) {
  const client = useQueryClient();
  const { setOpen, addReference } = useDiscuss();
  const blocked = useContext(AskBlocked);
  const id = useId();
  const [pending, setPending] = useState(false);
  const [refusal, setRefusal] = useState<RepoRefusal | null>(null);
  const services = teamServices(view, dir);

  const consequences: ReactNode[] = [
    `Agents stop working in ${dir} after ./hub sync.`,
    ...(services.length === 1 ? [`Its service goes with it: ${services.join(", ")}.`] : []),
    ...(services.length > 1
      ? [`Its ${String(services.length)} services go with it: ${services.join(", ")}.`]
      : []),
    `../${dir} and its worktrees stay on disk.`,
    "hub.json changes; run ./hub sync and open a hub PR.",
  ];

  return (
    <ConfirmDialog
      title={`Remove repo ${dir}?`}
      confirmLabel={pending ? "Removing…" : "Remove repo"}
      pending={pending}
      consequences={consequences}
      onCancel={onCancel}
      onConfirm={() => {
        setPending(true);
        setRefusal(null);
        postRepoEdit(client, view.project, { op: "remove_repo", dir })
          .then(() => {
            setPending(false);
            onRemoved(dir);
          })
          .catch((error: unknown) => {
            setPending(false);
            setRefusal(repoRefusalOf(error));
          });
      }}
    >
      {refusal && (
        <div className="ah-stack ah-repo-removal-refusal">
          <RefusalBlock refusal={refusal} idPrefix={id} />
          <Tooltip label={blocked ?? undefined}>
            <Button
              icon="message-square"
              disabled={blocked !== null}
              onClick={() => {
                addReference({
                  id: `config:repos:remove:${dir}`,
                  label: `References to ${dir}`,
                  source: "hub.json",
                  quote: refusal.lines.map((line) => line.message).join("\n"),
                });
                setOpen(true);
                onCancel();
              }}
            >
              Ask Claude to drop these
            </Button>
          </Tooltip>
        </div>
      )}
    </ConfirmDialog>
  );
}
