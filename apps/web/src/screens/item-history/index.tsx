import "./ItemHistory.css";

import { useId, useMemo, useState } from "react";

import {
  Banner,
  Button,
  DataTable,
  EmptyState,
  Icon,
  PathText,
  ProblemError,
  Skeleton,
  Time,
} from "../../components";
import { useNow } from "../../lib/clock";
import { Compare } from "./Compare";
import { authorWords, canRestore, originIcon, originWords, shortHash, stateNotice } from "./model";
import { RestoreDialog, type RestoreOutcome } from "./RestoreDialog";
import {
  useItemVersions,
  type HistoryTarget,
  type ItemVersion,
  type ItemVersionPage,
} from "./queries";

/* The History panel (AGH-295, AC-295.29): the versions agent-hub recorded of an item's unit,
 * newest first, with what the disk holds now. It reads nothing until it is opened. */

/** What the items sharing one unit are called (only a hook file holds more than one). */
const UNIT_ITEMS: Record<ItemVersionPage["unit_kind"], string> = {
  skill: "skills",
  agent: "agents",
  hook: "hooks",
  workflow: "workflows",
  scenario: "scenarios",
};

function targetName(target: HistoryTarget): string {
  return target.kind === "item" ? target.item.name : target.name;
}

function UnitLine({ page }: { page: ItemVersionPage }) {
  return (
    <p className="ah-history-unit ah-small ah-muted">
      <span>Versions of</span>
      <span className="ah-mono">
        <PathText path={page.unit_path} max={64} />
      </span>
      {page.shared_by > 1 && (
        <span>
          Shared by {page.shared_by} {UNIT_ITEMS[page.unit_kind]}
        </span>
      )}
      {page.managed && (
        <span className="ah-badge ah-badge-quiet">
          <Icon name="lock" />
          Managed by hub.lock
        </span>
      )}
    </p>
  );
}

