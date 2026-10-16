import { Fragment, useId, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";

import type { components } from "../../api/schema";
import {
  Banner,
  Button,
  ExternalLabel,
  FrontmatterChips,
  IdChip,
  Icon,
  Markdown,
  ProblemError,
  SegmentedControl,
  ProvenanceBadge,
  Skeleton,
  StatusBadge,
  Time,
  type Frontmatter,
  type Status,
} from "../../components";
import { fmtAgo } from "../../lib/format";
import { safeHref } from "../../lib/safeHref";
import { DiscussButton, useDiscussTarget } from "../../shell/discuss";
import { DecideDialog, type DecideAction } from "./DecideDialog";
import { learningDiscussTarget } from "./discussLearning";
import { useNoteDraft } from "./noteDraft";
import { ReviewPanel } from "./ReviewPanel";
import { useDecideLearning, useHubRepo, useLearning, type LearningActionResult } from "./queries";

type Learning = components["schemas"]["Learning"];
type LearningDetailView = components["schemas"]["LearningDetail"];
export type LearningState = components["schemas"]["LearningState"];

const STATE: Record<LearningState, { status: Status; label: string }> = {
  proposed: { status: "queued", label: "Proposed" },
  accepted_pr_open: { status: "waiting", label: "Accepted · PR open" },
  rejected_pr_open: { status: "waiting", label: "Rejected · PR open" },
  in_brain: { status: "done", label: "In brain" },
  archived: { status: "ended", label: "Archived" },
};

const PR_OPEN = "A pull request for this learning is already open";
const BLOCKED_BY_STATE: Record<LearningState, string | null> = {
  proposed: null,
  accepted_pr_open: PR_OPEN,
  rejected_pr_open: PR_OPEN,
  in_brain: "This learning is already in the brain",
  archived: "This learning is archived",
};

/** The learning's place (L11); a legacy learning without one is placed by its status. */
export function stateOf(l: Pick<Learning, "state" | "status">): LearningState {
  if (l.state) return l.state;
  if (l.status === "accepted") return "in_brain";
  if (l.status === "rejected") return "archived";
  return "proposed";
}

export function LearningStateBadge({ state }: { state: LearningState }) {
  const look = STATE[state];
  return <StatusBadge status={look.status} label={look.label} />;
}

/** A title without the "Proposal:" agents often prefix: every learning is a proposal here. */
export function displayTitle(t: string): string {
  return t.replace(/^\s*proposal:\s*/i, "");
}

/** Backticks in a learning title render as inline code (design). */
export function Title({ t }: { t: string }) {
  return (
    <>
      {displayTitle(t)
        .split("`")
        .map((part, i) =>
          i % 2 ? (
            <code
              key={i}
              className="ah-mono"
              style={{
                fontSize: "0.92em",
                background: "var(--code-bg)",
                padding: "0 3px",
                borderRadius: 3,
              }}
            >
              {part}
            </code>
          ) : (
            <Fragment key={i}>{part}</Fragment>
          ),
        )}
    </>
  );
}

export const isExternal = (l: Pick<Learning, "provenance">) =>
  l.provenance === "agent-from-external";

export function ageOf(l: Pick<Learning, "proposed_at">, now: number): string {
  return l.proposed_at
    ? fmtAgo(Math.max(1, (now - Date.parse(l.proposed_at)) / 1000)).replace(" ago", "")
    : "—";
}

function Section({
  label,
  children,
  labelFor,
}: {
  label: string;
  children: ReactNode;
  labelFor?: string | undefined;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "120px 1fr",
        gap: 12,
        padding: "12px 0",
        borderTop: "1px solid var(--border)",
      }}
    >
      {labelFor ? (
        <label htmlFor={labelFor} className="ah-small ah-subtle">
          {label}
        </label>
      ) : (
        <div className="ah-small ah-subtle">{label}</div>
      )}
      <div style={{ minWidth: 0 }}>{children}</div>
    </div>
  );
}

function PullRequestLink({ url }: { url: string }) {
  const href = safeHref(url);
  if (href === null) return <span className="ah-mono ah-small">{url}</span>;
  return (
    <a className="ah-mono ah-small" href={href} target="_blank" rel="noopener noreferrer">
      {url} <span className="ah-sr">(opens in a new tab)</span>
    </a>
  );
}

