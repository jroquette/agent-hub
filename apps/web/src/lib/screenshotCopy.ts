/**
 * The screenshot sent with a session's first message, kept in memory only so the chat view can show it.
 * It holds the latest one alone (bounded) and never touches browser storage or history: after a reload
 * the chat view shows the stored marker's label instead.
 */
const copies = new Map<string, string>();

export function rememberScreenshot(agentSessionId: string, dataUrl: string): void {
  copies.clear();
  copies.set(agentSessionId, dataUrl);
}

export function screenshotFor(agentSessionId: string): string | undefined {
  return copies.get(agentSessionId);
}
