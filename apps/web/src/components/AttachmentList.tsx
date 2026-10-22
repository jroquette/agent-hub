import "./AttachmentList.css";

import { useRef, useState } from "react";

import {
  fileSize,
  MAX_MESSAGE_FILES,
  MessageFileError,
  otherFiles,
  readMessageFile,
  type MessageFile,
} from "../lib/messageFile";
import { imageFiles, imageToPng, MAX_MESSAGE_IMAGES } from "../lib/pastedImage";
import { Icon } from "./Icon";
import { ScreenshotThumb } from "./ScreenshotLightbox";

/** An image of a message: a PNG data URL, keyed for its list. */
export interface AttachedImage {
  key: number;
  url: string;
}

/** A PDF or text file of a message, keyed for its list. */
export interface AttachedFile {
  key: number;
  file: MessageFile;
}

/** Where a paste, a drop or a file input keeps its files. */
export type FileSource = { files: ArrayLike<File> | null } | null;

export interface MessageAttachmentsOptions {
  acceptsImages: boolean;
  acceptsFiles: boolean;
  /** Nothing can be added (the box is disabled). */
  disabled?: boolean | undefined;
  /** Says what went wrong (a refused file, a limit), or null once an add went through. */
  onError: (message: string | null) => void;
}

export interface MessageAttachments {
  images: readonly AttachedImage[];
  files: readonly AttachedFile[];
  /** How many images or files are still being read. */
  reading: number;
  /** Images and files attached (not counting the ones still being read). */
  count: number;
  /** Whether a paste or drop holds anything this box takes. */
  takes: (source: FileSource) => boolean;
  /** Adds what a paste, a drop or the picker brought: images as images, the rest as files. */
  add: (source: FileSource) => void;
  removeImage: (key: number) => void;
  removeFile: (key: number) => void;
  /** An image marked up in the lightbox replaces its PNG. */
  replaceImage: (key: number, url: string) => void;
  /** Drops what was sent; what was added meanwhile stays for the next message. */
  removeSent: (images: readonly AttachedImage[], files: readonly AttachedFile[]) => void;
  /** Both limits are reached: the picker has nothing left to add. */
  full: boolean;
}

/**
 * The images and files of one message or request: each image read and turned into a PNG under
 * the size limit, each file read and checked (a PDF, or UTF-8 text, of at most 5 MB). Past a
 * limit, or for a refused file, `onError` says why; the rest stay attached.
 */
export function useMessageAttachments({
  acceptsImages,
  acceptsFiles,
  disabled = false,
  onError,
}: MessageAttachmentsOptions): MessageAttachments {
  const [images, setImages] = useState<AttachedImage[]>([]);
  const [files, setFiles] = useState<AttachedFile[]>([]);
  const [readingImages, setReadingImages] = useState(0);
  const [readingFiles, setReadingFiles] = useState(0);
  const keys = useRef(0);
  const nextKey = () => {
    keys.current += 1;
    return keys.current;
  };

  const addImages = (picked: readonly File[]) => {
    if (!acceptsImages || disabled || picked.length === 0) return;
    const room = MAX_MESSAGE_IMAGES - images.length - readingImages;
    const taken = picked.slice(0, Math.max(0, room));
    onError(
      taken.length < picked.length
        ? `A message takes up to ${String(MAX_MESSAGE_IMAGES)} images.`
        : null,
    );
    for (const file of taken) {
      setReadingImages((count) => count + 1);
      imageToPng(file)
        .then((url) => {
          const key = nextKey();
          setImages((before) => [...before, { key, url }]);
        })
        .catch(() => {
          onError("Could not read that image. Try another one.");
        })
        .finally(() => {
          setReadingImages((count) => count - 1);
        });
    }
  };

  const addFiles = (picked: readonly File[]) => {
    if (!acceptsFiles || disabled || picked.length === 0) return;
    const room = MAX_MESSAGE_FILES - files.length - readingFiles;
    const taken = picked.slice(0, Math.max(0, room));
    onError(
      taken.length < picked.length
        ? `A message takes up to ${String(MAX_MESSAGE_FILES)} files.`
        : null,
    );
    for (const one of taken) {
      setReadingFiles((count) => count + 1);
      readMessageFile(one)
        .then((file) => {
          const key = nextKey();
          setFiles((before) => [...before, { key, file }]);
        })
        .catch((cause: unknown) => {
          onError(
            cause instanceof MessageFileError
              ? cause.message
              : "Could not read that file. Try again.",
          );
        })
        .finally(() => {
          setReadingFiles((count) => count - 1);
        });
    }
  };

  const picked = (source: FileSource) => ({
    images: acceptsImages ? imageFiles(source) : [],
    files: acceptsFiles ? otherFiles(source) : [],
  });

  return {
    images,
    files,
    reading: readingImages + readingFiles,
    count: images.length + files.length,
    takes: (source) => {
      const found = picked(source);
      return found.images.length + found.files.length > 0;
    },
    add: (source) => {
      const found = picked(source);
      addImages(found.images);
      addFiles(found.files);
    },
    removeImage: (key) => {
      setImages((before) => before.filter((image) => image.key !== key));
    },
    removeFile: (key) => {
      setFiles((before) => before.filter((attached) => attached.key !== key));
    },
    replaceImage: (key, url) => {
      setImages((before) => before.map((image) => (image.key === key ? { ...image, url } : image)));
    },
    removeSent: (sentImages, sentFiles) => {
      setImages((now) => now.filter((image) => !sentImages.includes(image)));
      setFiles((now) => now.filter((attached) => !sentFiles.includes(attached)));
    },
    full:
      (!acceptsImages || images.length + readingImages >= MAX_MESSAGE_IMAGES) &&
      (!acceptsFiles || files.length + readingFiles >= MAX_MESSAGE_FILES),
  };
}

