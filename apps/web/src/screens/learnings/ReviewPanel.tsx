import { useState } from "react";

import type { components } from "../../api/schema";
import {
  AppLink,
  Banner,
  Button,
  Icon,
  StatusBadge,
  type IconName,
  type Status,
} from "../../components";
import { useAgentTranscript } from "../agent-session/queries";
import { sessionControlUnavailable } from "../sessions-list/control";
import { useAgentCapabilities, useCreateAgentSession, useWorkdirs } from "../sessions-list/queries";
import {
  forgetReviewLink,
  newReviewDraftId,
  readReviewLink,
  reviewPrompt,
  reviewWrites,
  saveReviewLink,
  type CheckResult,
  type LearningReview,
  type ReviewLink,
  type ReviewVerdict,
} from "./review";

type LearningDetailView = components["schemas"]["LearningDetail"];

export const VERDICT: Record<ReviewVerdict, { status: Status; label: string }> = {
  ready: { status: "done", label: "Ready for the brain" },
  needs_changes: { status: "waiting", label: "Needs changes" },
  not_for_brain: { status: "failed", label: "Not for the brain" },
};

const CHECK: Record<CheckResult, { icon: IconName; label: string; color: string }> = {
  pass: { icon: "circle-check", label: "Pass", color: "var(--done)" },
  fail: { icon: "circle-x", label: "Fail", color: "var(--failed)" },
  unknown: { icon: "circle-dashed", label: "Could not tell", color: "var(--text-subtle)" },
};

const conversation = (sessionId: string) => `/agent-sessions/${encodeURIComponent(sessionId)}`;

export interface ReviewPanelProps {
  detail: LearningDetailView;
  /** The body the note has now (the edit when there is one). */
  currentBody: string;
  /** Claude's revised body becomes the learning's edit. */
  onUseRevision: (body: string) => void;
  /** Claude's suggested target goes into the Target field. */
  onUseTarget: (target: string) => void;
}

