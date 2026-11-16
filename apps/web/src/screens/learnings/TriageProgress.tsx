/* How Claude's reviews read on the Learnings screen: a badge per learning and a progress card per
 * review session, so it is plain which learning Claude is on, which wait their turn, and when it
 * needs you. */
import type { components } from "../../api/schema";
import { AppLink, Button, IconButton, StatusBadge } from "../../components";
import { CLAUDE_LABEL, conversationHref } from "./ClaudeReviewBadge";
import { displayTitle } from "./LearningDetail";
import { VERDICT } from "./ReviewPanel";
import type { ReviewVerdict } from "./review";
import type { TriageRun } from "./triage";

type Learning = components["schemas"]["Learning"];

const VERDICT_ORDER: readonly ReviewVerdict[] = ["ready", "needs_changes", "not_for_brain"];

/** One review session's progress: where Claude is, what it found so far, what needs you. */
export function TriageProgress({
  run,
  learnings,
  onSelect,
  onShowVerdict,
  onDismiss,
}: {
  run: TriageRun;
  learnings: readonly Learning[];
  onSelect: (id: string) => void;
  onShowVerdict: (verdict: ReviewVerdict) => void;
  onDismiss: () => void;
}) {
  const current = learnings.find((l) => l.id === run.currentId);
  const pct = run.total > 0 ? Math.round((run.reviewed / run.total) * 100) : 0;
  const what = run.total === 1 ? "learning" : "learnings";
  const tone =
    run.status === "waiting" ? "var(--waiting)" : run.status === "running" ? "var(--live)" : null;
  const title =
    run.status === "running"
      ? `Claude is triaging ${String(run.total)} ${what}`
      : run.status === "waiting"
        ? "Claude is waiting for you"
        : run.missing > 0
          ? `Triage stopped · ${String(run.missing)} without a verdict`
          : "Triage finished";
  return (
    <section
      aria-label="Triage progress"
      className="ah-stack"
      style={{
        gap: 8,
        padding: "10px 12px",
        borderRadius: 8,
        border: "1px solid var(--border)",
        borderLeft: `3px solid ${tone ?? "var(--border)"}`,
        background:
          run.status === "running"
            ? "var(--live-soft)"
            : run.status === "waiting"
              ? "var(--waiting-soft)"
              : "var(--surface)",
      }}
    >
      <div className="ah-row" style={{ gap: 8, alignItems: "center" }}>
        {run.status === "running" && <StatusBadge status="running" label="Live" />}
        {run.status === "waiting" && <StatusBadge status="waiting" label="Needs you" />}
        {run.status === "ended" && (
          <StatusBadge
            status={run.missing > 0 ? "stale" : "done"}
            label={run.missing > 0 ? "Stopped" : "Done"}
          />
        )}
        <b className="ah-grow" style={{ fontWeight: 600, minWidth: 0 }} role="status">
          {title}
        </b>
        {run.status === "ended" && (
          <IconButton icon="x" label="Dismiss the triage summary" size="sm" onClick={onDismiss} />
        )}
      </div>
      <span
        className="ah-budget-track"
        style={{ display: "block" }}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={run.total}
        aria-valuenow={run.reviewed}
        aria-label={`${String(run.reviewed)} of ${String(run.total)} reviewed`}
      >
        <span
          className="ah-budget-fill"
          style={{
            display: "block",
            width: `${String(pct)}%`,
            background: tone ?? "var(--done)",
            transition: "width 300ms ease",
          }}
        />
      </span>
      <span className="ah-small ah-muted" style={{ whiteSpace: "nowrap" }}>
        {run.reviewed} of {run.total} reviewed
        {run.status === "ended" && run.missing > 0 && " · the rest can be triaged again"}
      </span>
      {run.status === "waiting" && (
        <span className="ah-small">
          It stopped on a permission request or a question, with {run.total - run.reviewed}{" "}
          {run.total - run.reviewed === 1 ? "learning" : "learnings"} left. Answer it in the
          conversation and the triage carries on.
        </span>
      )}
      {current && run.status !== "ended" && (
        <span className="ah-small" style={{ minWidth: 0 }}>
          <span className="ah-subtle">{run.status === "waiting" ? "Stopped on " : "Now on "}</span>
          <button
            type="button"
            className="ah-link-button"
            style={{
              background: "none",
              border: 0,
              padding: 0,
              color: "var(--accent)",
              cursor: "pointer",
              font: "inherit",
              textAlign: "left",
            }}
            onClick={() => {
              onSelect(current.id);
            }}
          >
            {displayTitle(current.text)}
          </button>
        </span>
      )}
      <div className="ah-row ah-wrap" style={{ gap: 6 }}>
        {VERDICT_ORDER.filter((v) => run.verdicts[v] > 0).map((v) => (
          <Button
            key={v}
            size="sm"
            variant="ghost"
            title={`Show the learnings Claude marked ${VERDICT[v].label.toLowerCase()}`}
            onClick={() => {
              onShowVerdict(v);
            }}
          >
            <StatusBadge
              status={VERDICT[v].status}
              label={`${String(run.verdicts[v])} ${CLAUDE_LABEL[v].toLowerCase()}`}
            />
          </Button>
        ))}
        <span className="ah-grow" />
        <AppLink
          href={conversationHref(run.sessionId)}
          className="ah-small"
          style={{ fontWeight: run.status === "waiting" ? 600 : undefined }}
        >
          {run.status === "waiting" ? "Answer in the conversation" : "Open the conversation"}
        </AppLink>
      </div>
    </section>
  );
}