function VersionsBody({ target }: { target: HistoryTarget }) {
  const versions = useItemVersions(target, true);
  const now = useNow(60_000);
  const items = useMemo(
    () => versions.data?.pages.flatMap((page) => page.items) ?? [],
    [versions.data],
  );
  const byId = useMemo(() => new Map(items.map((v) => [v.id, v])), [items]);
  // Two versions at most, the last two picked; Compare orders them older then newer.
  const [picked, setPicked] = useState<string[]>([]);
  const [comparing, setComparing] = useState<[ItemVersion, ItemVersion] | null>(null);
  const [restoring, setRestoring] = useState<ItemVersion | null>(null);
  const [restored, setRestored] = useState<RestoreOutcome | null>(null);
  const compareId = useId();
  const toggle = (id: string) => {
    setPicked((was) => (was.includes(id) ? was.filter((p) => p !== id) : [...was, id].slice(-2)));
  };
  const startCompare = () => {
    // The list is newest first: the later row is the older version.
    const [a, b] = picked
      .map((id) => items.findIndex((v) => v.id === id))
      .filter((i) => i >= 0)
      .sort((x, y) => y - x)
      .map((i) => items[i]);
    if (a && b) setComparing([a, b]);
  };

  if (versions.isPending) {
    return (
      <div role="status" aria-label="Loading the history" aria-busy="true">
        <Skeleton lines={3} />
      </div>
    );
  }
  // A failed refresh keeps the list it already shows; only a first read without data replaces it.
  if (versions.isError && versions.data === undefined) {
    if (versions.error.status === 404) {
      return (
        <EmptyState icon="circle-dashed" title="No history for this item">
          It has no file of its own in this hub (a link out of the hub, or a built-in), so agent-hub
          keeps no versions of it.
        </EmptyState>
      );
    }
    return (
      <ProblemError
        title="Could not load the history"
        detail={versions.error.detail}
        status={versions.error.status}
        onRetry={() => void versions.refetch()}
        compact
      />
    );
  }

  const page = versions.data.pages[0];
  if (page === undefined) return null;
  const refreshFailed = versions.isError ? versions.error : null;
  const notice = stateNotice(page.state);
  const restorable = canRestore(page.state);
  return (
    <div className="ah-stack ah-history-body">
      <UnitLine page={page} />
      {refreshFailed && (
        <ProblemError
          title="Could not refresh the history"
          detail={refreshFailed.detail}
          status={refreshFailed.status}
          onRetry={() => void versions.refetch()}
          compact
        />
      )}
      {restored && (
        <Banner
          tone={restored.warning ? "warning" : "info"}
          icon={restored.warning ? "triangle-alert" : "circle-check"}
          boxed
          onDismiss={() => {
            setRestored(null);
          }}
        >
          {restored.text}
        </Banner>
      )}
      {notice && (
        <Banner tone="warning" icon={notice.icon} boxed>
          <strong>{notice.title}</strong>
          <span className="ah-history-notice-detail">{notice.detail}</span>
        </Banner>
      )}
      {items.length === 0 ? (
        <EmptyState icon="clock" title="No versions yet">
          agent-hub records the first version the next time it reads this item and can store it.
        </EmptyState>
      ) : (
        <DataTable<ItemVersion>
          caption={`Versions of ${targetName(target)}`}
          density="compact"
          rows={items}
          rowKey={(v) => v.id}
          columns={[
            {
              id: "pick",
              label: <span className="ah-sr">Compare</span>,
              width: 36,
              render: (v) => (
                <input
                  type="checkbox"
                  className="ah-check"
                  checked={picked.includes(v.id)}
                  onChange={() => {
                    toggle(v.id);
                  }}
                  aria-label={`Select ${shortHash(v.content_hash)} (${originWords(v, byId)}) to compare`}
                />
              ),
            },
            {
              id: "origin",
              label: "Origin",
              render: (v) => (
                <span className="ah-row ah-history-origin">
                  <Icon name={originIcon(v)} size="sm" />
                  {originWords(v, byId)}
                </span>
              ),
            },
            { id: "author", label: "Author", render: (v) => authorWords(v) },
            {
              id: "when",
              label: "When",
              width: 110,
              render: (v) => (
                <Time
                  iso={v.recorded_at}
                  ago={Math.max(0, (now - Date.parse(v.recorded_at)) / 1000)}
                />
              ),
            },
            {
              id: "hash",
              label: "Hash",
              width: 100,
              render: (v) => (
                <span className="ah-mono" title={v.content_hash}>
                  {shortHash(v.content_hash)}
                </span>
              ),
            },
            {
              id: "restore",
              label: <span className="ah-sr">Restore</span>,
              width: 110,
              align: "right",
              render: (v) => (
                <Button
                  size="sm"
                  icon="rotate-ccw"
                  disabled={!restorable}
                  title={restorable ? undefined : "Restore is off: see the notice above."}
                  aria-label={`Restore ${shortHash(v.content_hash)} (${originWords(v, byId)})`}
                  onClick={() => {
                    setRestored(null);
                    setRestoring(v);
                  }}
                >
                  Restore
                </Button>
              ),
            },
          ]}
        />
      )}
      {versions.hasNextPage && (
        <div>
          <Button
            size="sm"
            disabled={versions.isFetchingNextPage}
            onClick={() => void versions.fetchNextPage()}
          >
            Load more
          </Button>
        </div>
      )}
      {items.length > 1 && (
        <div className="ah-history-tools">
          <Button
            size="sm"
            icon="git-compare"
            disabled={picked.length !== 2}
            id={compareId}
            onClick={startCompare}
          >
            Compare
          </Button>
          <span className="ah-small ah-muted" aria-live="polite">
            {picked.length === 2
              ? "2 versions selected."
              : "Select two versions to compare, any two."}
          </span>
        </div>
      )}
      {restoring && (
        <RestoreDialog
          target={target}
          version={restoring}
          page={page}
          onClose={() => {
            setRestoring(null);
          }}
          onRestored={(outcome) => {
            setRestoring(null);
            setRestored(outcome);
          }}
        />
      )}
      {comparing && (
        <Compare
          target={target}
          older={comparing[0]}
          newer={comparing[1]}
          onClose={() => {
            setComparing(null);
            // Back to the control that opened it (it stays in the page).
            document.getElementById(compareId)?.focus();
          }}
        />
      )}
    </div>
  );
}

/** The History panel of a Toolkit item or a hub workflow: a fold that reads on first open. */
export function HistoryPanel({ target }: { target: HistoryTarget }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <section className="ah-card ah-history" aria-labelledby={`${id}-title`}>
      <div className="ah-card-head ah-history-head">
        <h2 id={`${id}-title`} className="ah-h3 ah-grow">
          History
        </h2>
        <Button
          size="sm"
          variant="ghost"
          icon={open ? "chevron-up" : "chevron-down"}
          aria-expanded={open}
          aria-controls={`${id}-body`}
          onClick={() => {
            setOpen((was) => !was);
          }}
        >
          {open ? "Hide history" : "Show history"}
        </Button>
      </div>
      {open && (
        <div id={`${id}-body`} className="ah-card-body">
          <VersionsBody target={target} />
        </div>
      )}
    </section>
  );
}
