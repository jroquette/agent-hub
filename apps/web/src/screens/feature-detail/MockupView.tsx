import { useCallback, useEffect, useRef, useState } from "react";

import { Button, ProblemError, Skeleton } from "../../components";
import { useViewportSize } from "../../components/Canvas";
import { useApi } from "../../lib/api";
import { useDiscuss, type DiscussReference } from "../../shell/discuss";

/** The width the mockups are drawn at (the ux-designer's main desktop width). */
export const MOCKUP_WIDTH = 1280;

/**
 * The mockup served as its own page, which the frame loads. What the frame may do: no script
 * runs (no `allow-scripts`), and the page's own policy, sent by hub web with it, blocks every
 * request but its inline styles and `data:` images, fonts and media, so a mockup only shows what
 * its own file holds. (A `srcdoc` frame would inherit hub web's policy, which blocks inline
 * styles.) `allow-same-origin` lets this page read the drawn page (its height, the element under
 * a pin); without scripts nothing in it can reach back.
 */
export function mockupPageUrl(project: string, slug: string, name: string): string {
  const part = encodeURIComponent;
  return `/api/v1/features/${part(project)}/${part(slug)}/mockups/${part(name)}/page`;
}

interface Pin {
  n: number;
  x: number;
  y: number;
}

/** `pin:<file>:<n>:<x>:<y>`: a pin is a Discuss reference, so it lives as long as its chip. */
function pinId(file: string, pin: Pin): string {
  return `pin:${file}:${String(pin.n)}:${String(pin.x)}:${String(pin.y)}`;
}

function pinsOf(references: readonly DiscussReference[], file: string): Pin[] {
  const prefix = `pin:${file}:`;
  return references.flatMap((reference) => {
    if (!reference.id.startsWith(prefix)) return [];
    const [n, x, y] = reference.id.slice(prefix.length).split(":").map(Number);
    return n === undefined || x === undefined || y === undefined ? [] : [{ n, x, y }];
  });
}

/** What sits under a point of the drawn page: its `data-ux` region and the element's own text. */
export function describePoint(doc: Document, x: number, y: number): string {
  const element = doc.elementFromPoint(x, y);
  if (!element) return "empty space";
  const region = element.closest("[data-ux]")?.getAttribute("data-ux");
  const text = element.textContent.replace(/\s+/g, " ").trim();
  const words = text.length > 120 ? `${text.slice(0, 119)}…` : text;
  return [
    region ? `region "${region}"` : null,
    `<${element.tagName.toLowerCase()}>`,
    words ? `reading "${words}"` : null,
  ]
    .filter(Boolean)
    .join(", ");
}

/**
 * One UX design's mockup (`ux-*.html`), drawn at its desktop width and scaled to fit the column
 * (or shown at its own size). "Comment on a point" turns each click into a numbered pin that is
 * attached to the next Discuss message, naming the point and what is drawn there.
 */
export function MockupView({
  project,
  slug,
  name,
  source,
  screen,
}: {
  project: string;
  slug: string;
  /** The mockup's file name, `ux-<stem>.html`. */
  name: string;
  /** The file as the agents find it, relative to the hub folder. */
  source: string;
  screen: string;
}) {
  const mockup = useApi("/api/v1/features/{project}/{slug}/mockups/{name}", {
    path: { project, slug, name },
  });
  if (mockup.isPending) return <Skeleton height={480} />;
  if (mockup.isError) {
    return (
      <ProblemError
        title={mockup.error.title}
        detail={mockup.error.detail}
        status={mockup.error.status}
        onRetry={() => void mockup.refetch()}
      />
    );
  }
  return (
    <MockupStage
      src={mockupPageUrl(project, slug, name)}
      version={mockup.data.sha256}
      source={source}
      screen={screen}
    />
  );
}

/**
 * The loaded mockup: mounted only once the file is read, so the column it measures for "fit to
 * width" is there on its first render.
 */
function MockupStage({
  src,
  version,
  source,
  screen,
}: {
  src: string;
  /** The file's sha256: a new read of a changed file loads the frame afresh. */
  version: string;
  source: string;
  screen: string;
}) {
  const { references, addReference } = useDiscuss();
  const pins = pinsOf(references, source);
  const [fit, setFit] = useState(true);
  const [pinning, setPinning] = useState(false);
  const [height, setHeight] = useState(800);
  const box = useRef<HTMLDivElement | null>(null);
  const frame = useRef<HTMLIFrameElement | null>(null);
  // Before the first measure, or with no ResizeObserver, the width reads 0: drawn at its own size.
  const measured = useViewportSize(box).width;
  const width = measured > 0 ? measured : MOCKUP_WIDTH;

  useEffect(() => {
    if (!pinning) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPinning(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [pinning]);

  const measure = useCallback(() => {
    const doc = frame.current?.contentDocument;
    if (doc?.documentElement) setHeight(Math.max(400, doc.documentElement.scrollHeight));
  }, []);

  const scale = fit ? Math.min(1, width / MOCKUP_WIDTH) : 1;
  const place = (event: React.MouseEvent<HTMLDivElement>) => {
    const doc = frame.current?.contentDocument;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.round((event.clientX - rect.left) / scale);
    const y = Math.round((event.clientY - rect.top) / scale);
    const n = Math.max(0, ...pins.map((p) => p.n)) + 1;
    let what = "the mockup";
    try {
      if (doc) what = describePoint(doc, x, y);
    } catch {
      // A page that cannot say what is under the point still gets its pin.
    }
    addReference({
      id: pinId(source, { n, x, y }),
      label: `Pin ${String(n)} · ${screen}`,
      source,
      quote: `Pin ${String(n)} at (${String(x)}, ${String(y)}) px of the ${String(MOCKUP_WIDTH)} px wide mockup: ${what}.`,
    });
  };

  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <Button
          size="sm"
          variant={pinning ? "primary" : "default"}
          icon="message-square"
          aria-pressed={pinning}
          onClick={() => {
            setPinning(!pinning);
          }}
        >
          {pinning ? "Click the mockup to drop a pin · Esc to stop" : "Comment on a point"}
        </Button>
        {pins.length > 0 && (
          <span className="ah-small ah-muted">
            {pins.length} pin{pins.length === 1 ? "" : "s"} in your next Discuss message
          </span>
        )}
        <span className="ah-grow" />
        <Button
          size="sm"
          variant="ghost"
          icon={fit ? "maximize-2" : "scan-eye"}
          onClick={() => {
            setFit(!fit);
          }}
        >
          {fit ? "Actual size" : "Fit to width"}
        </Button>
      </div>
      <div ref={box} className="ah-mockup" style={{ overflowX: fit ? "hidden" : "auto" }}>
        <div
          className="ah-mockup-stage"
          style={{
            width: MOCKUP_WIDTH * scale,
            height: height * scale,
          }}
        >
          <iframe
            key={version}
            ref={frame}
            title={`Mockup of ${screen}`}
            sandbox="allow-same-origin"
            src={src}
            onLoad={measure}
            style={{
              width: MOCKUP_WIDTH,
              height,
              transform: `scale(${String(scale)})`,
            }}
          />
          {pinning && (
            // The pin layer is a pointer surface over the drawing; the button above is its keyboard way.
            // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
            <div className="ah-mockup-layer" onClick={place} />
          )}
          {pins.map((pin) => (
            <span
              key={pin.n}
              className="ah-mockup-pin"
              style={{ left: pin.x * scale, top: pin.y * scale }}
              title={`Pin ${String(pin.n)}`}
            >
              {pin.n}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