function Verdict({
  review,
  revision,
  currentBody,
  onUseRevision,
  onUseTarget,
}: {
  review: LearningReview;
  revision: string | null;
  currentBody: string;
  onUseRevision: (body: string) => void;
  onUseTarget: (target: string) => void;
}) {
  const look = VERDICT[review.verdict];
  const usedRevision = revision !== null && revision === currentBody;
  return (
    <div className="ah-stack" style={{ gap: 10 }}>
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <StatusBadge status={look.status} label={look.label} />
        <span className="ah-small ah-subtle">Claude&apos;s recommendation · you decide</span>
      </div>
      {review.summary && <p style={{ margin: 0 }}>{review.summary}</p>}
      {review.checks.length > 0 && (
        <ul
          aria-label="Checks"
          className="ah-stack"
          style={{ listStyle: "none", margin: 0, padding: 0, gap: 6 }}
        >
          {review.checks.map((check) => {
            const mark = CHECK[check.result];
            return (
              <li key={check.name} className="ah-row" style={{ gap: 8, alignItems: "flex-start" }}>
                <Icon name={mark.icon} size="sm" style={{ color: mark.color, marginTop: 3 }} />
                <span className="ah-small">
                  <b style={{ fontWeight: 600 }}>{check.name}</b>{" "}
                  <span className="ah-subtle">· {mark.label}</span>
                  {check.note && <span className="ah-muted"> — {check.note}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        {revision !== null &&
          (usedRevision ? (
            <span className="ah-small ah-muted">
              <Icon name="check" size="sm" /> Claude&apos;s revision is your edit
            </span>
          ) : (
            <Button
              size="sm"
              icon="file-pen"
              onClick={() => {
                onUseRevision(revision);
              }}
            >
              Use Claude&apos;s revision
            </Button>
          ))}
        {review.target && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              if (review.target) onUseTarget(review.target);
            }}
          >
            Use target <span className="ah-mono">brain/{review.target}</span>
          </Button>
        )}
      </div>
    </div>
  );
}

function RunningReview({
  link,
  currentBody,
  onUseRevision,
  onUseTarget,
  onRestart,
}: {
  link: ReviewLink;
  currentBody: string;
  onUseRevision: (body: string) => void;
  onUseTarget: (target: string) => void;
  onRestart: () => void;
}) {
  const transcript = useAgentTranscript(link.sessionId);
  const { state } = transcript;
  const writes = reviewWrites(state, link.draftId);
  const ended = state.status === "ended" || state.status === "failed";
  const open = (
    <AppLink href={conversation(link.sessionId)} className="ah-small">
      Open the conversation
    </AppLink>
  );
  let body;
  if (transcript.error) {
    body = (
      <span className="ah-small ah-muted">
        The review session could not be read: {transcript.error.title}.
      </span>
    );
  } else if (writes.review) {
    body = (
      <Verdict
        review={writes.review}
        revision={writes.revision}
        currentBody={currentBody}
        onUseRevision={onUseRevision}
        onUseTarget={onUseTarget}
      />
    );
  } else if (writes.malformed) {
    body = (
      <span className="ah-small">
        Claude wrote a verdict this page cannot read. Open the conversation to see it, or review
        again.
      </span>
    );
  } else if (ended) {
    body = <span className="ah-small">The review ended without a verdict.</span>;
  } else if (state.status === "waiting_permission") {
    body = (
      <span className="ah-small" role="status">
        <b style={{ fontWeight: 600 }}>Claude is waiting for your answer</b> to a permission
        request. Open the conversation to answer it.
      </span>
    );
  } else {
    body = (
      <span className="ah-row ah-small ah-muted" role="status" style={{ gap: 6 }}>
        <Icon name="loader" size="sm" />
        Claude is checking the claims, the brain for duplicates and where it belongs…
      </span>
    );
  }
  return (
    <div className="ah-stack" style={{ gap: 10 }}>
      {body}
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        {open}
        {(writes.review !== null || writes.malformed || ended || transcript.error) && (
          <Button size="sm" variant="ghost" icon="rotate-ccw" onClick={onRestart}>
            Review again
          </Button>
        )}
      </div>
    </div>
  );
}

/** Ask Claude to review a learning, then read its verdict and use its revision or target. */
export function ReviewPanel({ detail, currentBody, onUseRevision, onUseTarget }: ReviewPanelProps) {
  const [link, setLink] = useState<ReviewLink | null>(() => readReviewLink(detail.id));
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const canDrive = capabilities.data !== undefined && unavailable === null;
  const workdirs = useWorkdirs(detail.project, canDrive && link === null);
  const hub = workdirs.data?.items.find((w) => w.kind === "hub") ?? null;
  const create = useCreateAgentSession();
  const reason = unavailable
    ? `${unavailable.title}.`
    : !canDrive
      ? "Checking whether this machine can drive Claude…"
      : workdirs.isPending
        ? "Looking for the hub folder…"
        : hub === null
          ? `Project ${detail.project} has no hub folder to work in.`
          : null;

  const start = async () => {
    if (!hub || !detail.note_path) return;
    const draftId = newReviewDraftId();
    const session = await create.mutateAsync({
      project: detail.project,
      workdir_id: hub.workdir_id,
      mode: "acceptEdits",
      fork: false,
      prompt: reviewPrompt({
        project: detail.project,
        notePath: detail.note_path.startsWith("brain/")
          ? detail.note_path
          : `brain/${detail.note_path}`,
        draftId,
        targetChoices: detail.target_choices,
        suggestedTarget: detail.suggested_target,
      }),
    });
    const next = { sessionId: session.id, draftId };
    saveReviewLink(detail.id, next);
    setLink(next);
  };

  return (
    <section aria-label="Review by Claude" className="ah-stack" style={{ gap: 10 }}>
      {link ? (
        <RunningReview
          key={link.sessionId}
          link={link}
          currentBody={currentBody}
          onUseRevision={onUseRevision}
          onUseTarget={onUseTarget}
          onRestart={() => {
            forgetReviewLink(detail.id);
            setLink(null);
          }}
        />
      ) : (
        <>
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            Claude checks it is non-obvious, still true and not already in the brain, suggests where
            it goes and, if needed, a revised text. It changes nothing: you decide.
          </p>
          <div className="ah-row ah-wrap" style={{ gap: 8 }}>
            <Button
              size="sm"
              icon="message-square"
              disabled={reason !== null || create.isPending}
              title={reason ?? undefined}
              onClick={() => void start()}
            >
              {create.isPending ? "Starting the review…" : "Review with Claude"}
            </Button>
            {reason && <span className="ah-small ah-subtle">{reason}</span>}
          </div>
          {create.error && (
            <Banner tone="warning" boxed>
              <b style={{ fontWeight: 600 }}>The review did not start.</b> {create.error.title}
            </Banner>
          )}
        </>
      )}
    </section>
  );
}
