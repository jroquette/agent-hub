import "./ScreenshotLightbox.css";

import { useCallback, useEffect, useId, useRef, useState, type PointerEvent } from "react";
import { createPortal } from "react-dom";

import { cx } from "../lib/cx";
import { useModalFocus } from "../lib/modalFocus";
import { decodedBytes, MAX_CAPTURE_BYTES } from "../lib/screenCapture";
import { Button, IconButton } from "./core";
import { Icon } from "./Icon";
import type { IconName } from "./icons";

export type AnnotationTool = "crop" | "arrow" | "rect" | "ellipse" | "pen" | "highlight" | "text";

type Point = readonly [number, number];

/**
 * One edit of the image, in the image's own pixels: a mark, or a crop (the latest crop wins). Both
 * live in one history, so undo and clear treat a crop like any mark.
 */
export type Annotation =
  | {
      kind: "crop" | "arrow" | "rect" | "ellipse" | "highlight";
      color: string;
      from: Point;
      to: Point;
    }
  | { kind: "pen"; color: string; points: readonly Point[] }
  | { kind: "text"; color: string; at: Point; text: string };

export const ANNOTATION_COLORS = ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#ffffff"] as const;

const TOOLS: readonly { tool: AnnotationTool; icon: IconName; label: string; key: string }[] = [
  { tool: "crop", icon: "crop", label: "Crop (C)", key: "c" },
  { tool: "arrow", icon: "move-up-right", label: "Arrow (A)", key: "a" },
  { tool: "rect", icon: "square", label: "Rectangle (R)", key: "r" },
  { tool: "ellipse", icon: "circle", label: "Ellipse (O)", key: "o" },
  { tool: "pen", icon: "pencil", label: "Pen (P)", key: "p" },
  { tool: "highlight", icon: "highlighter", label: "Highlight (H)", key: "h" },
  { tool: "text", icon: "type", label: "Text (T)", key: "t" },
];

/** The stroke width for an image this wide: about 3px on a screen-sized view. */
export function strokeFor(width: number): number {
  return Math.max(2, Math.round(width / 500));
}

function arrowHead(from: Point, to: Point, stroke: number): string {
  const angle = Math.atan2(to[1] - from[1], to[0] - from[0]);
  const size = stroke * 4.5;
  const left: Point = [
    to[0] - size * Math.cos(angle - Math.PI / 7),
    to[1] - size * Math.sin(angle - Math.PI / 7),
  ];
  const right: Point = [
    to[0] - size * Math.cos(angle + Math.PI / 7),
    to[1] - size * Math.sin(angle + Math.PI / 7),
  ];
  return [to, left, right].map((p) => `${String(p[0])},${String(p[1])}`).join(" ");
}

export interface CropBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The smallest crop kept, in image pixels: a narrower drag is taken as a slip. */
const MIN_CROP = 10;

function box(from: Point, to: Point): CropBox {
  return {
    x: Math.min(from[0], to[0]),
    y: Math.min(from[1], to[1]),
    width: Math.abs(to[0] - from[0]),
    height: Math.abs(to[1] - from[1]),
  };
}

/** The crop's frame: the area cut away is dimmed. It is never drawn into the PNG (`data-crop`). */
function CropFrame({ crop, width, height }: { crop: CropBox; width: number; height: number }) {
  const { x, y, width: w, height: h } = crop;
  return (
    <g data-crop="" pointerEvents="none">
      <path
        d={`M0 0H${String(width)}V${String(height)}H0Z M${String(x)} ${String(y)}h${String(w)}v${String(h)}h${String(-w)}Z`}
        fillRule="evenodd"
        fill="#000000"
        fillOpacity={0.6}
      />
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        fill="none"
        stroke="#ffffff"
        strokeWidth={1.5}
        strokeDasharray="6 4"
        vectorEffect="non-scaling-stroke"
      />
    </g>
  );
}

/** The crop in effect: the one being dragged, else the latest in the history. */
export function activeCrop(
  marks: readonly Annotation[],
  drawing: Annotation | null,
): CropBox | null {
  const last = drawing?.kind === "crop" ? drawing : marks.findLast((m) => m.kind === "crop");
  return last?.kind === "crop" ? box(last.from, last.to) : null;
}

