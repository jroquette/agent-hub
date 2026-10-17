/* Sessions toolbar: a wide search, the period, and one Filters popover for the rest (sessions v2). */
import { useEffect, useRef, useState } from "react";

import { Button, FacetMenu, FilterChip, Icon, Kbd, Popover } from "../../components";
import { typingIn } from "../../shell/goSequence";
import { OUTCOMES, PERIODS, TOOLS, WITHINS, badDecimal, type Period, type Within } from "./filters";

type Update = (changes: Record<string, string | null>) => void;

const PERIOD_LABEL: Record<Period, string> = {
  "24 h": "Last 24 hours",
  "7 d": "Last 7 days",
  "30 d": "Last 30 days",
  All: "All time",
};
const OUTCOME_LABEL: Record<(typeof OUTCOMES)[number], string> = {
  done: "Done",
  stopped: "Stopped",
  blocked: "Blocked",
  error: "Error",
};
/** The filters that live in the Filters popover, shown as chips once set. */
export const MORE_KEYS = [
  "repo",
  "outcome",
  "workflow",
  "agent",
  "file",
  "tool",
  "cost_min",
  "cost_max",
  "guard_denial",
  "status",
] as const;
const STATUS_LABEL: Record<string, string> = {
  waiting: "Needs you",
  live: "Working",
  idle: "Paused",
  ended: "Finished",
};
const MORE_LABEL: Record<(typeof MORE_KEYS)[number], string> = {
  repo: "Repo",
  outcome: "Outcome",
  workflow: "Workflow",
  status: "Status",
  agent: "Agent type",
  file: "Touched file",
  tool: "Used tool",
  cost_min: "Cost from",
  cost_max: "Cost to",
  guard_denial: "Had a guard denial",
};

function outcomeText(value: string | null): string {
  const outcome = OUTCOMES.find((o) => o === value);
  return outcome ? OUTCOME_LABEL[outcome] : (value ?? "");
}

export function periodLabel(period: Period): string {
  return PERIOD_LABEL[period];
}

/** `/` focuses the search; Esc in it clears, then leaves. */
function SearchField({ value, onChange }: { value: string; onChange: (q: string) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey || typingIn(event.target)) return;
      event.preventDefault();
      ref.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  return (
    <div className="ah-search sl-search">
      <Icon name="search" size="sm" />
      <input
        ref={ref}
        type="search"
        className="ah-input"
        aria-label="Find sessions"
        placeholder="Find by name, issue, repo or branch"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          if (value) onChange("");
          else event.currentTarget.blur();
        }}
      />
      {!value && (
        <span className="sl-search-kbd" aria-hidden="true">
          <Kbd>/</Kbd>
        </span>
      )}
    </div>
  );
}

function Choices({
  title,
  options,
  value,
  onPick,
  mono,
}: {
  title: string;
  options: { id: string; label: string }[];
  value: string | null;
  onPick: (id: string | null) => void;
  mono?: boolean;
}) {
  if (options.length === 0) return null;
  return (
    <fieldset className="sl-more-field" style={{ border: 0, margin: 0, padding: 0 }}>
      <legend className="ah-small" style={{ marginBottom: 4 }}>
        {title}
      </legend>
      <div className={mono ? "ah-row ah-wrap ah-mono" : "ah-row ah-wrap"} style={{ gap: 4 }}>
        {options.map((option) => (
          <FilterChip
            key={option.id}
            value={option.label}
            active={value === option.id}
            onClick={() => {
              onPick(value === option.id ? null : option.id);
            }}
          />
        ))}
      </div>
    </fieldset>
  );
}

