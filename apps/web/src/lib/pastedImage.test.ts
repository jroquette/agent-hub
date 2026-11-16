import { describe, expect, it } from "vitest";

import { imageFiles, screenshotBody } from "./pastedImage";

describe("pastedImage", () => {
  it("keeps only the image files of a paste, a drop or a picker, in order", () => {
    const png = new File(["a"], "a.png", { type: "image/png" });
    const text = new File(["b"], "b.txt", { type: "text/plain" });
    const jpeg = new File(["c"], "c.jpg", { type: "image/jpeg" });

    expect(imageFiles({ files: [png, text, jpeg] })).toEqual([png, jpeg]);
    expect(imageFiles(null)).toEqual([]);
    expect(imageFiles({ files: null })).toEqual([]);
  });

  it("turns a PNG data URL into a message's screenshot body", () => {
    expect(screenshotBody("data:image/png;base64,iVBORw0KGgo")).toEqual({
      media_type: "image/png",
      data: "iVBORw0KGgo",
    });
  });
});
