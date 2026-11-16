/* The owner's decision on a feature: mark it shipped, close it without shipping, pause it, or reopen it. */
import "./features.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { components } from "../../api/schema";
import {
  Button,
  Dialog,
  Icon,
  MenuItem,
  Popover,
  ProblemError,
  type IconName,
} from "../../components";
import { ApiProblem, apiKey, apiPost, toProblem } from "../../lib/api";
import { useLaunchCookie } from "../../shell/queries";

type Feature = components["schemas"]["FeatureView"];
type OwnerStatusKind = components["schemas"]["OwnerStatus"]["status"];
export type StatusDecision = OwnerStatusKind | "active";

/** Each decision in words: the menu item, the dialog's verb and what it does. */
export const DECISIONS: Record<
  StatusDecision,
  { icon: IconName; item: string; verb: string; explain: string; badge: string }
> = {
  shipped: {
    icon: "circle-check",
    item: "Mark shipped",
    verb: "Mark shipped",
    explain: "The work is delivered. It moves to Shipped and closed, whatever step it shows now.",
    badge: "Shipped by you",
  },
  closed: {
    icon: "circle-stop",
    item: "Close without shipping",
    verb: "Close",
    explain:
      "It ends here: dropped, replaced, or not worth finishing. It moves to Shipped and closed.",
    badge: "Closed by you",
  },
  paused: {
    icon: "circle-pause",
    item: "Pause",
    verb: "Pause",
    explain: "Set it aside. It leaves the work in progress until you reopen it.",
    badge: "Paused by you",
  },
  active: {
    icon: "rotate-ccw",
    item: "Reopen",
    verb: "Reopen",
    explain: "Undo your decision: its step is read from its records again.",
    badge: "Open",
  },
};

const keyOf = (f: Pick<Feature, "project" | "slug">) => `${f.project}/${f.slug}`;

/** One feature's result when a decision is applied to several. */
export interface StatusResult {
  feature: Feature;
  error: ApiProblem | null;
}

/** Writes the decision for each feature, one after another, and refreshes the lists. */
function useSetOwnerStatus() {
  const client = useQueryClient();
  return useMutation<
    StatusResult[],
    ApiProblem,
    { features: Feature[]; status: StatusDecision; note: string }
  >({
    mutationFn: async ({ features, status, note }) => {
      const results: StatusResult[] = [];
      for (const feature of features) {
        try {
          await apiPost(
            "/api/v1/features/{project}/{slug}/status",
            { status, note: note.trim() || null },
            { path: { project: feature.project, slug: feature.slug } },
          );
          results.push({ feature, error: null });
        } catch (error) {
          results.push({
            feature,
            error: toProblem(error),
          });
        }
      }
      return results;
    },
    onSettled: (_data, _error, { features }) => {
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/features") });
      for (const f of features) {
        void client.invalidateQueries({
          queryKey: apiKey("/api/v1/features/{project}/{slug}", {
            path: { project: f.project, slug: f.slug },
          }),
        });
      }
    },
  });
}

/**
 * Confirms a decision over one feature or several, names each, takes an optional note, and reports
 * the result feature by feature. `onDone` gets the features it was written for.
 */