/** One annotation as SVG; the same drawing is shown live and flattened into the PNG. */
function Mark({ mark, stroke }: { mark: Annotation; stroke: number }) {
  const line = {
    stroke: mark.color,
    strokeWidth: stroke,
    fill: "none",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  switch (mark.kind) {
    case "crop":
      return null;
    case "rect":
      return <rect {...box(mark.from, mark.to)} rx={stroke} {...line} />;
    case "highlight":
      return <rect {...box(mark.from, mark.to)} fill={mark.color} fillOpacity={0.3} />;
    case "ellipse": {
      const b = box(mark.from, mark.to);
      return (
        <ellipse
          cx={b.x + b.width / 2}
          cy={b.y + b.height / 2}
          rx={b.width / 2}
          ry={b.height / 2}
          {...line}
        />
      );
    }
    case "arrow":
      return (
        <g>
          <line x1={mark.from[0]} y1={mark.from[1]} x2={mark.to[0]} y2={mark.to[1]} {...line} />
          <polygon points={arrowHead(mark.from, mark.to, stroke)} fill={mark.color} />
        </g>
      );
    case "pen":
      return <polyline points={mark.points.map((p) => p.join(",")).join(" ")} {...line} />;
    case "text":
      return (
        <text
          x={mark.at[0]}
          y={mark.at[1]}
          fill={mark.color}
          stroke="#000000"
          strokeWidth={stroke / 3}
          paintOrder="stroke"
          fontFamily="system-ui, -apple-system, sans-serif"
          fontWeight={600}
          fontSize={stroke * 7}
          dominantBaseline="hanging"
        >
          {mark.text}
        </text>
      );
  }
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      resolve(image);
    };
    image.onerror = () => {
      reject(new Error("image failed to load"));
    };
    image.src = src;
  });
}

/**
 * The image with its annotations drawn in and cut to `crop` (the whole image without one), as a
 * PNG data URL the server takes: when it is over `maxBytes` it is scaled down until it fits.
 */
export async function flattenScreenshot(
  src: string,
  overlay: SVGSVGElement,
  { maxBytes = MAX_CAPTURE_BYTES, crop }: { maxBytes?: number; crop?: CropBox | null } = {},
): Promise<string> {
  const base = await loadImage(src);
  const clean = overlay.cloneNode(true) as SVGSVGElement;
  for (const frame of clean.querySelectorAll("[data-crop]")) frame.remove();
  const svg = new XMLSerializer().serializeToString(clean);
  const marks = await loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
  const area = crop ?? { x: 0, y: 0, width: base.naturalWidth, height: base.naturalHeight };
  let scale = 1;
  for (let attempt = 0; attempt < 4; attempt++) {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(area.width * scale));
    canvas.height = Math.max(1, Math.round(area.height * scale));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("no 2D canvas");
    for (const layer of [base, marks])
      context.drawImage(
        layer,
        area.x,
        area.y,
        area.width,
        area.height,
        0,
        0,
        canvas.width,
        canvas.height,
      );
    const dataUrl = canvas.toDataURL("image/png");
    const bytes = decodedBytes(dataUrl);
    if (bytes <= maxBytes) return dataUrl;
    scale *= Math.sqrt(maxBytes / bytes) * 0.9;
  }
  throw new Error("the annotated screenshot stays too large");
}

export interface ScreenshotLightboxProps {
  /** A PNG data URL. */
  src: string;
  /** The image's accessible name. */
  alt: string;
  onClose: () => void;
  /** Set to offer annotation tools: called with the annotated PNG, then the caller closes. */
  onSave?: ((dataUrl: string) => void) | undefined;
}

/**
 * A screenshot shown large over the page. With `onSave` it is also an editor, like the macOS
 * screenshot markup: a crop, arrows, boxes, ellipses, a pen, a highlighter and text, in a few
 * colours, with undo. The marks and the crop go into the PNG only on save.
 */
