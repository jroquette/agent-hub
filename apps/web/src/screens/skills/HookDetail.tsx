/* A hook as configured (D4, AC-164.22): its command is inert text, with no button that runs it;
 * its event, matcher and state are facts of the About rail. */
import "./SkillDetail.css";

import type { components } from "../../api/schema";
import { RailFact } from "./RailFact";
import { HookStateTags } from "./SkillCard";

type HookFacts = components["schemas"]["HookFacts"];

/** The hook's facts, as rows of the About rail. */
export function HookFactsList({ hook }: { hook: HookFacts }) {
  return (
    <>
      <RailFact term="Event" mono>
        {hook.event}
      </RailFact>
      <RailFact term="Matcher" mono={hook.matcher !== null}>
        {hook.matcher ?? "Every tool (no matcher)"}
      </RailFact>
      <RailFact term="Type" mono>
        {hook.type}
      </RailFact>
      {hook.timeout !== null && <RailFact term="Timeout">{hook.timeout} s</RailFact>}
      <RailFact term="State">
        <span className="ah-row ah-wrap" style={{ gap: 6 }}>
          <HookStateTags active={hook.active} state={hook.state} />
          {hook.state === "synced" && <span className="ah-skill-tag">Synced</span>}
        </span>
      </RailFact>
    </>
  );
}

/** The Command card of a hook's detail. */
export function HookDetail({ hook }: { hook: HookFacts }) {
  return (
    <section className="ah-card ah-skill-section" aria-labelledby="skill-hook">
      <div className="ah-card-head">
        <h2 id="skill-hook" className="ah-h3">
          Command
        </h2>
      </div>
      <div className="ah-card-body">
        {hook.command === null ? (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            No command: this hook is not a command hook.
          </p>
        ) : (
          <>
            {/* A scrolling region must take keyboard focus (axe scrollable-region-focusable). */}
            {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
            <pre className="ah-skill-raw" tabIndex={0}>
              <code>{hook.command}</code>
            </pre>
            <p className="ah-small ah-muted" style={{ margin: "6px 0 0" }}>
              Shown as text: Claude Code runs it on the event; this page never runs it.
            </p>
          </>
        )}
      </div>
    </section>
  );
}