const PROVENANCES = new Set(["human", "agent", "agent-from-code", "agent-from-external"]);

/** The note's frontmatter as the chips show it (a field of an unexpected shape is left out). */
export function noteFrontmatter(fields: Record<string, unknown> | undefined): Frontmatter {
  if (!fields) return {};
  const text = (key: string) => {
    const value = fields[key];
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
  };
  const repos = fields.repos;
  const provenance = text("provenance");
  return {
    type: text("type"),
    repos: Array.isArray(repos)
      ? repos.filter((r): r is string => typeof r === "string")
      : undefined,
    last_verified: text("last_verified"),
    provenance:
      provenance && PROVENANCES.has(provenance)
        ? (provenance as Frontmatter["provenance"])
        : undefined,
  };
}

function NoteView({ detail, markdown }: { detail: LearningDetailView; markdown: string }) {
  const navigate = useNavigate();
  const note = detail.note;
  return (
    <div
      style={{
        background: "var(--surface-sunken)",
        borderRadius: "var(--radius-md)",
        padding: "10px 14px",
        borderLeft: "2px solid var(--border-strong)",
      }}
    >
      <Markdown
        source={markdown}
        note={note ? { project: note.project, path: note.path } : undefined}
        onBrainLink={(link) => {
          void navigate(link.route);
        }}
      />
    </div>
  );
}

type NoteMode = "write" | "preview";

function NoteEditor({
  detail,
  body,
  onChange,
  onDone,
}: {
  detail: LearningDetailView;
  body: string;
  onChange: (body: string) => void;
  onDone: () => void;
}) {
  const [mode, setMode] = useState<NoteMode>("write");
  const fieldId = useId();
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <div className="ah-row" style={{ gap: 8 }}>
        <SegmentedControl
          label="Note view"
          value={mode}
          options={[
            { id: "write", label: "Write" },
            { id: "preview", label: "Preview" },
          ]}
          onChange={(value) => {
            setMode(value === "preview" ? "preview" : "write");
          }}
        />
        <span className="ah-grow" />
        <Button size="sm" icon="check" onClick={onDone}>
          Done editing
        </Button>
      </div>
      {mode === "write" ? (
        <>
          <label htmlFor={fieldId} className="ah-sr">
            Note body
          </label>
          <textarea
            id={fieldId}
            className="ah-input ah-mono"
            rows={Math.min(24, Math.max(8, body.split("\n").length + 1))}
            value={body}
            spellCheck
            style={{ width: "100%", fontSize: 12.5, lineHeight: "19px", resize: "vertical" }}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          />
        </>
      ) : (
        <NoteView detail={detail} markdown={body} />
      )}
    </div>
  );
}

