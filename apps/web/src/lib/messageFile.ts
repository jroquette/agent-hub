/** The most files one message carries (the API's `MAX_MESSAGE_FILES`). */
export const MAX_MESSAGE_FILES = 10;
/** The decoded size limit of each file (the API's `MAX_MESSAGE_FILE_BYTES`: 5 MiB). */
export const MAX_MESSAGE_FILE_BYTES = 5 * 1024 * 1024;

/** A file read for a message: a PDF or a UTF-8 text, as the base64 the API takes. */
export interface MessageFile {
  name: string;
  mediaType: "application/pdf" | "text/plain";
  /** The file's bytes, base64-encoded. */
  data: string;
  bytes: number;
}

/** Why a file cannot go with a message, in words the composer shows as they are. */
export class MessageFileError extends Error {}

const PDF_SIGNATURE = [0x25, 0x50, 0x44, 0x46, 0x2d]; // "%PDF-"

/** The files of a paste, a drop or a file input that are not images, in order. */
export function otherFiles(source: { files: ArrayLike<File> | null } | null): File[] {
  return Array.from(source?.files ?? []).filter((file) => !file.type.startsWith("image/"));
}

/** A size in the units people read: bytes, KB or MB. */
export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${String(Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function readBytes(file: Blob): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (reader.result instanceof ArrayBuffer) resolve(new Uint8Array(reader.result));
      else reject(new MessageFileError("Could not read that file. Try again."));
    };
    reader.onerror = () => {
      reject(new MessageFileError("Could not read that file. Try again."));
    };
    reader.readAsArrayBuffer(file);
  });
}

function isPdf(bytes: Uint8Array): boolean {
  return PDF_SIGNATURE.every((byte, index) => bytes[index] === byte);
}

function isText(bytes: Uint8Array): boolean {
  if (bytes.includes(0)) return false;
  try {
    new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return true;
  } catch {
    return false;
  }
}

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let at = 0; at < bytes.length; at += chunk) {
    binary += String.fromCharCode(...bytes.subarray(at, at + chunk));
  }
  return btoa(binary);
}

/**
 * A picked, pasted or dropped file as a message takes it: a PDF, or any text in UTF-8 (code,
 * Markdown, CSV, JSON, logs…), of at most 5 MB. Anything else is refused with the reason.
 */
export async function readMessageFile(file: File): Promise<MessageFile> {
  if (file.size > MAX_MESSAGE_FILE_BYTES)
    throw new MessageFileError(`“${file.name}” is ${fileSize(file.size)}: files go up to 5 MB.`);
  if (file.size === 0) throw new MessageFileError(`“${file.name}” is empty.`);
  const bytes = await readBytes(file);
  const mediaType = isPdf(bytes) ? "application/pdf" : isText(bytes) ? "text/plain" : null;
  if (mediaType === null)
    throw new MessageFileError(
      `Claude reads PDFs and text files here, and “${file.name}” is neither.`,
    );
  return { name: file.name, mediaType, data: toBase64(bytes), bytes: bytes.length };
}

/** A read file as a message's `files[]` item. */
export function fileBody(file: MessageFile): {
  name: string;
  media_type: MessageFile["mediaType"];
  data: string;
} {
  return { name: file.name, media_type: file.mediaType, data: file.data };
}