export function ScreenshotLightbox({ src, alt, onClose, onSave }: ScreenshotLightboxProps) {
  const editing = onSave !== undefined;
  const dialog = useRef<HTMLDivElement>(null);
  const overlay = useRef<SVGSVGElement>(null);
  const titleId = useId();
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const [tool, setTool] = useState<AnnotationTool>("arrow");
  const [color, setColor] = useState<string>(ANNOTATION_COLORS[0]);
  const [marks, setMarks] = useState<readonly Annotation[]>([]);
  const [drawing, setDrawing] = useState<Annotation | null>(null);
  const [typing, setTyping] = useState<{ at: Point; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useModalFocus(dialog, { locked: saving, onEscape: onClose });

  const stroke = size ? strokeFor(size.width) : 3;
  const crop = activeCrop(marks, drawing);

  const undo = useCallback(() => {
    setMarks((before) => before.slice(0, -1));
  }, []);

  useEffect(() => {
    if (!editing) return;
    const node = dialog.current;
    if (!node) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        undo();
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const picked = TOOLS.find((t) => t.key === event.key.toLowerCase());
      if (picked) setTool(picked.tool);
    };
    node.addEventListener("keydown", onKeyDown);
    return () => {
      node.removeEventListener("keydown", onKeyDown);
    };
  }, [editing, undo]);

  const pointAt = (event: PointerEvent<SVGSVGElement>): Point | null => {
    if (!size) return null;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const x = Math.round(((event.clientX - rect.left) / rect.width) * size.width);
    const y = Math.round(((event.clientY - rect.top) / rect.height) * size.height);
    // A drag held past the edge (pointer capture) stays on the image.
    return [Math.min(Math.max(x, 0), size.width), Math.min(Math.max(y, 0), size.height)];
  };

  const commitText = () => {
    if (typing?.text.trim())
      setMarks((before) => [...before, { kind: "text", color, at: typing.at, text: typing.text }]);
    setTyping(null);
  };

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (!editing || event.button !== 0) return;
    const at = pointAt(event);
    if (!at) return;
    if (tool === "text") {
      event.preventDefault();
      commitText();
      setTyping({ at, text: "" });
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrawing(
      tool === "pen"
        ? { kind: "pen", color, points: [at] }
        : { kind: tool, color, from: at, to: at },
    );
  };

  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!drawing) return;
    const at = pointAt(event);
    if (!at) return;
    setDrawing(
      drawing.kind === "pen"
        ? { ...drawing, points: [...drawing.points, at] }
        : drawing.kind === "text"
          ? drawing
          : { ...drawing, to: at },
    );
  };

  const onPointerUp = () => {
    if (!drawing) return;
    const tiny =
      drawing.kind === "pen"
        ? drawing.points.length < 2
        : drawing.kind === "crop"
          ? Math.min(
              Math.abs(drawing.to[0] - drawing.from[0]),
              Math.abs(drawing.to[1] - drawing.from[1]),
            ) < MIN_CROP
          : drawing.kind !== "text" &&
            Math.hypot(drawing.to[0] - drawing.from[0], drawing.to[1] - drawing.from[1]) <
              stroke * 2;
    if (!tiny) setMarks((before) => [...before, drawing]);
    setDrawing(null);
  };

  const save = async () => {
    if (!onSave) return;
    if (marks.length === 0 || !overlay.current) {
      onClose();
      return;
    }
    setSaving(true);
    setFailure(null);
    try {
      onSave(await flattenScreenshot(src, overlay.current, { crop: activeCrop(marks, null) }));
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "the screenshot could not be saved");
      setSaving(false);
    }
  };

  const textBox = typing && size && (
    <input
      // The text tool's field opens where it was clicked; it takes focus at once.
      // eslint-disable-next-line jsx-a11y/no-autofocus
      autoFocus
      aria-label="Annotation text"
      className="ah-lightbox-text"
      style={{
        left: `${String((typing.at[0] / size.width) * 100)}%`,
        top: `${String((typing.at[1] / size.height) * 100)}%`,
        color,
      }}
      value={typing.text}
      onChange={(event) => {
        setTyping({ ...typing, text: event.target.value });
      }}
      onBlur={commitText}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commitText();
        } else if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          setTyping(null);
        }
      }}
    />
  );

  return createPortal(
    <div
      className="ah-scrim ah-lightbox-scrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget && !saving) onClose();
      }}
    >
      <div
        ref={dialog}
        className="ah-lightbox"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={saving}
        tabIndex={-1}
      >
        <div className="ah-lightbox-bar">
          <h2 id={titleId} className="ah-small ah-lightbox-title">
            {editing ? "Mark up the screenshot" : "Screenshot"}
          </h2>
          {editing && (
            <>
              <div className="ah-row" role="radiogroup" aria-label="Tool" style={{ gap: 2 }}>
                {TOOLS.map((t) => (
                  <IconButton
                    key={t.tool}
                    icon={t.icon}
                    label={t.label}
                    size="sm"
                    role="radio"
                    aria-checked={tool === t.tool}
                    className={cx(tool === t.tool && "ah-lightbox-on")}
                    disabled={saving}
                    onClick={() => {
                      setTool(t.tool);
                    }}
                  />
                ))}
              </div>
              <div className="ah-row" role="radiogroup" aria-label="Colour" style={{ gap: 4 }}>
                {ANNOTATION_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    role="radio"
                    aria-checked={color === c}
                    aria-label={`Colour ${c}`}
                    className={cx("ah-lightbox-swatch", color === c && "ah-lightbox-on")}
                    style={{ background: c }}
                    disabled={saving}
                    onClick={() => {
                      setColor(c);
                    }}
                  />
                ))}
              </div>
              <IconButton
                icon="undo-2"
                label="Undo (⌘Z)"
                size="sm"
                disabled={saving || marks.length === 0}
                onClick={undo}
              />
              <Button
                size="sm"
                variant="ghost"
                disabled={saving || marks.length === 0}
                onClick={() => {
                  setMarks([]);
                }}
              >
                Clear
              </Button>
            </>
          )}
          <span className="ah-lightbox-spacer" />
          {!editing && (
            <a className="ah-btn ah-btn-ghost ah-btn-sm" href={src} download="screenshot.png">
              Download
            </a>
          )}
          <IconButton icon="x" label="Close (Esc)" size="sm" disabled={saving} onClick={onClose} />
        </div>

        <div className="ah-lightbox-stage">
          <div className="ah-lightbox-frame">
            <img
              src={src}
              alt={alt}
              draggable={false}
              onLoad={(event) => {
                setSize({
                  width: event.currentTarget.naturalWidth,
                  height: event.currentTarget.naturalHeight,
                });
              }}
            />
            {editing && size && (
              <svg
                ref={overlay}
                xmlns="http://www.w3.org/2000/svg"
                viewBox={`0 0 ${String(size.width)} ${String(size.height)}`}
                width={size.width}
                height={size.height}
                className={cx("ah-lightbox-overlay", tool === "text" && "ah-lightbox-typing")}
                data-testid="annotation-layer"
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
              >
                {marks.map((mark, index) => (
                  <Mark key={index} mark={mark} stroke={stroke} />
                ))}
                {drawing && <Mark mark={drawing} stroke={stroke} />}
                {crop && <CropFrame crop={crop} width={size.width} height={size.height} />}
              </svg>
            )}
            {textBox}
          </div>
        </div>

        {editing && (
          <div className="ah-lightbox-foot">
            {failure ? (
              <span role="alert" className="ah-small as-error">
                Could not save: {failure}
              </span>
            ) : (
              <span className="ah-small ah-subtle">
                Drag on the image to mark it or crop it. Claude receives the screenshot as you see
                it.
              </span>
            )}
            <span className="ah-lightbox-spacer" />
            <Button size="sm" disabled={saving} onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              disabled={saving}
              onClick={() => {
                void save();
              }}
            >
              {saving ? "Saving…" : "Done"}
            </Button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

export interface ScreenshotThumbProps {
  src: string;
  alt: string;
  /** The thumbnail's class (its size where it shows). */
  className?: string | undefined;
  /** Set to open the lightbox as an editor; see `ScreenshotLightbox`. */
  onSave?: ((dataUrl: string) => void) | undefined;
  disabled?: boolean | undefined;
}

/** A screenshot thumbnail that opens it large (and, with `onSave`, its markup editor). */
export function ScreenshotThumb({ src, alt, className, onSave, disabled }: ScreenshotThumbProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="ah-shot-button"
        aria-label={onSave ? `Open and mark up: ${alt}` : `Open larger: ${alt}`}
        title={onSave ? "Open to view larger and mark up" : "Open larger"}
        disabled={disabled}
        onClick={() => {
          setOpen(true);
        }}
      >
        <img className={className} src={src} alt={alt} />
        <span className="ah-shot-hint" aria-hidden="true">
          <Icon name={onSave ? "pencil" : "maximize-2"} size="sm" />
        </span>
      </button>
      {open && (
        <ScreenshotLightbox
          src={src}
          alt={alt}
          onClose={() => {
            setOpen(false);
          }}
          onSave={
            onSave &&
            ((dataUrl) => {
              onSave(dataUrl);
              setOpen(false);
            })
          }
        />
      )}
    </>
  );
}
