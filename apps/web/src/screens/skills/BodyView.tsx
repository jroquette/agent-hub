/* An item's text (D4, AC-164.17): rendered with a table of contents, or raw, exactly as the file. */
import "./SkillDetail.css";

import { useState } from "react";
import type { MouseEvent, ReactNode } from "react";

import { Markdown, SegmentedControl, plainHeadingText } from "../../components";
import type { MarkdownProps } from "../../components";
import type { components } from "../../api/schema";
import { tocAnchors } from "../../lib/brainLinks";

type TocEntry = components["schemas"]["TocEntry"];
export type BodyMode = "rendered" | "raw";

/** Scrolls the element with this id into view, when the page has it. */
export function scrollToAnchor(id: string): void {
  document.getElementById(id)?.scrollIntoView({ block: "start" });
}

/** A same-page link to an anchor: a plain click scrolls to it (or hands it to `onGo`). */
export function AnchorLink({
  anchor,
  children,
  className,
  label,
  onGo,
}: {
  anchor: string;
  children: ReactNode;
  className?: string | undefined;
  /** The accessible name, when the visible text alone does not say enough. */
  label?: string | undefined;
  onGo?: ((anchor: string) => void) | undefined;
}) {
  return (
    <a
      href={`#${anchor}`}
      className={className}
      aria-label={label}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
        event.preventDefault();
        (onGo ?? scrollToAnchor)(anchor);
      }}
    >
      {children}
    </a>
  );
}

export interface BodyViewProps {
  /** The text after the frontmatter, or null when the file was not read. */
  body: string | null;
  /** The whole file as UTF-8, or null when not read. */
  raw: string | null;
  toc: readonly TocEntry[];
  /** Resolves the body's relative links (a bundled file opens in the page). */
  localLink?: MarkdownProps["localLink"];
  /** The view, when the page owns it (e.g. to switch back to Rendered for a step link). */
  view?: BodyMode | undefined;
  onViewChange?: ((view: BodyMode) => void) | undefined;
}

/** The body: Rendered (safe Markdown, steps anchored, TOC) or Raw (the exact file text). */
export function BodyView({ body, raw, toc, localLink, view, onViewChange }: BodyViewProps) {
  const [own, setOwn] = useState<BodyMode>("rendered");
  const mode = view ?? own;
  const setMode = (next: string) => {
    const value: BodyMode = next === "raw" ? "raw" : "rendered";
    setOwn(value);
    onViewChange?.(value);
  };
  const anchors = tocAnchors(toc, plainHeadingText).filter((entry) => entry.anchor !== null);
  const showRaw = mode === "raw" && raw !== null;
  return (
    <section className="ah-card ah-skill-section" aria-labelledby="skill-text">
      <div className="ah-card-head">
        <h2 id="skill-text" className="ah-h3">
          Text
        </h2>
        <span className="ah-grow" />
        {body !== null && (
          <SegmentedControl
            label="Show the text"
            value={showRaw ? "raw" : "rendered"}
            onChange={setMode}
            options={[
              { id: "rendered", label: "Rendered" },
              ...(raw === null ? [] : [{ id: "raw", label: "Raw" }]),
            ]}
          />
        )}
      </div>
      <div className="ah-card-body">
        {body === null ? (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            The file was not read, so there is no text to show; Diagnostics says why.
          </p>
        ) : showRaw ? (
          // A scrolling region must take keyboard focus (axe scrollable-region-focusable).
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          <pre className="ah-skill-raw" tabIndex={0}>
            {raw}
          </pre>
        ) : (
          <div className="ah-skill-body">
            {anchors.length > 0 && (
              <nav className="ah-skill-toc" aria-label="Contents">
                <p className="ah-overline" style={{ margin: "0 0 4px" }}>
                  Contents
                </p>
                <ol>
                  {anchors.map((entry) => (
                    <li key={entry.anchor} data-level={entry.level}>
                      <AnchorLink anchor={entry.anchor ?? ""}>
                        {plainHeadingText(entry.text)}
                      </AnchorLink>
                    </li>
                  ))}
                </ol>
              </nav>
            )}
            <Markdown source={body} localLink={localLink} stepAnchors className="ah-grow" />
          </div>
        )}
      </div>
    </section>
  );
}
