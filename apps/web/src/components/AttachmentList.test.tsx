import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AttachmentList, useMessageAttachments } from "./AttachmentList";

vi.mock("../lib/pastedImage", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/pastedImage")>();
  // The canvas is not in jsdom: an image "converts" to a data URL naming its file.
  return {
    ...actual,
    imageToPng: vi.fn((file: File) => Promise.resolve(`data:image/png;base64,${file.name}`)),
  };
});

const text = (name: string) => new File(["hello"], name, { type: "text/plain" });
const shot = (name: string) => new File(["x"], name, { type: "image/png" });
const file = (name: string, bytes = 2048) => ({
  name,
  mediaType: "text/plain" as const,
  data: "aGVsbG8=",
  bytes,
});

describe("useMessageAttachments (AC-419.12)", () => {
  it("takes images as images and the rest as files", async () => {
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useMessageAttachments({ acceptsImages: true, acceptsFiles: true, onError }),
    );

    act(() => {
      result.current.add({ files: [shot("a.png"), text("notes.txt")] });
    });

    await waitFor(() => {
      expect(result.current.count).toBe(2);
    });
    expect(result.current.images.map((image) => image.url)).toEqual([
      "data:image/png;base64,a.png",
    ]);
    expect(result.current.files.map((attached) => attached.file.name)).toEqual(["notes.txt"]);
    expect(onError).toHaveBeenLastCalledWith(null);
  });

  it("refuses files past ten with the reason and keeps the first ten (AC-419.8)", async () => {
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useMessageAttachments({ acceptsImages: false, acceptsFiles: true, onError }),
    );

    act(() => {
      result.current.add({ files: Array.from({ length: 11 }, (_, n) => text(`${String(n)}.txt`)) });
    });

    expect(onError).toHaveBeenCalledWith("A message takes up to 10 files.");
    await waitFor(() => {
      expect(result.current.files).toHaveLength(10);
    });
    expect(result.current.full).toBe(true);
  });

  it("takes nothing it does not accept, and nothing while disabled", () => {
    const onError = vi.fn();
    const { result, rerender } = renderHook(
      ({ disabled }: { disabled: boolean }) =>
        useMessageAttachments({ acceptsImages: true, acceptsFiles: false, disabled, onError }),
      { initialProps: { disabled: false } },
    );

    expect(result.current.takes({ files: [text("a.txt")] })).toBe(false);
    expect(result.current.takes({ files: [shot("a.png")] })).toBe(true);
    rerender({ disabled: true });
    act(() => {
      result.current.add({ files: [shot("a.png")] });
    });
    expect(result.current.reading).toBe(0);
    expect(onError).not.toHaveBeenCalled();
  });
});

describe("AttachmentList (AC-419.11, AC-419.12)", () => {
  it("shows each file as a chip with its whole name in its title and its size", () => {
    const long = "a-very-long-file-name-that-does-not-fit-in-one-chip.md";
    render(<AttachmentList images={[]} files={[{ key: 1, file: file(long) }]} />);

    const list = screen.getByRole("list", { name: "Attached to this message" });
    expect(within(list).getByText(long)).toHaveAttribute("title", long);
    expect(within(list).getByText("2 KB")).toHaveClass("as-composer-file-size");
  });

  it("is read-only without remove handlers", () => {
    render(
      <AttachmentList
        images={[{ key: 1, url: "data:image/png;base64,A" }]}
        files={[{ key: 2, file: file("notes.md") }]}
        label="Sent"
      />,
    );

    expect(screen.getByRole("list", { name: "Sent" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
  });

  it("removes a file or an image by its key", async () => {
    const onRemoveFile = vi.fn();
    const onRemoveImage = vi.fn();
    render(
      <AttachmentList
        images={[{ key: 1, url: "data:image/png;base64,A" }]}
        files={[{ key: 2, file: file("notes.md") }]}
        onRemoveFile={onRemoveFile}
        onRemoveImage={onRemoveImage}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Remove notes.md" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove image 1" }));

    expect(onRemoveFile).toHaveBeenCalledWith(2);
    expect(onRemoveImage).toHaveBeenCalledWith(1);
  });

  it("shows a loader while one is read, and nothing when empty", () => {
    const { rerender, container } = render(<AttachmentList images={[]} files={[]} reading={1} />);
    expect(screen.getByText("Reading…")).toBeInTheDocument();

    rerender(<AttachmentList images={[]} files={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
