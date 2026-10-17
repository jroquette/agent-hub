import { flattenScreenshot } from "../components/ScreenshotLightbox";

/** The most images one message carries (the API's `MAX_MESSAGE_SCREENSHOTS`). */
export const MAX_MESSAGE_IMAGES = 10;

/** The image files of a paste, a drop or a file input, in order. */
export function imageFiles(source: { files: ArrayLike<File> | null } | null): File[] {
  return Array.from(source?.files ?? []).filter((file) => file.type.startsWith("image/"));
}

function readAsDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("could not read the image"));
    };
    reader.onerror = () => {
      reject(reader.error ?? new Error("could not read the image"));
    };
    reader.readAsDataURL(file);
  });
}

/**
 * A pasted or dropped image as the PNG data URL a message takes: any format the browser decodes,
 * scaled down until it fits the screenshot byte limit.
 */
export async function imageToPng(file: Blob): Promise<string> {
  return flattenScreenshot(await readAsDataUrl(file), null);
}

/** A PNG data URL as a message's `screenshots[]` item (the base64 after the comma). */
export function screenshotBody(dataUrl: string): { media_type: "image/png"; data: string } {
  return { media_type: "image/png", data: dataUrl.slice(dataUrl.indexOf(",") + 1) };
}
