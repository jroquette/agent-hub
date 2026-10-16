/* Claude's state on one learning, as the queue row and the top of the detail show it. */
import { AppLink, StatusBadge } from "../../components";
import { VERDICT } from "./ReviewPanel";
import type { ClaudeVerdict } from "./filters";
import type { ClaudeReview } from "./triage";

export const conversationHref = (sessionId: string) =>
  `/agent-sessions/${encodeURIComponent(sessionId)}`;

/** What each state reads as in the facet menu. */
export const CLAUDE_LABEL: Record<ClaudeVerdict, string> = {
  ready: "Goes in",
  needs_changes: "Needs changes",
  not_for_brain: "Leave out",
  reviewing: "Reviewing now",
  queued: "Queued",
  waiting: "Needs you",
  no_verdict: "No verdict",
  unreviewed: "Not reviewed",
};

/** Claude's state on one learning; nothing until a review was asked for. */
export function ClaudeReviewBadge({ review }: { review: ClaudeReview }) {
  switch (review.verdict) {
    case "unreviewed":
      return null;
    case "reviewing":
      return <StatusBadge status="running" label="Claude is reviewing this now" />;
    case "queued":
      return (
        <StatusBadge
          status="queued"
          quiet
          label={
            review.position === null
              ? "Queued for Claude"
              : review.position === 1
                ? "Up next for Claude"
                : `Queued for Claude · ${String(review.position)} ahead`
          }
        />
      );
    case "waiting":
      return <StatusBadge status="waiting" label="Claude needs your answer" />;
    case "no_verdict":
      return <StatusBadge status="stale" label="No verdict from Claude" />;
    default: {
      const look = VERDICT[review.verdict];
      return (
        <StatusBadge
          status={look.status}
          label={`Claude: ${look.label}`}
          title={review.summary ?? undefined}
        />
      );
    }
  }
}

/** The top of a learning's detail while Claude reviews it, or once it has: what it is doing or
 * what it recommends, with a jump to the full review further down. */
export function ClaudeReviewNotice({
  review,
  reviewAnchor,
}: {
  review: ClaudeReview;
  /** The id of the Review section, when the detail shows one. */
  reviewAnchor: string | null;
}) {
  if (review.verdict === "unreviewed" || review.sessionId === null) return null;
  const text: Record<Exclude<ClaudeVerdict, "unreviewed">, string> = {
    reviewing:
      "Claude is checking this learning right now. Its recommendation will appear here; you can still decide without it.",
    queued:
      "This learning is in Claude's triage queue. It shows here when Claude gets to it; you can still decide without it.",
    waiting:
      "Claude stopped on a permission request or a question. Answer it in the conversation and the review carries on.",
    no_verdict:
      "The review session ended without a verdict for this learning. Triage it again, or review it on its own below.",
    ready: review.summary ?? "",
    needs_changes: review.summary ?? "",
    not_for_brain: review.summary ?? "",
  };
  const tone =
    review.verdict === "reviewing"
      ? "var(--live)"
      : review.verdict === "waiting"
        ? "var(--waiting)"
        : "var(--border-strong, var(--border))";
  return (
    <aside
      aria-label="Claude's review"
      className="ah-stack"
      style={{
        gap: 6,
        marginTop: 12,
        padding: "10px 12px",
        borderRadius: 8,
        border: "1px solid var(--border)",
        borderLeft: `3px solid ${tone}`,
        background:
          review.verdict === "reviewing"
            ? "var(--live-soft)"
            : review.verdict === "waiting"
              ? "var(--waiting-soft)"
              : "var(--surface)",
      }}
    >
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <ClaudeReviewBadge review={review} />
        <span className="ah-small ah-subtle">Claude&apos;s recommendation · you decide</span>
      </div>
      {text[review.verdict] && <span className="ah-small">{text[review.verdict]}</span>}
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        {reviewAnchor && ["ready", "needs_changes", "not_for_brain"].includes(review.verdict) && (
          <a href={`#${reviewAnchor}`} className="ah-small">
            See the checks and the suggested target
          </a>
        )}
        <AppLink
          href={conversationHref(review.sessionId)}
          className="ah-small"
          style={{ fontWeight: review.verdict === "waiting" ? 600 : undefined }}
        >
          {review.verdict === "waiting" ? "Answer in the conversation" : "Open the conversation"}
        </AppLink>
      </div>
    </aside>
  );
}
