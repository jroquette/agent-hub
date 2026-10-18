import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { Button, Dialog, SegmentedControl } from "../../components";
import { ApiProblem, apiKey, apiPut } from "../../lib/api";

type HubConfigView = components["schemas"]["HubConfigView"];
type SourcedValue = components["schemas"]["SourcedValue"];

const LOCAL_LISTS = ["blocked_words", "blocked_words_files", "blocked_words_env"] as const;
type ListKey = (typeof LOCAL_LISTS)[number];
const IDENTITY = ["branch_prefix", "author_name", "author_email"] as const;
type IdentityKey = (typeof IDENTITY)[number];

const LABEL: Record<IdentityKey | ListKey, string> = {
  branch_prefix: "Branch prefix",
  author_name: "Author name",
  author_email: "Author email",
  blocked_words: "Blocked words",
  blocked_words_files: "Files checked for blocked words",
  blocked_words_env: "Variables checked for blocked words",
};

const LIST_HELP: Record<ListKey, string> = {
  blocked_words:
    "One per line. Added to the team's list: you can add words, not remove the team's.",
  blocked_words_files: "One glob per line, e.g. config/*.yml. Added to the team's.",
  blocked_words_env:
    "One variable per line; a trailing * is a prefix, e.g. AWS_*. Added to the team's.",
};

const SOURCE_WORD: Record<SourcedValue["source"], string> = {
  team: "hub.json",
  local: "hub.local.json",
  git: "git config",
  derived: "derived from your email",
  default: "the default",
};

const PATTERN_HELP: Record<string, string> = {
  branch_prefix: "Must end with / and use letters, digits, . _ - (e.g. jane/).",
  author_email: "Must be an email address, e.g. jane@example.com.",
};

/** The server's message in the owner's words: a regex pattern means nothing to a reader. */
function plainMessage(key: string, message: string): string {
  if (message.startsWith("String should match pattern")) {
    return PATTERN_HELP[key] ?? "Has a character this field does not accept.";
  }
  return message.charAt(0).toUpperCase() + message.slice(1);
}

function fallbackOf(value: SourcedValue): string {
  if (value.source === "local") {
    return value.team_value
      ? `Empty: ${value.team_value}, from hub.json`
      : "Empty: from git config";
  }
  return value.value
    ? `Empty: ${value.value}, from ${SOURCE_WORD[value.source]}`
    : "Empty: not set";
}