function NoteBody({
  detail,
  row,
  canEdit,
  draft,
}: {
  detail: LearningDetailView | undefined;
  row: Learning;
  canEdit: boolean;
  draft: ReturnType<typeof useNoteDraft>;
}) {
  const [editing, setEditing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  if (!detail) {
    return (
      <div className="ah-stack" style={{ gap: 6 }} aria-busy="true">
        {row.summary ? (
          <p style={{ margin: 0 }}>{row.summary}</p>
        ) : (
          row.note_unavailable && <span className="ah-small ah-muted">{row.note_unavailable}</span>
        )}
        <Skeleton height={64} radius={8} />
      </div>
    );
  }
  const note = detail.note;
  if (!note) {
    return (
      <section aria-label="Note" style={{ minWidth: 0 }}>
        <div className="ah-stack" style={{ gap: 4 }}>
          <span>{detail.note_unavailable ?? "The note could not be read."}</span>
          {detail.note_path && (
            <span className="ah-small ah-muted">
              The agent recorded <span className="ah-mono">{detail.note_path}</span>, but the hub
              checkout has no such file: it was likely written in another worktree and never pushed.
              Pull the hub to bring it in; without the note there is nothing to put in the brain.
            </span>
          )}
        </div>
      </section>
    );
  }
  const current = draft.draft;
  const edited = current !== null && current.body !== note.markdown;
  const stale = current !== null && current.base !== note.markdown;
  return (
    <section aria-label="Note" style={{ minWidth: 0 }} className="ah-stack">
      {stale && (
        <Banner tone="warning" boxed>
          <b style={{ fontWeight: 600 }}>The note changed in the hub since you edited it.</b> Your
          edit is kept; discard it to start again from the hub&apos;s version.
        </Banner>
      )}
      {editing && canEdit ? (
        <NoteEditor
          detail={detail}
          body={current?.body ?? note.markdown}
          onChange={(body) => {
            draft.save({ body, base: current?.base ?? note.markdown });
          }}
          onDone={() => {
            setEditing(false);
            if (current !== null && current.body === note.markdown) draft.discard();
          }}
        />
      ) : (
        <NoteView detail={detail} markdown={current?.body ?? note.markdown} />
      )}
      <div className="ah-row ah-wrap ah-small ah-subtle" style={{ gap: 8 }}>
        {edited ? (
          <span>
            <b style={{ fontWeight: 600, color: "var(--text)" }}>Edited here.</b> The accept pull
            request writes this version of <span className="ah-mono">{detail.note_path}</span>.
          </span>
        ) : (
          detail.note_path && (
            <span>
              As proposed in <span className="ah-mono">{detail.note_path}</span>, unedited.
            </span>
          )
        )}
        <span className="ah-grow" />
        {canEdit && !editing && (
          <Button
            size="sm"
            variant="ghost"
            icon="file-pen"
            onClick={() => {
              setEditing(true);
            }}
          >
            {edited ? "Edit again" : "Edit note"}
          </Button>
        )}
        {current !== null &&
          (discarding ? (
            <span className="ah-row" style={{ gap: 6 }}>
              <span>Discard your edits?</span>
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  draft.discard();
                  setDiscarding(false);
                  setEditing(false);
                }}
              >
                Discard edits
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setDiscarding(false);
                }}
              >
                Keep
              </Button>
            </span>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              icon="x"
              onClick={() => {
                setDiscarding(true);
              }}
            >
              Discard edits
            </Button>
          ))}
      </div>
    </section>
  );
}

export interface LearningDetailProps {
  id: string;
  /** The list's copy of the learning, shown while its detail loads. */
  row?: Learning | undefined;
  now: number;
  /**
   * Called when an accept or reject is sent, so the screen keeps this learning open (pinned in the URL)
   * while the decision moves it out of the list it was picked from.
   */
  onDecide?: ((id: string) => void) | undefined;
}

