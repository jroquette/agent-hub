import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { Button, ProblemError, Skeleton } from "../../components";
import { useApi } from "../../lib/api";
import { useDiscuss, type DiscussReference } from "../../shell/discuss";

/** The width the mockups are drawn at (the ux-designer's main desktop width). */
export const MOCKUP_WIDTH = 1280;

/**
 * What the frame may do: no script runs (no `allow-scripts`), and the policy below blocks every
 * request, so a mockup only shows what its own file holds. `allow-same-origin` lets this page
 * read the drawn page (its height, the element under a pin); without scripts nothing in it can
 * reach back.
 */
const POLICY =
  "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; media-src data:";

/** The mockup's page with the policy set first, before anything in it could load. */
export function framedDocument(html: string): string {
  return `<meta http-equiv="Content-Security-Policy" content="${POLICY}">${html}`;
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
  const { references, addReference } = useDiscuss();
  const pins = pinsOf(references, source);
  const [fit, setFit] = useState(true);
  const [pinning, setPinning] = useState(false);
  const [height, setHeight] = useState(800);
  const [width, setWidth] = useState(MOCKUP_WIDTH);
  const box = useRef<HTMLDivElement | null>(null);
  const frame = useRef<HTMLIFrameElement | null>(null);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);
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
            ref={frame}
            title={`Mockup of ${screen}`}
            sandbox="allow-same-origin"
            srcDoc={framedDocument(mockup.data.html)}
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
