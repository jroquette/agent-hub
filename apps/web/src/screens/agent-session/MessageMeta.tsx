import { memo } from "react";

import { CopyButton } from "../../components";
import { useMinuteNow } from "../../lib/clock";
import { fmtDateTime, fmtRelative } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";

export interface MessageMetaProps {
  /** When the message was recorded; null while it has no record yet (a streamed reply). */
  at: string | null;
  /** The message's raw text (Markdown for Claude's replies), what Copy copies. */
  text: string;
}

/**
 * A message's action row (AC-234.22): when it was written, relative with the absolute time (in
 * the chosen time zone) in the title, and Copy. Only this row follows the shared minute clock, so
 * the time moves on without re-rendering the message or its Markdown.
 */
export const MessageMeta = memo(function MessageMeta({ at, text }: MessageMetaProps) {
  const now = useMinuteNow();
  const { tz } = usePreferences();
  const written = at === null ? Number.NaN : Date.parse(at);
  return (
    <div className="as-meta">
      {at !== null && Number.isFinite(written) && (
        <time className="ah-small ah-muted" dateTime={at} title={fmtDateTime(at, tz)}>
          {fmtRelative((now - written) / 1000)}
        </time>
      )}
      <CopyButton text={text} label="Copy message" />
    </div>
  );
});
