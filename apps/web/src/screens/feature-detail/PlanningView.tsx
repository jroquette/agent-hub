import { Fragment } from "react";
import type { ReactNode } from "react";

import type { components } from "../../api/schema";
import { Banner, Icon } from "../../components";
import { linearHref } from "../../lib/safeHref";

type TicketRow = components["schemas"]["TicketRow"];
type TicketPlan = components["schemas"]["TicketPlan"];
type ExternalBlocker = components["schemas"]["ExternalBlocker"];

/** The element id of a ticket's row, the target of every in-page ticket link. */
export function ticketAnchor(ref: string): string {
  return `ticket-${ref.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

/** A link that opens a Linear issue in a new tab (AC-136.29); plain text when the url is unsafe. */
export function LinearLink({
  id,
  url,
  label,
  title,
}: {
  id: string;
  url: string | null;
  label?: string | undefined;
  title?: string | undefined;
}) {
  const href = linearHref(url);
  if (href === null) {
    return (
      <span className="ah-issue" title={title ?? `${id} · no Linear link`}>
        {id}
      </span>
    );
  }
  return (
    <a
      className="ah-issue"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      title={title ?? `${id} · opens in Linear`}
    >
      {id}
      <Icon name="arrow-up-right" />
      {!label && <span className="ah-sr"> (opens in Linear in a new tab)</span>}
    </a>
  );
}

/**
 * A ticket named by `ref`: an in-page link to its row when it is one of the feature's tickets, a
 * Linear link when it is an external blocker with a safe url, else plain text.
 */
export function TicketRef({
  id,
  rows,
  external,
  label,
  title,
}: {
  id: string;
  rows: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  label?: string | undefined;
  title?: string | undefined;
}) {
  const row = rows.find((r) => r.ref === id);
  if (row) {
    return (
      <a
        className="ah-mono"
        href={`#${ticketAnchor(id)}`}
        aria-label={label}
        title={title ?? row.title ?? undefined}
      >
        {id}
      </a>
    );
  }
  const outside = external.find((b) => b.id === id);
  if (outside) {
    return (
      <LinearLink
        id={id}
        url={outside.url}
        label={label}
        title={title ?? `${id}${outside.title ? ` · ${outside.title}` : ""} · outside this feature`}
      />
    );
  }
  return <span className="ah-mono">{id}</span>;
}

function RefList({
  refs,
  rows,
  external,
  separator = ", ",
}: {
  refs: readonly string[];
  rows: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  separator?: ReactNode;
}) {
  return (
    <>
      {refs.map((ref, i) => (
        <Fragment key={ref}>
          {i > 0 && separator}
          <TicketRef id={ref} rows={rows} external={external} />
        </Fragment>
      ))}
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="ah-stack" style={{ gap: 6 }} aria-label={title}>
      <h3 className="ah-small" style={{ margin: 0, fontWeight: 600 }}>
        {title}
      </h3>
      {children}
    </section>
  );
}

export interface PlanningViewProps {
  tickets: readonly TicketRow[];
  planning: TicketPlan;
}

/**
 * The planning of the feature's tickets (AC-136.30): what can start now, the parallel groups as
 * numbered layers, the recommended order, the critical path, and banners for dependency cycles,
 * blockers outside the feature and the server's warnings.
 */
export function PlanningView({ tickets, planning }: PlanningViewProps) {
  const external = planning.external_blockers;
  const refs = (list: readonly string[]) => (
    <RefList refs={list} rows={tickets} external={external} />
  );
  const titleOf = (ref: string) => tickets.find((r) => r.ref === ref)?.title;
  return (
    <section className="ah-card ah-pad ah-stack" style={{ gap: 14 }} aria-labelledby="planning-h">
      <h2 id="planning-h" className="ah-h3" style={{ margin: 0 }}>
        Planning
      </h2>
      {planning.cycles.length > 0 && (
        <Banner tone="error" icon="octagon-x">
          <b style={{ fontWeight: 500 }}>
            Dependency cycle{planning.cycles.length === 1 ? "" : "s"}:
          </b>{" "}
          {planning.cycles.map((cycle, i) => (
            <Fragment key={cycle.join(">")}>
              {i > 0 && "; "}
              <RefList refs={cycle} rows={tickets} external={external} separator=" → " />
            </Fragment>
          ))}
          . These tickets wait on each other and are left out of the layers; break the cycle in the
          plan or in Linear.
        </Banner>
      )}
      {external.length > 0 && (
        <Banner tone="warning" icon="triangle-alert">
          <b style={{ fontWeight: 500 }}>Blocked from outside this feature:</b>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {external.map((b) => (
              <li key={b.id}>
                <LinearLink id={b.id} url={b.url} />
                {b.title && ` · ${b.title}`} ·{" "}
                {b.done ? "done" : b.state ? `${b.state.name} (not done)` : "status unknown"}
              </li>
            ))}
          </ul>
        </Banner>
      )}
      {planning.warnings.length > 0 && (
        <Banner tone="info">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {planning.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Banner>
      )}
      <Section title="Can start now">
        {planning.can_start.length > 0 ? (
          <div className="ah-row ah-wrap" style={{ gap: 8 }}>
            {refs(planning.can_start)}
          </div>
        ) : (
          <span className="ah-small ah-muted">Nothing can start now.</span>
        )}
      </Section>
      <Section title="Parallel groups">
        {planning.layers.length > 0 ? (
          <ol className="ah-stack" style={{ gap: 4, margin: 0, paddingLeft: 0, listStyle: "none" }}>
            {planning.layers.map((layer, i) => (
              <li key={layer.join(",")} className="ah-row ah-wrap" style={{ gap: 8 }}>
                <span className="ah-small" style={{ fontWeight: 500, minWidth: 64 }}>
                  Layer {i + 1}
                </span>
                {refs(layer)}
              </li>
            ))}
          </ol>
        ) : (
          <span className="ah-small ah-muted">No ticket left to plan.</span>
        )}
      </Section>
      <Section title="Recommended order">
        {planning.order.length > 0 ? (
          <ol className="ah-small" style={{ margin: 0, paddingLeft: 22 }}>
            {planning.order.map((ref) => (
              <li key={ref}>
                <TicketRef id={ref} rows={tickets} external={external} />
                {titleOf(ref) && <span className="ah-muted"> · {titleOf(ref)}</span>}
              </li>
            ))}
          </ol>
        ) : (
          <span className="ah-small ah-muted">No ticket left to order.</span>
        )}
      </Section>
      <Section title="Critical path">
        {planning.critical_path.length > 0 ? (
          <div className="ah-small">
            <RefList
              refs={planning.critical_path}
              rows={tickets}
              external={external}
              separator=" → "
            />{" "}
            <span className="ah-muted">
              ({planning.critical_path.length} ticket
              {planning.critical_path.length === 1 ? "" : "s"}, the longest chain not done)
            </span>
          </div>
        ) : (
          <span className="ah-small ah-muted">No chain left: every ticket is done.</span>
        )}
      </Section>
    </section>
  );
}