export interface AttachmentListProps {
  images: readonly AttachedImage[];
  files: readonly AttachedFile[];
  reading?: number | undefined;
  /** The list's accessible name. */
  label?: string | undefined;
  /** Without these the list is read-only (what was sent). */
  onRemoveImage?: ((key: number) => void) | undefined;
  onRemoveFile?: ((key: number) => void) | undefined;
  onReplaceImage?: ((key: number, url: string) => void) | undefined;
}

/**
 * The images (a thumbnail each, open it to mark it up) and files (a chip with name and size) of a
 * message, each with a remove button in its corner; a loader tile while one is read.
 */
export function AttachmentList({
  images,
  files,
  reading = 0,
  label = "Attached to this message",
  onRemoveImage,
  onRemoveFile,
  onReplaceImage,
}: AttachmentListProps) {
  if (images.length + files.length + reading === 0) return null;
  return (
    <ul className="as-composer-images" aria-label={label}>
      {files.map(({ key, file }) => (
        <li key={key} className="as-composer-file">
          <Icon name="file-text" size="sm" />
          <span className="as-composer-file-name" title={file.name}>
            {file.name}
          </span>
          <span className="ah-small ah-muted as-composer-file-size">{fileSize(file.bytes)}</span>
          {onRemoveFile && (
            <button
              type="button"
              className="as-composer-image-remove"
              aria-label={`Remove ${file.name}`}
              title="Remove"
              onClick={() => {
                onRemoveFile(key);
              }}
            >
              <Icon name="x" size="sm" />
            </button>
          )}
        </li>
      ))}
      {images.map((image, index) => (
        <li key={image.key} className="as-composer-image">
          <ScreenshotThumb
            className="as-composer-thumb"
            src={image.url}
            alt={`Image ${String(index + 1)}`}
            onSave={
              onReplaceImage
                ? (url) => {
                    onReplaceImage(image.key, url);
                  }
                : undefined
            }
          />
          {onRemoveImage && (
            <button
              type="button"
              className="as-composer-image-remove"
              aria-label={`Remove image ${String(index + 1)}`}
              title="Remove"
              onClick={() => {
                onRemoveImage(image.key);
              }}
            >
              <Icon name="x" size="sm" />
            </button>
          )}
        </li>
      ))}
      {reading > 0 && (
        <li className="as-composer-image as-composer-image-reading" aria-live="polite">
          <Icon name="loader" size="sm" className="as-spin" />
          <span className="ah-sr">Reading…</span>
        </li>
      )}
    </ul>
  );
}
