import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  OpenReviewFileContext,
  ReviewBubble,
  ReviewDiff,
  resolvedKey,
  useResolvedThreads,
  type ReviewDiffProps,
} from "./ReviewDiff";
import { commentMessage, type ReviewThread } from "./review";

const DIFF = "--- a/x.py\n+++ b/x.py\n@@ -40,3 +40,4 @@\n a\n-b\n+c\n+d\n e\n";

function Harness(props: Partial<ReviewDiffProps>) {
  const resolved = useResolvedThreads("s1");
  return (
    <ReviewDiff
      diff={DIFF}
      label="Change 1 to x.py"
      numbered
      path="/r/x.py"
      change={1}
      threads={[]}
      resolved={resolved}
      {...props}
    />
  );
}

afterEach(() => {
  window.localStorage.clear();
});

describe("ReviewDiff (comments)", () => {
  it("comments on a range of lines, sending the anchor and the code to Claude (AC-265.16)", async () => {
    const user = userEvent.setup();
    const onComment = vi.fn(() => Promise.resolve());
    render(<Harness onComment={onComment} />);

    await user.click(screen.getByRole("button", { name: "Comment on old line 41" }));
    await user.keyboard("{Shift>}");
    await user.click(screen.getByRole("button", { name: "Comment on line 42" }));
    await user.keyboard("{/Shift}");

    const box = screen.getByRole("textbox", { name: "Comment on Lines 41–42" });
    expect(box).toHaveFocus();
    await user.type(box, "Why both?{Meta>}{Enter}{/Meta}");

    expect(onComment).toHaveBeenCalledWith(
      commentMessage(
        { path: "/r/x.py", change: 1, side: "new", start: 41, end: 42 },
        "-b\n+c\n+d",
        "Why both?",
      ),
    );
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("shows a thread under its last line, takes a reply and resolves it for this session (AC-265.17)", async () => {
    const onComment = vi.fn(() => Promise.resolve());
    const thread: ReviewThread = {
      key: "u-3",
      anchor: { path: "/r/x.py", change: 1, side: "new", start: 41, end: 42 },
      messages: [
        { key: "u-3", author: "you", text: "Why both?", pending: false },
        { key: "a-4", author: "claude", text: "**Because** of tests.", pending: false },
      ],
      waiting: false,
    };
    render(<Harness threads={[thread]} onComment={onComment} />);

    const shown = screen.getByRole("region", { name: "Review thread on Lines 41–42" });
    expect(within(shown).getByText("Because").tagName).toBe("STRONG");
    await userEvent.click(within(shown).getByRole("button", { name: "Reply…" }));
    await userEvent.type(within(shown).getByRole("textbox"), "Ok{Control>}{Enter}{/Control}");
    expect(onComment).toHaveBeenCalledWith(
      "Reply to review comment on `/r/x.py`, change 1, lines 41-42:\n\nOk",
    );

    await userEvent.click(within(shown).getByRole("button", { name: "Resolve" }));
    expect(within(shown).queryByText("Why both?")).toBeNull();
    expect(within(shown).getByText("Resolved")).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(resolvedKey("s1")) ?? "[]")).toEqual(["u-3"]);
  });

  it("is read-only without a way to send, and keeps a thread whose lines left the diff (AC-265.16, AC-265.17)", () => {
    const gone: ReviewThread = {
      key: "u-9",
      anchor: { path: "/r/x.py", change: 1, side: "new", start: 90, end: 90 },
      messages: [{ key: "u-9", author: "you", text: "Old remark", pending: false }],
      waiting: true,
    };
    render(<Harness threads={[gone]} />);

    expect(screen.queryByRole("button", { name: /^Comment on/ })).toBeNull();
    expect(screen.getByText("On lines this change no longer shows")).toBeInTheDocument();
    expect(screen.getByText("Waiting for Claude")).toBeInTheDocument();
  });
});

describe("ReviewDiff (conversation)", () => {
  const thread: ReviewThread = {
    key: "u-5",
    anchor: { path: "/r/x.py", change: 1, side: "new", start: 41, end: 41 },
    messages: [
      { key: "u-5", author: "you", text: "Why c?", pending: false },
      { key: "a-6", author: "claude", text: "For the tests.", pending: false },
      { key: "u-7", author: "you", text: "Ok", pending: true },
    ],
    waiting: false,
  };

  it("lays out a thread like a GitHub conversation: who wrote each comment, Claude as Agent", () => {
    render(<Harness threads={[thread]} onComment={vi.fn(() => Promise.resolve())} />);

    const shown = screen.getByRole("region", { name: "Review thread on Line 41" });
    expect(within(shown).getByText("· 3 comments")).toBeInTheDocument();
    const comments = within(shown).getAllByRole("listitem");
    expect(comments.map((item) => item.textContent)).toEqual([
      "YYoucommentedWhy c?",
      "CClaudeAgentrepliedFor the tests.",
      "YYousending…Ok",
    ]);
    expect(within(shown).getByRole("button", { name: "Reply…" })).toBeInTheDocument();
    expect(within(shown).getByRole("button", { name: "Resolve" })).toBeInTheDocument();
  });

  it("folds a resolved thread to its header, shows it again and reopens it", async () => {
    render(<Harness threads={[thread]} onComment={vi.fn(() => Promise.resolve())} />);
    const shown = screen.getByRole("region", { name: "Review thread on Line 41" });
    await userEvent.click(within(shown).getByRole("button", { name: "Resolve" }));

    expect(within(shown).getByText(/conversation on Line 41/)).toBeInTheDocument();
    expect(within(shown).queryByRole("listitem")).toBeNull();
    expect(within(shown).queryByRole("button", { name: "Reply…" })).toBeNull();

    await userEvent.click(within(shown).getByRole("button", { name: "Show" }));
    expect(within(shown).getAllByRole("listitem")).toHaveLength(3);
    expect(within(shown).queryByRole("button", { name: "Reply…" })).toBeNull();

    await userEvent.click(within(shown).getByRole("button", { name: "Reopen" }));
    expect(within(shown).getByRole("button", { name: "Resolve" })).toBeInTheDocument();
    expect(within(shown).getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("ReviewBubble (chat)", () => {
  it("reads a review comment in the chat and opens its file in the review (AC-265.18)", async () => {
    const openFile = vi.fn();
    const text = commentMessage(
      { path: "/r/src/app.py", change: 1, side: "new", start: 3, end: 3 },
      "+x",
      "Rename it",
    );
    render(
      <OpenReviewFileContext.Provider value={openFile}>
        <ReviewBubble text={text} />
      </OpenReviewFileContext.Provider>,
    );

    expect(screen.getByText("app.py")).toBeInTheDocument();
    expect(screen.getByText("Rename it")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open in review" }));
    expect(openFile).toHaveBeenCalledWith("/r/src/app.py");
  });
});