function MoreFilters({
  params,
  update,
  repos,
  workflows,
}: {
  params: URLSearchParams;
  update: Update;
  repos: string[];
  workflows: string[];
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const fromUrl = () => ({
    agent: params.get("agent") ?? "",
    file: params.get("file") ?? "",
    cost_min: params.get("cost_min") ?? "",
    cost_max: params.get("cost_max") ?? "",
  });
  const [draft, setDraft] = useState(fromUrl);
  // A chip or Clear all changes the URL: the fields follow it, and the panel stays as it is.
  const urlKey = MORE_KEYS.map((key) => params.get(key) ?? "").join("\n");
  const [seenKey, setSeenKey] = useState(urlKey);
  if (seenKey !== urlKey) {
    setSeenKey(urlKey);
    setDraft(fromUrl());
  }
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  const set = MORE_KEYS.filter((key) => key !== "status" && params.get(key));
  const costBad = badDecimal(draft.cost_min) || badDecimal(draft.cost_max);
  const apply = () => {
    if (costBad) return;
    update({
      agent: draft.agent.trim(),
      file: draft.file.trim(),
      cost_min: draft.cost_min.trim(),
      cost_max: draft.cost_max.trim(),
    });
  };
  const text = (key: "agent" | "file", label: string, placeholder: string) => (
    <label className="ah-stack sl-more-field">
      <span className="ah-small">{label}</span>
      <input
        className="ah-input ah-mono"
        placeholder={placeholder}
        value={draft[key]}
        onChange={(event) => {
          setDraft({ ...draft, [key]: event.target.value });
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") apply();
        }}
        onBlur={apply}
      />
    </label>
  );
  return (
    <span ref={root} style={{ position: "relative", display: "inline-flex" }}>
      <button
        ref={button}
        type="button"
        className="ah-scope ah-facet-btn"
        data-active={set.length > 0}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <Icon name="list-filter" size="sm" />
        <span>{set.length > 0 ? `Filters · ${String(set.length)}` : "Filters"}</span>
        <Icon name="chevron-down" size="sm" />
      </button>
      <Popover
        open={open}
        label="Filters"
        style={{ top: 36, left: 0, width: 340, maxHeight: "70vh", overflow: "auto" }}
      >
        <div className="ah-stack" style={{ gap: 12, padding: 4 }}>
          <Choices
            title="Repo"
            mono
            options={repos.map((r) => ({ id: r, label: r }))}
            value={params.get("repo")}
            onPick={(id) => {
              update({ repo: id });
            }}
          />
          <Choices
            title="Outcome"
            options={OUTCOMES.map((o) => ({ id: o, label: OUTCOME_LABEL[o] }))}
            value={params.get("outcome")}
            onPick={(id) => {
              update({ outcome: id });
            }}
          />
          <Choices
            title="Workflow"
            mono
            options={workflows.map((w) => ({ id: w, label: w }))}
            value={params.get("workflow")}
            onPick={(id) => {
              update({ workflow: id });
            }}
          />
          {text("agent", "Agent type", "Subagent type, e.g. Explore")}
          {text("file", "Touched file", "Path or glob")}
          <fieldset className="sl-more-field" style={{ border: 0, margin: 0, padding: 0 }}>
            <legend className="ah-small" style={{ marginBottom: 4 }}>
              Used tool
            </legend>
            <div className="ah-row ah-wrap" style={{ gap: 4 }}>
              {TOOLS.map((tool) => (
                <FilterChip
                  key={tool}
                  value={tool}
                  active={params.get("tool") === tool}
                  onClick={() => {
                    update({ tool: params.get("tool") === tool ? null : tool });
                  }}
                />
              ))}
            </div>
          </fieldset>
          <div className="ah-stack" style={{ gap: 4 }}>
            <div className="ah-row" style={{ gap: 8 }}>
              {(["cost_min", "cost_max"] as const).map((bound) => (
                <label key={bound} className="ah-stack sl-more-field" style={{ flex: 1 }}>
                  <span className="ah-small">{bound === "cost_min" ? "Cost from" : "Cost to"}</span>
                  <input
                    className="ah-input"
                    inputMode="decimal"
                    placeholder="$ 0.00"
                    aria-invalid={badDecimal(draft[bound]) || undefined}
                    value={draft[bound]}
                    onChange={(event) => {
                      setDraft({ ...draft, [bound]: event.target.value });
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") apply();
                    }}
                    onBlur={apply}
                  />
                </label>
              ))}
            </div>
            {costBad && (
              <span className="ah-small" style={{ color: "var(--failed)" }}>
                Use a decimal with a dot, e.g. 1.5
              </span>
            )}
          </div>
          <label className="ah-facet-opt">
            <input
              type="checkbox"
              className="ah-check"
              checked={params.get("guard_denial") === "1"}
              onChange={() => {
                update({ guard_denial: params.get("guard_denial") === "1" ? null : "1" });
              }}
            />
            <Icon name="shield-x" size="sm" style={{ color: "var(--guard)" }} />
            Had a guard denial
          </label>
          <div className="ah-row" style={{ gap: 8, justifyContent: "flex-end" }}>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setDraft({ agent: "", file: "", cost_min: "", cost_max: "" });
                update(
                  Object.fromEntries(
                    MORE_KEYS.filter((key) => key !== "status").map((key) => [key, null]),
                  ),
                );
              }}
            >
              Clear these filters
            </Button>
            <Button
              size="sm"
              onClick={() => {
                apply();
                setOpen(false);
                button.current?.focus();
              }}
            >
              Done
            </Button>
          </div>
        </div>
      </Popover>
    </span>
  );
}

