import { describe, expect, it } from "vitest";

import {
  fileBody,
  fileSize,
  MAX_MESSAGE_FILE_BYTES,
  MessageFileError,
  otherFiles,
  readMessageFile,
} from "./messageFile";

const pdfBytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37]); // "%PDF-1.7"

describe("readMessageFile (AC-419.7, AC-419.8)", () => {
  it("reads a PDF by its signature, whatever the file says it is", async () => {
    const file = await readMessageFile(new File([pdfBytes], "spec.pdf", { type: "" }));

    expect(file).toEqual({
      name: "spec.pdf",
      mediaType: "application/pdf",
      data: btoa("%PDF-1.7"),
      bytes: 8,
    });
  });

  it("reads any UTF-8 text as text/plain", async () => {
    const file = await readMessageFile(
      new File(["# Notes\nolá\n"], "notes.md", { type: "text/markdown" }),
    );

    expect(file.mediaType).toBe("text/plain");
    expect(file.bytes).toBe(new TextEncoder().encode("# Notes\nolá\n").length);
  });

  it.each([
    ["a NUL byte", new Uint8Array([0x61, 0x00, 0x62])],
    ["bytes that are not UTF-8", new Uint8Array([0xff, 0xfe, 0x41])],
  ])("refuses %s with the reason", async (_, bytes) => {
    await expect(readMessageFile(new File([bytes], "app.bin"))).rejects.toThrow(
      new MessageFileError("Claude reads PDFs and text files here, and “app.bin” is neither."),
    );
  });

  it("refuses an empty file", async () => {
    await expect(readMessageFile(new File([], "empty.txt"))).rejects.toThrow(
      "“empty.txt” is empty.",
    );
  });

  it("takes a file exactly at 5 MB and refuses one byte over", async () => {
    const at = await readMessageFile(new File(["a".repeat(MAX_MESSAGE_FILE_BYTES)], "at.log"));
    expect(at.bytes).toBe(MAX_MESSAGE_FILE_BYTES);

    await expect(
      readMessageFile(new File(["a".repeat(MAX_MESSAGE_FILE_BYTES + 1)], "over.log")),
    ).rejects.toThrow("“over.log” is 5.0 MB: files go up to 5 MB.");
  });
});

describe("message file helpers", () => {
  it("sizes in B, KB and MB (AC-419.7)", () => {
    expect([fileSize(300), fileSize(2048), fileSize(6 * 1024 * 1024)]).toEqual([
      "300 B",
      "2 KB",
      "6.0 MB",
    ]);
  });

  it("keeps the files of a paste that are not images, in order", () => {
    const shot = new File(["x"], "shot.png", { type: "image/png" });
    const notes = new File(["x"], "notes.md", { type: "text/markdown" });
    const spec = new File(["x"], "spec.pdf", { type: "application/pdf" });

    expect(otherFiles({ files: [notes, shot, spec] })).toEqual([notes, spec]);
    expect(otherFiles(null)).toEqual([]);
  });

  it("turns a read file into the API's files[] item", () => {
    expect(fileBody({ name: "a.txt", mediaType: "text/plain", data: "YQ==", bytes: 1 })).toEqual({
      name: "a.txt",
      media_type: "text/plain",
      data: "YQ==",
    });
  });
});
