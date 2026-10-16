import { useId, useState } from "react";
import type { ReactNode } from "react";
import { Link, Navigate, useParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Button,
  CodeBlock,
  ConfirmDialog,
  DataTable,
  EmptyState,
  Icon,
  PathText,
  ProblemError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Time,
  copyText,
  useCopied,
  type IconName,
  type Status,
} from "../../components";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtClock, fmtInt } from "../../lib/format";
import { usePreferences, type ThemeChoice } from "../../lib/preferences";
import { useCollectorState } from "../../shell/GlobalStream";
import { NotFoundBody } from "../not-found";
import { RegisterHubForm } from "./RegisterHubForm";
import { useCollectorStatus, useHubs, useRemoveHub, useSettings } from "./queries";

type HubView = components["schemas"]["HubView"];
type EventSource = components["schemas"]["EventSource"];
type LockState = components["schemas"]["LockState"];

const SECTIONS: readonly { id: string; label: string; icon: IconName }[] = [
  { id: "hubs", label: "Hubs", icon: "warehouse" },
  { id: "collector", label: "Collector", icon: "server" },
  { id: "privacy", label: "Privacy", icon: "lock" },
  { id: "appearance", label: "Appearance", icon: "monitor" },
  { id: "about", label: "About", icon: "info" },
];

/** Spec 01 names the privacy section `/settings/retention`; Phase 2 has no retention setting. */
const ALIASES: Readonly<Record<string, string>> = { retention: "privacy" };

const LOCK: Record<LockState, { label: string; tone?: "waiting" }> = {
  in_sync: { label: "in sync" },
  drift: { label: "drift", tone: "waiting" },
  sync_pending: { label: "sync pending", tone: "waiting" },
  not_adopted: { label: "not adopted" },
};

const ALL_SOURCES: readonly EventSource[] = [
  "claude_code",
  "transcript",
  "executor",
  "otel",
  "github",
  "linear",
];

function Section({
  title,
  sub,
  action,
  children,
}: {
  title: string;
  sub?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="ah-stack" style={{ gap: 12 }} aria-label={title}>
      <div className="ah-row" style={{ gap: 12, alignItems: "flex-end" }}>
        <div className="ah-grow">
          <h2 className="ah-h2">{title}</h2>
          {sub && (
            <p className="ah-muted ah-small" style={{ margin: "4px 0 0" }}>
              {sub}
            </p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "220px 1fr",
        gap: 16,
        padding: "14px 0",
        borderTop: "1px solid var(--border)",
        alignItems: "start",
      }}
    >
      <div>
        <div style={{ fontWeight: 500 }}>{label}</div>
        {hint && <div className="ah-small ah-muted">{hint}</div>}
      </div>
      <div className="ah-stack" style={{ gap: 6, alignItems: "flex-start" }}>
        {children}
      </div>
    </div>
  );
}

/* ---------- Hubs: register and remove are the only writes of Phase 2 ---------- */

function HubPlatform({ hub }: { hub: HubView }) {
  const lock = hub.lock_state ? LOCK[hub.lock_state] : null;
  return (
    <span className="ah-stack" style={{ gap: 2 }}>
      <span className="ah-small">
        {hub.platform_pin ?? "not pinned"} pinned · lock {hub.lock_version ?? "none"}
        {lock && (
          <>
            {" · "}
            <span style={lock.tone ? { color: "var(--waiting)", fontWeight: 500 } : undefined}>
              {lock.label}
            </span>
          </>
        )}
      </span>
      {hub.warnings.map((warning) => (
        <span key={warning} className="ah-small" style={{ color: "var(--waiting)" }}>
          {warning}
        </span>
      ))}
    </span>
  );
}