/** One learning: its note, source, target and the accept/reject actions (AC-201.29). */
export function LearningDetail({ id, row, now, onDecide }: LearningDetailProps) {
  const query = useLearning(id);
  const detail = query.data;
  const l: Learning | undefined = detail ?? row;
  const hubRepo = useHubRepo(l?.project ?? null);
  const decide = useDecideLearning(id);
  const draft = useNoteDraft(id);
  const [deciding, setDeciding] = useState<DecideAction | null>(null);
  const [edited, setEdited] = useState<string | null>(null);
  const [result, setResult] = useState<LearningActionResult | null>(null);
  const targetId = useId();
  const choicesId = useId();
  // The learning is what the Discuss panel talks about: open on a proposal, so the owner can
  // review, improve or drop it with Claude straight away; on a decided one, when asked.
  const placed = l ? (result?.state ?? stateOf(l)) : null;
  useDiscussTarget(
    l
      ? learningDiscussTarget({
          id: l.id,
          project: l.project,
          text: displayTitle(l.text),
          path: detail?.note ? `brain/${detail.note.path}` : null,
          recordedPath: l.note_path ?? null,
          inBrain: placed === "in_brain",
          proposed: placed === "proposed",
        })
      : null,
  );

  if (query.isError && !l) {
    return (
      <div style={{ padding: "20px 28px" }}>
        <ProblemError
          title={query.error.title}
          detail={query.error.detail}
          status={query.error.status}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }
  if (!l) {
    return (
      <section
        aria-label="Proposal"
        aria-busy="true"
        className="ah-stack"
        style={{ padding: "20px 28px" }}
      >
        <Skeleton width="70%" height={22} />
        <Skeleton width="45%" />
        <Skeleton height={64} radius={8} />
      </section>
    );
  }

  const fm = noteFrontmatter(detail?.note?.frontmatter);
  const provenance = l.provenance ?? fm.provenance ?? null;
  const ext = isExternal({ provenance });
  const state = result?.state ?? stateOf(l);
  const prUrl = result?.pr_url ?? l.pr_url ?? null;
  const blocked = l.actions_unavailable ?? (result ? PR_OPEN : BLOCKED_BY_STATE[state]) ?? null;
  const target = edited ?? detail?.suggested_target ?? "";
  const canDecide = blocked === null && detail !== undefined;
  const original = detail?.note?.markdown;
  const noteBody =
    draft.draft !== null && original !== undefined && draft.draft.body !== original
      ? draft.draft.body
      : undefined;

  const confirm = (reason: string) => {
    onDecide?.(id);
    decide.mutate(
      deciding === "accept"
        ? { action: "accept", target: target.trim(), noteBody }
        : { action: "reject", reason },
      {
        onSuccess: (answer) => {
          setResult(answer);
          setDeciding(null);
          draft.discard();
        },
      },
    );
  };

  return (
    <section
      aria-label="Proposal"
      style={{ display: "flex", flexDirection: "column", minWidth: 0 }}
    >
      <div style={{ padding: "20px 28px 12px" }}>
        <div
          style={
            ext
              ? {
                  border: "1px solid var(--waiting)",
                  borderLeft: "3px solid var(--waiting)",
                  borderRadius: "var(--radius-lg)",
                  overflow: "hidden",
                }
              : undefined
          }
        >
          <div
            style={ext ? { background: "var(--waiting-soft)", padding: "12px 16px" } : undefined}
          >
            <div className="ah-row" style={{ gap: 8, alignItems: "flex-start" }}>
              {ext && (
                <Icon name="triangle-alert" style={{ color: "var(--waiting)", marginTop: 4 }} />
              )}
              <h2 className="ah-h2 ah-grow" style={{ fontSize: 18, lineHeight: "26px" }}>
                <Title t={l.text} />
              </h2>
              <span style={{ flex: "none" }}>
                <DiscussButton label="Talk with Claude" />
              </span>
            </div>
            <div className="ah-row ah-wrap ah-small ah-muted" style={{ gap: 8, marginTop: 6 }}>
              <LearningStateBadge state={state} />
              {provenance && <ProvenanceBadge provenance={provenance} />}
              {ext && <ExternalLabel source="External content" />}
              <span title={l.proposed_at ?? undefined}>
                proposed {l.proposed_at ? `${ageOf(l, now)} ago` : ""} by{" "}
                <span className="ah-mono" style={{ color: "var(--text)" }}>
                  {l.author ?? "an agent"}
                </span>
              </span>
            </div>
          </div>
          {ext && (
            <div style={{ padding: "12px 16px" }}>
              <b style={{ fontWeight: 600 }}>Verify before accepting.</b> This text came from
              outside the project and was relayed by an agent.
            </div>
          )}
        </div>

        <div style={{ marginTop: 16 }}>
          {(fm.type ?? fm.repos ?? fm.last_verified) && (
            <Section label="Frontmatter">
              <FrontmatterChips fm={{ ...fm, provenance: undefined }} />
            </Section>
          )}
          <Section label="Note">
            {query.isError ? (
              <ProblemError
                title={query.error.title}
                detail={query.error.detail}
                status={query.error.status}
                onRetry={() => void query.refetch()}
              />
            ) : (
              <NoteBody
                detail={detail}
                row={l}
                canEdit={canDecide && detail.note !== null && detail.note !== undefined}
                draft={draft}
              />
            )}
          </Section>
          {canDecide && detail.note && (
            <Section label="Review">
              <ReviewPanel
                detail={detail}
                currentBody={draft.draft?.body ?? detail.note.markdown}
                onUseRevision={(body) => {
                  const base = detail.note?.markdown ?? "";
                  draft.save({ body, base: draft.draft?.base ?? base });
                }}
                onUseTarget={setEdited}
              />
            </Section>
          )}
          <Section label="Project">
            <span>{l.project}</span>
          </Section>
          <Section label="Source">
            {l.source_session_id ? (
              <div className="ah-row ah-wrap" style={{ gap: 8 }}>
                <span className="ah-small">session</span>
                <IdChip id={l.source_session_id} kind="session" />
                <Link
                  className="ah-small ah-row"
                  style={{ gap: 4 }}
                  to={`/sessions/${l.source_session_id}?tab=timeline${l.source_event_id ? `&event=${l.source_event_id}` : ""}`}
                >
                  Open at that moment
                  <Icon name="arrow-right" size="sm" />
                </Link>
              </div>
            ) : (
              <span className="ah-small ah-subtle">No source session recorded.</span>
            )}
          </Section>
          {canDecide ? (
            <Section label="Target in brain/" labelFor={targetId}>
              <input
                id={targetId}
                className="ah-input ah-mono"
                list={choicesId}
                value={target}
                spellCheck={false}
                style={{ width: "100%", maxWidth: 420 }}
                aria-describedby={`${targetId}-help`}
                onChange={(event) => {
                  setEdited(event.target.value);
                }}
              />
              <datalist id={choicesId}>
                {detail.target_choices.map((choice) => (
                  <option key={choice} value={choice} />
                ))}
              </datalist>
              <div id={`${targetId}-help`} className="ah-small ah-subtle" style={{ marginTop: 6 }}>
                A folder (the note keeps its name) or a full <span className="ah-mono">.md</span>{" "}
                path, relative to <span className="ah-mono">brain/</span>.
              </div>
            </Section>
          ) : (
            l.brain_path && (
              <Section label="In the brain">
                <span className="ah-mono ah-small">brain/{l.brain_path}</span>
              </Section>
            )
          )}
          {prUrl && (
            <Section label="Pull request">
              <PullRequestLink url={prUrl} />
            </Section>
          )}
          {(l.decided_at ?? l.rejection_reason) && (
            <Section label="Decision">
              <div className="ah-stack" style={{ gap: 4 }}>
                {l.decided_at && (
                  <span className="ah-small ah-muted">
                    <Time iso={l.decided_at} absolute />
                    {l.decided_by ? ` by ${l.decided_by}` : ""}
                  </span>
                )}
                {l.rejection_reason && <span className="ah-small">{l.rejection_reason}</span>}
              </div>
            </Section>
          )}
        </div>
      </div>
      <div
        style={{
          borderTop: "1px solid var(--border)",
          padding: "12px 28px",
          background: "var(--surface)",
        }}
      >
        {result && (
          <div role="status" className="ah-stack" style={{ gap: 2, marginBottom: 10 }}>
            <b style={{ fontWeight: 600 }}>Pull request opened</b>
            <PullRequestLink url={result.pr_url} />
            <span className="ah-small ah-subtle">
              Nothing changes in the brain until you merge it.
            </span>
          </div>
        )}
        <div className="ah-row" style={{ gap: 8 }}>
          <Button
            variant="primary"
            icon="check"
            disabled={!canDecide || target.trim() === ""}
            title={blocked ?? undefined}
            onClick={() => {
              decide.reset();
              setDeciding("accept");
            }}
          >
            Accept
          </Button>
          <Button
            icon="x"
            disabled={!canDecide}
            title={blocked ?? undefined}
            onClick={() => {
              decide.reset();
              setDeciding("reject");
            }}
          >
            Reject
          </Button>
          <Button variant="ghost" icon="clock" phase="P3">
            Snooze 7 d
          </Button>
        </div>
        {blocked && state === "proposed" && !result ? (
          <div style={{ marginTop: 10 }}>
            <Banner tone="warning" boxed>
              <b style={{ fontWeight: 600 }}>Cannot be decided here.</b> {blocked}
            </Banner>
          </div>
        ) : (
          <div className="ah-small ah-subtle" style={{ marginTop: 8 }}>
            {blocked ??
              "Accept or reject opens a pull request in the hub; the brain changes when you merge it."}
          </div>
        )}
      </div>
      {deciding && (
        <DecideDialog
          action={deciding}
          title={l.text}
          hubRepo={hubRepo}
          notePath={l.note_path ?? null}
          target={target.trim()}
          edited={noteBody !== undefined}
          pending={decide.isPending}
          error={decide.error}
          onConfirm={confirm}
          onCancel={() => {
            setDeciding(null);
          }}
        />
      )}
    </section>
  );
}