export interface ToolbarProps {
  params: URLSearchParams;
  update: Update;
  query: string;
  onQuery: (q: string) => void;
  period: Period;
  repos: string[];
  workflows: string[];
  view: "grid" | "list";
  within: Within | null;
  matches: number | null;
  onClearAll: () => void;
}

export function Toolbar({
  params,
  update,
  query,
  onQuery,
  period,
  repos,
  workflows,
  view,
  within,
  matches,
  onClearAll,
}: ToolbarProps) {
  const repo = params.get("repo");
  const workflow = params.get("workflow");
  const repoOptions = repo && !repos.includes(repo) ? [...repos, repo] : repos;
  const workflowOptions =
    workflow && !workflows.includes(workflow) ? [...workflows, workflow] : workflows;
  const more = MORE_KEYS.filter((key) => params.get(key));
  const anySet = Boolean(query) || more.length > 0 || params.get("period") !== null;
  return (
    <div className="ah-row ah-wrap sl-toolbar" role="group" aria-label="Filters">
      <SearchField value={query} onChange={onQuery} />
      {query && matches !== null && (
        <span className="ah-small ah-muted" role="status">
          {matches === 1 ? "1 match" : `${String(matches)} matches`}
        </span>
      )}
      <span title="Applies to finished sessions. Sessions that need you, work or are paused always show.">
        <FacetMenu
          label="Period"
          anyLabel={PERIOD_LABEL[period]}
          options={PERIODS.map((p) => ({
            id: p,
            label: PERIOD_LABEL[p],
            // The default period is not a filter the owner set: the button stays quiet.
            checked: p === period && p !== "7 d",
          }))}
          onToggle={(id) => {
            update({ period: id === "7 d" || id === period ? null : id });
          }}
        />
      </span>
      {view === "grid" && (
        <FacetMenu
          label="Group"
          anyLabel="None"
          options={WITHINS.filter((w) => w.id !== "flat").map((w) => ({
            id: w.id,
            label: w.label,
            checked: w.id === within,
          }))}
          onToggle={(id) => {
            update({ within: id === within ? null : id });
          }}
        />
      )}
      <MoreFilters
        params={params}
        update={update}
        repos={repoOptions}
        workflows={workflowOptions}
      />
      {more.map((key) => (
        <FilterChip
          key={key}
          k={key === "guard_denial" ? undefined : MORE_LABEL[key]}
          value={
            key === "guard_denial"
              ? MORE_LABEL[key]
              : key.startsWith("cost")
                ? `$${params.get(key) ?? ""}`
                : key === "status"
                  ? (STATUS_LABEL[params.get(key) ?? ""] ?? params.get(key) ?? "")
                  : key === "outcome"
                    ? outcomeText(params.get(key))
                    : (params.get(key) ?? "")
          }
          onRemove={() => {
            update({ [key]: null });
          }}
        />
      ))}
      {anySet && (
        <Button size="sm" variant="ghost" icon="x" onClick={onClearAll}>
          Clear filters
        </Button>
      )}
    </div>
  );
}