function HubValidity({ hub }: { hub: HubView }) {
  if (hub.valid) return <StatusBadge status="done" label="valid" />;
  const first = hub.validation_errors[0];
  return (
    <span className="ah-stack" style={{ gap: 2 }}>
      <StatusBadge status="failed" label="invalid" />
      {first && (
        <span className="ah-small" style={{ color: "var(--failed)", whiteSpace: "normal" }}>
          {first.pointer ? `${first.pointer}: ` : ""}
          {first.message}
        </span>
      )}
    </span>
  );
}

function Hubs() {
  const hubs = useHubs();
  const remove = useRemoveHub();
  const [removing, setRemoving] = useState<HubView | null>(null);
  const now = useNow(30_000);
  const formId = useId();
  const name = (hub: HubView) => hub.project ?? hub.path;
  return (
    <Section
      title="Hubs"
      sub="Hub folders this app reads. Each hub is one project; nothing is written to them."
      action={
        <Button
          variant="primary"
          icon="plus"
          onClick={() => {
            document.getElementById(formId)?.focus();
          }}
        >
          Add hub
        </Button>
      }
    >
      {hubs.isError ? (
        <ProblemError
          title={hubs.error.title}
          detail={hubs.error.detail}
          status={hubs.error.status}
          onRetry={() => void hubs.refetch()}
        />
      ) : (
        <DataTable<HubView>
          caption="Registered hubs"
          rowKey={(hub) => hub.id}
          rows={hubs.data?.items ?? []}
          loading={hubs.isPending}
          empty={<EmptyState icon="warehouse" title="No hub registered yet." />}
          columns={[
            {
              id: "project",
              label: "Project",
              render: (hub) => (
                <span className="ah-stack" style={{ gap: 0 }}>
                  <b>{hub.project ?? "—"}</b>
                  <span className="ah-small ah-muted">
                    {hub.repos.length} repo{hub.repos.length === 1 ? "" : "s"} · added{" "}
                    <Time
                      iso={hub.added_at}
                      ago={Math.max(1, (now - Date.parse(hub.added_at)) / 1000)}
                    />
                  </span>
                </span>
              ),
            },
            { id: "path", label: "Path", render: (hub) => <PathText path={hub.path} max={32} /> },
            { id: "valid", label: "hub.json", render: (hub) => <HubValidity hub={hub} /> },
            { id: "pin", label: "Platform", render: (hub) => <HubPlatform hub={hub} /> },
            {
              id: "remove",
              label: <span className="ah-sr">Actions</span>,
              width: 110,
              align: "right",
              render: (hub) => (
                <Button
                  size="sm"
                  variant="ghost"
                  icon="x"
                  aria-label={`Remove ${name(hub)}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    remove.reset();
                    setRemoving(hub);
                  }}
                >
                  Remove
                </Button>
              ),
            },
          ]}
          footer={
            <span>Remove asks first. Its stored events stay; the hub folder is not touched.</span>
          }
        />
      )}
      <div className="ah-card ah-pad ah-stack" style={{ gap: 10 }}>
        <b className="ah-small">Add hub</b>
        <RegisterHubForm
          label="Hub path"
          helper="The absolute path of the folder that contains hub.json."
          placeholder="/home/you/code/agent-hub-hub"
          inputId={formId}
        />
        <Link className="ah-small" to="/welcome">
          Open the setup checklist
        </Link>
      </div>
      {removing && (
        <ConfirmDialog
          title={`Stop reading ${name(removing)}?`}
          consequences={[
            "Its stored events stay in the store.",
            "The hub folder is not touched.",
            "Register it again at any time.",
          ]}
          confirmLabel={remove.isPending ? "Removing…" : "Remove hub"}
          onCancel={() => {
            setRemoving(null);
          }}
          onConfirm={() => {
            remove.mutate(removing.id, {
              onSuccess: () => {
                setRemoving(null);
              },
            });
          }}
        >
          {remove.error && (
            <span style={{ color: "var(--failed)" }} role="alert">
              {remove.error.detail ?? remove.error.title}
            </span>
          )}
        </ConfirmDialog>
      )}
    </Section>
  );
}

/* ---------- Collector: hub web's own status ---------- */

const SOURCE_HEALTH: Record<"fresh" | "stale" | "never" | "none", [Status, string]> = {
  fresh: ["done", "ok"],
  stale: ["waiting", "delayed"],
  never: ["idle", "no events yet"],
  none: ["idle", "not connected"],
};

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="ah-overline">{label}</div>
      {children}
    </div>
  );
}

function Collector() {
  const status = useCollectorStatus();
  const settings = useSettings();
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();
  const now = useNow(1000);
  const address = `127.0.0.1:${String(settings.data?.port ?? 7420)}`;
  const data = status.data;
  const lastAgo = data?.last_event_at
    ? fmtAgo(Math.max(1, (now - Date.parse(data.last_event_at)) / 1000))
    : "none yet";
  const badge =
    state === "offline" ? (
      <StatusBadge status="failed" label={`Offline since ${fmtClock(asOf, tz)}`} />
    ) : state === "delayed" ? (
      <StatusBadge status="waiting" label="Delayed" />
    ) : (
      <StatusBadge status="done" label={`Connected · last event ${lastAgo}`} />
    );
  const rows = ALL_SOURCES.map((source) => {
    const found = data?.sources.find((s) => s.source === source);
    return { source, state: found?.state ?? ("none" as const), last: found?.last_event_at ?? null };
  });
  return (
    <Section
      title="Collector"
      sub="hub web receives Claude Code hook, transcript and executor events and stores them on this machine."
      action={badge}
    >
      {status.isError ? (
        <ProblemError
          title={status.error.title}
          detail={status.error.detail}
          status={status.error.status}
          onRetry={() => void status.refetch()}
        />
      ) : (
        <div className="ah-card ah-pad">
          {data ? (
            <div
              style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 16 }}
            >
              <Stat label="Database">
                <PathText path={data.db_path} max={26} />
              </Stat>
              <Stat label="Address">
                <span className="ah-mono">{address}</span>
              </Stat>
              <Stat label="Events stored">
                <span className="ah-mono" style={{ fontSize: 18 }}>
                  {fmtInt(data.events_total)}
                </span>
              </Stat>
              <Stat label="Started">
                <span className="ah-small">
                  <Time iso={data.started_at} absolute />
                </span>
              </Stat>
              <Stat label="Hooks received">
                <span className="ah-num">{fmtInt(data.hooks_received)}</span>
              </Stat>
              <Stat label="Appended · duplicates">
                <span className="ah-num">
                  {fmtInt(data.appended)} · {fmtInt(data.duplicates)}
                </span>
              </Stat>
              <Stat label="Transcripts refused">
                <span className="ah-num">{fmtInt(data.transcript_refused)}</span>
              </Stat>
              <Stat label="Transcript lines skipped">
                <span className="ah-num">{fmtInt(data.transcript_lines_skipped)}</span>
              </Stat>
            </div>
          ) : (
            <Skeleton lines={2} height={16} />
          )}
          <div className="ah-row" style={{ gap: 10, marginTop: 14 }}>
            <span className="ah-small ah-muted" style={{ width: 110 }}>
              Start command
            </span>
            <div style={{ minWidth: 360 }}>
              <CodeBlock code="hub web" />
            </div>
          </div>
        </div>
      )}
      <DataTable
        caption="Sources"
        rowKey={(row) => row.source}
        rows={rows}
        loading={status.isPending}
        columns={[
          {
            id: "source",
            label: "Source",
            render: (row) => <span className="ah-mono">{row.source}</span>,
          },
          {
            id: "health",
            label: "Health",
            render: (row) => {
              const [tone, label] = SOURCE_HEALTH[row.state];
              return <StatusBadge status={tone} label={label} />;
            },
          },
          {
            id: "last",
            label: "Last event",
            render: (row) =>
              row.last ? (
                <span className="ah-small">
                  <Time iso={row.last} ago={Math.max(1, (now - Date.parse(row.last)) / 1000)} />
                </span>
              ) : (
                <span className="ah-subtle">—</span>
              ),
          },
        ]}
        footer={
          <span>
            ok = events arrive as expected · delayed = no recent event · OpenTelemetry, GitHub and
            Linear are not connected in this version.
          </span>
        }
      />
    </Section>
  );
}

/* ---------- Privacy ---------- */

function Privacy() {
  const settings = useSettings();
  if (settings.isError) {
    return (
      <Section title="Privacy" sub="What is kept, and what is never read.">
        <ProblemError
          title={settings.error.title}
          detail={settings.error.detail}
          status={settings.error.status}
          onRetry={() => void settings.refetch()}
        />
      </Section>
    );
  }
  const data = settings.data;
  return (
    <Section title="Privacy" sub="What is kept, and what is never read.">
      <div className="ah-card" style={{ padding: "0 16px" }}>
        <Row label="What is stored" hint="Every source">
          <b>{data?.metadata_only === false ? "Content may be stored." : "Metadata only."}</b>
          <span className="ah-small ah-muted">
            No prompt, message, reasoning, tool output, file content or diff is stored. Short texts
            such as a Bash command are kept redacted and truncated.
          </span>
        </Row>
        <Row label="Redaction rules" hint="Applied before storage">
          {data ? (
            <>
              <span className="ah-small">
                Ruleset <span className="ah-mono">{data.redaction_ruleset}</span>
              </span>
              <span className="ah-row ah-wrap" style={{ gap: 6 }}>
                {data.redaction_kinds.map((kind) => (
                  <span key={kind} className="ah-chip" style={{ cursor: "default" }}>
                    <Icon name="eye-off" size="sm" />
                    <span className="ah-mono">{kind}</span>
                  </span>
                ))}
              </span>
            </>
          ) : (
            <Skeleton width={320} />
          )}
          <span className="ah-small ah-muted">
            Redaction runs before anything is stored. Rules are shown by name; their patterns are
            not.
          </span>
        </Row>
        <Row label="Personal memory">
          <span className="ah-row" style={{ gap: 8 }}>
            <Icon name="lock" size="sm" />
            <b>Personal memory (brain/auto/workspace/) is never read.</b>
          </span>
        </Row>
        <Row label="Network">
          <span className="ah-small">
            hub web listens on 127.0.0.1 only and sends nothing off this machine.
          </span>
        </Row>
      </div>
    </Section>
  );
}

/* ---------- Appearance ---------- */

function Appearance() {
  const { theme, setTheme, tz, setTz, shakeToSession, setShakeToSession } = usePreferences();
  const shakeField = useId();
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return (
    <Section title="Appearance" sub="Applied instantly and stored for this browser.">
      <div className="ah-card" style={{ padding: "0 16px" }}>
        <Row label="Theme">
          <SegmentedControl
            label="Theme"
            value={theme}
            onChange={(id) => {
              setTheme(id as ThemeChoice);
            }}
            options={[
              { id: "system", label: "System", icon: "monitor" },
              { id: "light", label: "Light", icon: "sun" },
              { id: "dark", label: "Dark", icon: "moon" },
            ]}
          />
        </Row>
        <Row label="Time zone" hint="Also in the top bar">
          <SegmentedControl
            label="Time zone"
            value={tz}
            onChange={(id) => {
              setTz(id === "utc" ? "utc" : "local");
            }}
            options={[
              { id: "local", label: `Local · ${zone}` },
              { id: "utc", label: "UTC" },
            ]}
          />
        </Row>
        <Row
          label="Shake to start a session"
          hint="Shake the mouse on a project screen to open New session with a screenshot"
        >
          <label htmlFor={shakeField} className="ah-row ah-small" style={{ gap: 6 }}>
            <input
              id={shakeField}
              type="checkbox"
              className="ah-check"
              checked={shakeToSession}
              onChange={(event) => {
                setShakeToSession(event.target.checked);
              }}
            />
            Shake to start a session
          </label>
        </Row>
      </div>
    </Section>
  );
}

/* ---------- About ---------- */

function About() {
  const settings = useSettings();
  const hubs = useHubs();
  const status = useCollectorStatus();
  const [copied, markCopied] = useCopied();
  const data = settings.data;
  const pins = [...new Set((hubs.data?.items ?? []).map((hub) => hub.platform_pin ?? "none"))];
  const projects = (hubs.data?.items ?? []).map((hub) => hub.project ?? hub.path);
  const server = data ? `${data.running_version} · 127.0.0.1:${String(data.port)}` : "…";
  const copy = () => {
    // Versions and source health only: no paths, no content.
    copyText(
      JSON.stringify(
        {
          app: data?.running_version ?? null,
          api: "/api/v1",
          platform_pins: pins,
          redaction_ruleset: data?.redaction_ruleset ?? null,
          sources: (status.data?.sources ?? []).map(({ source, state }) => ({ source, state })),
        },
        null,
        2,
      ),
    );
    markCopied();
  };
  return (
    <Section
      title="About"
      action={
        <Button icon={copied ? "check" : "copy"} onClick={copy}>
          {copied ? "Copied" : "Copy diagnostics"}
        </Button>
      }
    >
      {settings.isError ? (
        <ProblemError
          title={settings.error.title}
          detail={settings.error.detail}
          status={settings.error.status}
          onRetry={() => void settings.refetch()}
        />
      ) : (
        <div className="ah-card" style={{ padding: "0 16px" }}>
          <Row label="App and server">
            <span className="ah-mono">{server}</span>
          </Row>
          <Row label="API">
            <span className="ah-mono">/api/v1</span>
          </Row>
          <Row label="Platform (pinned)">
            <span className="ah-mono">
              {pins.length ? `${pins.join(", ")} · ${projects.join(", ")}` : "no hub registered"}
            </span>
          </Row>
          <Row label="Prices" hint="For cost estimates">
            <span className="ah-small">
              {data?.prices_as_of ? `Price table dated ${data.prices_as_of}` : "No price table"}
            </span>
          </Row>
          <Row label="Hub registry">
            {data ? <PathText path={data.registry_path} max={64} /> : <Skeleton width={240} />}
          </Row>
        </div>
      )}
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        Diagnostics contain versions and source health only: no paths, no content.
      </p>
    </Section>
  );
}

const BODIES: Readonly<Record<string, () => ReactNode>> = {
  hubs: () => <Hubs />,
  collector: () => <Collector />,
  privacy: () => <Privacy />,
  appearance: () => <Appearance />,
  about: () => <About />,
};

/** Settings (spec 01, D20): Hubs, Collector, Privacy, Appearance, About. */
export function SettingsScreen() {
  const { section = "hubs" } = useParams();
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();
  const alias = ALIASES[section];
  if (alias !== undefined) return <Navigate to={`/settings/${alias}`} replace />;
  const body = BODIES[section];
  if (body === undefined) return <NotFoundBody />;
  return (
    <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <div className="ah-row" style={{ gap: 12 }}>
        <h1 className="ah-h1">Settings</h1>
        {state === "offline" && <AsOfStamp stale time={fmtClock(asOf, tz)} />}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "220px minmax(0, 1fr)",
          gap: 32,
          alignItems: "start",
        }}
      >
        <nav aria-label="Settings sections" className="ah-stack" style={{ gap: 2 }}>
          {SECTIONS.map((s) => (
            <Link
              key={s.id}
              to={`/settings/${s.id}`}
              className="ah-nav-item"
              aria-current={section === s.id ? "page" : undefined}
            >
              <Icon name={s.icon} />
              <span className="ah-nav-label">{s.label}</span>
              {s.id === "collector" && state === "offline" && (
                <span className="ah-nav-count" data-tone="failed" aria-hidden="true">
                  !
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div style={{ minWidth: 0 }}>{body()}</div>
      </div>
    </div>
  );
}