/** The developer's own layer: saved to hub.local.json, never to the team's hub.json. */
export function LocalSettingsDialog({
  view,
  focus,
  onClose,
  onSaved,
}: {
  view: HubConfigView;
  /** The field to focus on open: a row's ✎ names it. */
  focus: string | null;
  onClose: () => void;
  /** Called once the file is written, for the screen's confirmation. */
  onSaved?: (() => void) | undefined;
}) {
  const id = useId();
  const client = useQueryClient();
  const localOf = (value: SourcedValue) => (value.source === "local" ? (value.value ?? "") : "");
  const [identity, setIdentity] = useState<Record<IdentityKey, string>>({
    branch_prefix: localOf(view.branch_prefix),
    author_name: localOf(view.author_name),
    author_email: localOf(view.author_email),
  });
  const [transport, setTransport] = useState<string>(
    view.tracker.transport.source === "local" ? (view.tracker.transport.value ?? "team") : "team",
  );
  const [lists, setLists] = useState<Record<ListKey, string>>({
    blocked_words: view.guard.blocked_words.local.join("\n"),
    blocked_words_files: view.guard.blocked_words_files.local.join("\n"),
    blocked_words_env: view.guard.blocked_words_env.local.join("\n"),
  });
  const [pending, setPending] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);

  const lines = (text: string) =>
    text
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);

  const save = () => {
    setPending(true);
    setErrors({});
    setFailure(null);
    apiPut(
      "/api/v1/projects/{project}/config/local",
      {
        branch_prefix: identity.branch_prefix.trim() || null,
        author_name: identity.author_name.trim() || null,
        author_email: identity.author_email.trim() || null,
        transport: transport === "api" || transport === "mcp" ? transport : null,
        blocked_words: lines(lists.blocked_words),
        blocked_words_files: lines(lists.blocked_words_files),
        blocked_words_env: lines(lists.blocked_words_env),
      },
      { path: { project: view.project } },
    )
      .then((fresh) => {
        client.setQueryData(
          apiKey("/api/v1/projects/{project}/config", { path: { project: view.project } }),
          fresh,
        );
        onClose();
        onSaved?.();
      })
      .catch((error: unknown) => {
        setPending(false);
        if (error instanceof ApiProblem) {
          const found: Record<string, string> = {};
          for (const item of error.errors) {
            const key = item.pointer.split(".")[1]?.split("[")[0] ?? item.pointer;
            const line = /\[(\d+)\]/.exec(item.pointer)?.[1];
            const message = plainMessage(key, item.message);
            found[key] =
              line === undefined ? message : `Line ${String(Number(line) + 1)}: ${message}`;
          }
          setErrors(found);
          setFailure(
            Object.keys(found).length > 0
              ? "Nothing was saved: fix the fields marked below."
              : `${error.title}${error.detail ? `: ${error.detail}` : ""}`,
          );
        } else {
          setFailure("Could not reach the server. Nothing was saved.");
        }
      });
  };

  const fieldId = (key: string) => `${id}-${key}`;
  const initialFocus = focus ? `#${CSS.escape(fieldId(focus))}` : undefined;

  return (
    <Dialog
      title="Edit my local settings"
      size="md"
      onClose={onClose}
      pending={pending}
      initialFocus={initialFocus}
      footer={
        <>
          <Button disabled={pending} onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={pending} onClick={save}>
            {pending ? "Saving…" : "Save local settings"}
          </Button>
        </>
      }
    >
      <form
        className="ah-stack ah-config-form"
        style={{ gap: 14 }}
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          Saved to <code className="ah-mono">hub.local.json</code> in the hub on this machine. Only
          you use these; the team&apos;s <code className="ah-mono">hub.json</code> does not change.
          Leave a field empty to use the team&apos;s value.
        </p>
        {failure && (
          <p role="alert" className="ah-config-error">
            {failure}
          </p>
        )}
        {IDENTITY.map((key) => (
          <div key={key} className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId(key)} className="ah-config-field-label">
              {LABEL[key]}
            </label>
            <input
              id={fieldId(key)}
              className="ah-input"
              value={identity[key]}
              placeholder={
                view[key].source === "local"
                  ? (view[key].team_value ?? "")
                  : (view[key].value ?? "")
              }
              aria-invalid={errors[key] ? true : undefined}
              aria-describedby={`${fieldId(key)}-help`}
              onChange={(event) => {
                setIdentity({ ...identity, [key]: event.target.value });
              }}
            />
            <span
              id={`${fieldId(key)}-help`}
              className={errors[key] ? "ah-small ah-config-error" : "ah-small ah-muted"}
            >
              {errors[key] ??
                (key === "branch_prefix"
                  ? `Ends with /, e.g. jane/. ${fallbackOf(view[key])}.`
                  : `${fallbackOf(view[key])}.`)}
            </span>
          </div>
        ))}
        <div className="ah-stack" style={{ gap: 4 }} id={fieldId("transport")} tabIndex={-1}>
          <span className="ah-config-field-label">Tracker transport</span>
          <SegmentedControl
            label="Tracker transport"
            options={[
              {
                id: "team",
                label: `Team's (${view.tracker.transport.team_value ?? view.tracker.transport.value ?? "api"})`,
              },
              { id: "api", label: "API" },
              { id: "mcp", label: "MCP" },
            ]}
            value={transport}
            onChange={setTransport}
          />
          <span className={errors.transport ? "ah-small ah-config-error" : "ah-small ah-muted"}>
            {errors.transport ??
              "API needs LINEAR_API_KEY; MCP uses your Linear MCP server in Claude."}
          </span>
        </div>
        {LOCAL_LISTS.map((key) => (
          <div key={key} className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={fieldId(key)} className="ah-config-field-label">
              {LABEL[key]}
            </label>
            <textarea
              id={fieldId(key)}
              className="ah-input ah-config-textarea"
              rows={3}
              value={lists[key]}
              spellCheck={false}
              aria-invalid={errors[key] ? true : undefined}
              aria-describedby={`${fieldId(key)}-help`}
              onChange={(event) => {
                setLists({ ...lists, [key]: event.target.value });
              }}
            />
            <span
              id={`${fieldId(key)}-help`}
              className={errors[key] ? "ah-small ah-config-error" : "ah-small ah-muted"}
            >
              {errors[key] ??
                `${LIST_HELP[key]} The team has ${String(view.guard[key].team.length)}.`}
            </span>
          </div>
        ))}
        {errors.guard && (
          <p role="alert" className="ah-config-error ah-small">
            Guard: {errors.guard}
          </p>
        )}
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          Environments and services: edit them with <code className="ah-mono">hub env --local</code>{" "}
          or ask Claude.
        </p>
      </form>
    </Dialog>
  );
}
