/* A hook as configured (D4, AC-164.22): its command is inert text, with no button that runs it. */
import "./SkillDetail.css";

import type { ReactNode } from "react";

import type { components } from "../../api/schema";
import { HookStateTags } from "./SkillCard";

type HookFacts = components["schemas"]["HookFacts"];

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="ah-skill-fact">
      <dt>{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export interface HookDetailProps {
  hook: HookFacts;
  /** The hub-relative file the hook is configured in. */
  sourcePath: string;
}

export function HookDetail({ hook, sourcePath }: HookDetailProps) {
  return (
    <section className="ah-card ah-skill-section" aria-labelledby="skill-hook">
      <div className="ah-card-head">
        <h2 id="skill-hook" className="ah-h3">
          Hook
        </h2>
      </div>
      <div className="ah-card-body ah-stack" style={{ gap: 12 }}>
        <dl className="ah-skill-facts">
          <Fact term="Event">
            <span className="ah-mono">{hook.event}</span>
          </Fact>
          <Fact term="Matcher">
            {hook.matcher ? (
              <span className="ah-mono">{hook.matcher}</span>
            ) : (
              "Every tool (no matcher)"
            )}
          </Fact>
          <Fact term="Type">
            <span className="ah-mono">{hook.type}</span>
          </Fact>
          {hook.timeout !== null && <Fact term="Timeout">{hook.timeout} s</Fact>}
          <Fact term="Source file">
            <span className="ah-mono">{sourcePath}</span>
          </Fact>
          <Fact term="State">
            <span className="ah-row ah-wrap" style={{ gap: 6 }}>
              <HookStateTags active={hook.active} state={hook.state} />
              {hook.state === "synced" && <span className="ah-skill-tag">Synced</span>}
            </span>
          </Fact>
        </dl>
        <div>
          <h3 className="ah-caption ah-muted" style={{ margin: "0 0 6px" }}>
            Command
          </h3>
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
      </div>
    </section>
  );
}