export function OwnerStatusDialog({
  features,
  status,
  nameOf,
  onClose,
  onDone,
}: {
  features: Feature[];
  status: StatusDecision;
  nameOf: (f: Feature) => string | null;
  onClose: () => void;
  onDone?: ((written: Feature[]) => void) | undefined;
}) {
  const [note, setNote] = useState("");
  const set = useSetOwnerStatus();
  const { lock } = useLaunchCookie();
  const words = DECISIONS[status];
  const failed = set.data?.filter((r) => r.error) ?? [];
  const n = features.length;
  const [only] = features;
  const count = n === 1 && only ? (nameOf(only) ?? only.slug) : `${String(n)} features`;
  return (
    <Dialog
      title={`${words.verb} ${count}?`}
      size="md"
      pending={set.isPending}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={set.isPending}>
            {failed.length ? "Close" : "Cancel"}
          </Button>
          {!failed.length && (
            <Button
              variant="primary"
              icon={words.icon}
              disabled={set.isPending || lock !== null}
              title={lock?.detail}
              onClick={() => {
                set.mutate(
                  { features, status, note },
                  {
                    onSuccess: (results) => {
                      const ok = results.filter((r) => !r.error).map((r) => r.feature);
                      onDone?.(ok);
                      if (ok.length === results.length) onClose();
                    },
                  },
                );
              }}
            >
              {set.isPending ? "Saving…" : n === 1 ? words.verb : `${words.verb} ${String(n)}`}
            </Button>
          )}
        </>
      }
    >
      <div className="ah-stack" style={{ gap: 12 }}>
        <p className="ah-muted" style={{ margin: 0 }}>
          {words.explain} Writes <span className="ah-mono">status.md</span> in each feature&apos;s
          hub folder, uncommitted, for your next hub PR. Linear is not changed.
        </p>
        {n > 1 && (
          <ul className="fs-dialog-list">
            {features.map((f) => {
              const result = set.data?.find((r) => keyOf(r.feature) === keyOf(f));
              return (
                <li key={keyOf(f)}>
                  {result && (
                    <Icon
                      name={result.error ? "circle-x" : "circle-check"}
                      size="sm"
                      style={{ color: result.error ? "var(--failed)" : "var(--done)" }}
                    />
                  )}
                  <span className="ah-mono">{nameOf(f) ?? f.slug}</span>
                  <span className="ah-subtle">{f.project}</span>
                  {result?.error && (
                    <span className="ah-small" style={{ color: "var(--failed)" }}>
                      {result.error.detail ?? result.error.title}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {status !== "active" && (
          <label className="ah-stack ah-small" style={{ gap: 4 }}>
            <span>Why (optional)</span>
            <textarea
              className="ah-input"
              rows={2}
              maxLength={2000}
              value={note}
              placeholder={
                status === "closed"
                  ? "Replaced by another feature, no longer needed…"
                  : "What you checked, or what is left"
              }
              onChange={(event) => {
                setNote(event.target.value);
              }}
            />
          </label>
        )}
        {lock && (
          <span className="ah-small ah-muted">
            {lock.title}. {lock.detail}
          </span>
        )}
        {n === 1 && failed[0]?.error && (
          <ProblemError
            compact
            title={`Could not ${words.verb.toLowerCase()}`}
            detail={failed[0].error.detail ?? failed[0].error.title}
            status={failed[0].error.status || undefined}
          />
        )}
      </div>
    </Dialog>
  );
}

/** The "Status" button of a feature's page: the decisions the owner can take on it now. */
export function OwnerStatusMenu({
  feature,
  nameOf,
}: {
  feature: Feature;
  nameOf: (f: Feature) => string | null;
}) {
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<StatusDecision | null>(null);
  const wrap = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: PointerEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const current = feature.owner_status?.status ?? null;
  const options: StatusDecision[] = current
    ? ["active", ...(["shipped", "closed", "paused"] as const).filter((s) => s !== current)]
    : ["shipped", "closed", "paused"];
  return (
    <span ref={wrap} style={{ position: "relative" }}>
      <Button
        size="sm"
        icon="flag"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        Status
        <Icon name="chevron-down" size="sm" />
      </Button>
      <Popover open={open} label="Feature status" style={{ top: 32, right: 0, minWidth: 240 }}>
        {options.map((s) => (
          <MenuItem
            key={s}
            icon={DECISIONS[s].icon}
            onClick={() => {
              setOpen(false);
              setChosen(s);
            }}
          >
            {DECISIONS[s].item}
          </MenuItem>
        ))}
      </Popover>
      {chosen && (
        <OwnerStatusDialog
          features={[feature]}
          status={chosen}
          nameOf={nameOf}
          onClose={() => {
            setChosen(null);
          }}
        />
      )}
    </span>
  );
}

/** "Closed by you · 14 Nov · Replaced by …", under a feature's title while a decision holds. */
export function OwnerStatusBanner({ feature }: { feature: Feature }) {
  const decided = feature.owner_status;
  if (!decided) return null;
  const words = DECISIONS[decided.status];
  const on = decided.decided_at ? ` · ${fmtDay(decided.decided_at)}` : "";
  return (
    <p className="fs-banner" role="note" data-status={decided.status}>
      <Icon name={words.icon} size="sm" />
      <span>
        <b>
          {words.badge}
          {on}
        </b>
        {decided.note ? ` · ${decided.note}` : ""}
        <span className="ah-muted">
          {" "}
          · Its records alone would put it at {feature.golden_path.phase.replace("_", " ")}.
        </span>
      </span>
    </p>
  );
}

/** "2026-11-14…" → "14 Nov". */
export function fmtDay(iso: string): string {
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}
