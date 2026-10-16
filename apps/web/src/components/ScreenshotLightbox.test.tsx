import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { ScreenshotLightbox, ScreenshotThumb, strokeFor } from "./ScreenshotLightbox";

const SRC = "data:image/png;base64,iVBORw0KGgo=";

/** jsdom loads no image: give it a size and fire `load`, as a browser would. */
function loadImage(width = 1000, height = 500) {
  const img = screen.getByRole("img", { name: "The screen" });
  Object.defineProperty(img, "naturalWidth", { value: width });
  Object.defineProperty(img, "naturalHeight", { value: height });
  fireEvent.load(img);
}

/** The annotation layer, laid out at half the image's size on screen. */
function layer() {
  const svg = screen.getByTestId("annotation-layer");
  svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 500, height: 250 }) as DOMRect;
  (svg as unknown as { setPointerCapture: () => void }).setPointerCapture = vi.fn();
  return svg;
}

function drag(svg: Element, from: [number, number], to: [number, number]) {
  fireEvent.pointerDown(svg, { button: 0, clientX: from[0], clientY: from[1], pointerId: 1 });
  fireEvent.pointerMove(svg, { clientX: to[0], clientY: to[1], pointerId: 1 });
  fireEvent.pointerUp(svg, { clientX: to[0], clientY: to[1], pointerId: 1 });
}

describe("strokeFor", () => {
  it("scales the stroke with the image and never goes under 2px", () => {
    expect(strokeFor(3440)).toBe(7);
    expect(strokeFor(200)).toBe(2);
  });
});

describe("ScreenshotLightbox", () => {
  it("shows the image large with a download link and no tools when it only views", async () => {
    const { baseElement } = render(
      <ScreenshotLightbox src={SRC} alt="The screen" onClose={vi.fn()} />,
    );

    expect(screen.getByRole("dialog", { name: "Screenshot" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", SRC);
    expect(screen.queryByRole("radiogroup", { name: "Tool" })).toBeNull();
    expect(await seriousViolations(baseElement)).toEqual([]);
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<ScreenshotLightbox src={SRC} alt="The screen" onClose={onClose} />);

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("draws a mark in image pixels where the pointer drags, and undoes it", () => {
    render(<ScreenshotLightbox src={SRC} alt="The screen" onClose={vi.fn()} onSave={vi.fn()} />);
    loadImage();
    fireEvent.click(screen.getByRole("radio", { name: "Rectangle (R)" }));

    drag(layer(), [10, 20], [110, 70]);

    const rect = screen.getByTestId("annotation-layer").querySelector("rect");
    expect(rect).toHaveAttribute("x", "20");
    expect(rect).toHaveAttribute("y", "40");
    expect(rect).toHaveAttribute("width", "200");
    expect(rect).toHaveAttribute("height", "100");
    fireEvent.click(screen.getByRole("button", { name: "Undo (⌘Z)" }));
    expect(screen.getByTestId("annotation-layer").querySelector("rect")).toBeNull();
  });

  it("ignores a click that drags no distance", () => {
    render(<ScreenshotLightbox src={SRC} alt="The screen" onClose={vi.fn()} onSave={vi.fn()} />);
    loadImage();

    drag(layer(), [10, 10], [10, 10]);

    expect(screen.getByRole("button", { name: "Undo (⌘Z)" })).toBeDisabled();
  });

  it("picks a tool from its key and adds typed text where the text tool clicked", () => {
    render(<ScreenshotLightbox src={SRC} alt="The screen" onClose={vi.fn()} onSave={vi.fn()} />);
    loadImage();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "t" });
    expect(screen.getByRole("radio", { name: "Text (T)" })).toHaveAttribute("aria-checked", "true");

    fireEvent.pointerDown(layer(), { button: 0, clientX: 50, clientY: 50, pointerId: 1 });
    const field = screen.getByRole("textbox", { name: "Annotation text" });
    fireEvent.change(field, { target: { value: "this is broken" } });
    fireEvent.keyDown(field, { key: "Enter" });

    expect(screen.getByTestId("annotation-layer").querySelector("text")).toHaveTextContent(
      "this is broken",
    );
  });

  it("closes without saving when Done is pressed with no marks", () => {
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(<ScreenshotLightbox src={SRC} alt="The screen" onClose={onClose} onSave={onSave} />);
    loadImage();

    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("ScreenshotThumb", () => {
  it("opens the lightbox from the thumbnail and closes it again", () => {
    render(<ScreenshotThumb src={SRC} alt="The screen" />);

    fireEvent.click(screen.getByRole("button", { name: "Open larger: The screen" }));
    expect(screen.getByRole("dialog", { name: "Screenshot" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close (Esc)" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens the markup editor when it can save", () => {
    render(<ScreenshotThumb src={SRC} alt="The screen" onSave={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Open and mark up: The screen" }));

    expect(screen.getByRole("dialog", { name: "Mark up the screenshot" })).toBeInTheDocument();
  });
});
