import { render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAutoGrow } from "./useAutoGrow";

function Box({ value, share }: { value: string; share?: number }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useAutoGrow(ref, value, share);
  return <textarea aria-label="box" ref={ref} value={value} readOnly />;
}

/** jsdom has no layout: the text's height is given by hand. */
function contentHeight(px: number) {
  vi.spyOn(HTMLTextAreaElement.prototype, "scrollHeight", "get").mockReturnValue(px);
}

describe("useAutoGrow (AC-420.10)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("grows with its text and hides the scrollbar while under the cap", () => {
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(1000);
    contentHeight(120);
    const { getByLabelText } = render(<Box value="a few lines" />);

    const box = getByLabelText("box");
    expect(box.style.height).toBe("120px");
    expect(box.style.overflowY).toBe("hidden");
  });

  it("stops at its share of the viewport, then scrolls, and fits again on a resize", () => {
    const viewport = vi.spyOn(window, "innerHeight", "get").mockReturnValue(1000);
    contentHeight(900);
    const { getByLabelText } = render(<Box value="a long brief" share={0.5} />);

    const box = getByLabelText("box");
    expect(box.style.height).toBe("500px");
    expect(box.style.overflowY).toBe("auto");

    viewport.mockReturnValue(600);
    window.dispatchEvent(new Event("resize"));
    expect(box.style.height).toBe("300px");
  });

  it("caps at 40 % of the viewport by default, the chat's share", () => {
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(1000);
    contentHeight(900);
    const { getByLabelText } = render(<Box value="text" />);

    expect(getByLabelText("box").style.height).toBe("400px");
  });
});
