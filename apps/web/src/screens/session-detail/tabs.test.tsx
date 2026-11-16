import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  aPage,
  aProblem,
  aSession,
  aSessionCost,
  aSessionFile,
  aTimelineEvent,
  anId,
  at,
  renderWithApi,
} from "../../testing/builders";
import { CostTab } from "./CostTab";
import { FilesTab, fileStatus } from "./FilesTab";
import { Header } from "./Header";
import { RawTab } from "./RawTab";

const ID = anId(1, "5091b986");
const BASE = `/api/v1/sessions/${ID}`;

describe("FilesTab", () => {
  it("lists paths with op badges and jumps to the events that touched a file", async () => {
    const onJump = vi.fn();
    renderWithApi(
      <FilesTab
        sessionId={ID}
        events={[aTimelineEvent({ seq: 3, agent: "reviewer", payload: { tool: "Edit" } })]}
        onJump={onJump}
      />,
      {
        routes: {
          [`${BASE}/files`]: aPage([
            aSessionFile({ path: "a/edited.py", ops: ["read", "written"], repo: null }),
            aSessionFile({ path: "a/read.py", ops: ["read"], event_ids: [] }),
          ]),
        },
      },
    );

    expect(
      await screen.findByText("2 files · 1 edited · 0 created · 1 read only"),
    ).toBeInTheDocument();
    expect(screen.getByText("outside a repo")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Jump to timeline" }));
    expect(onJump).toHaveBeenCalledWith(anId(3, "0192aaaa"));
    fireEvent.click(screen.getByRole("button", { name: /a\/read\.py/ }));
    expect(screen.getByText("Read only · no changes")).toBeInTheDocument();
    expect(fileStatus({ ops: ["created"] })).toBe("created");
  });

  it("shows the empty and error states", async () => {
    const empty = renderWithApi(<FilesTab sessionId={ID} events={[]} onJump={vi.fn()} />, {
      routes: { [`${BASE}/files`]: aPage([]) },
    });
    expect(await screen.findByText("No files touched")).toBeInTheDocument();
    empty.unmount();

    renderWithApi(<FilesTab sessionId={ID} events={[]} onJump={vi.fn()} />, {
      routes: { [`${BASE}/files`]: aProblem({ status: 500, title: "Boom" }) },
    });
    expect(await screen.findByText("Could not load the files")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  });
});

describe("CostTab", () => {
  it("shows totals, the run share and flags a turn over three times the median", async () => {
    renderWithApi(<CostTab sessionId={ID} />, {
      routes: {
        [`${BASE}/cost`]: aSessionCost({
          run_total_usd: "2.0000",
          total_usd: "1.0000",
          unknown_reason: "Cost unknown: model x has no price",
          series: [
            { turn: 1, input: 10, output: 1, cache_read: 0, cache_write: 0, cost_usd: "0.0100" },
            { turn: 2, input: 10, output: 1, cache_read: 0, cache_write: 0, cost_usd: "0.0100" },
            { turn: 3, input: 900, output: 90, cache_read: 0, cache_write: 0, cost_usd: "0.9800" },
          ],
        }),
      },
    });

    expect(await screen.findByText("this session is 50 % of the run")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText("Cost unknown: model x has no price")).toBeInTheDocument();
  });

  it("shows the transcript-estimate empty state and the error state", async () => {
    const empty = renderWithApi(<CostTab sessionId={ID} />, {
      routes: { [`${BASE}/cost`]: aSessionCost({ series: [], prices_as_of: null, model: null }) },
    });
    expect(
      await screen.findByText(
        "Cost is estimated from transcripts. OpenTelemetry is not connected in this version.",
      ),
    ).toBeInTheDocument();
    empty.unmount();

    renderWithApi(<CostTab sessionId={ID} />, {
      routes: { [`${BASE}/cost`]: aProblem({ status: 500, title: "Boom" }) },
    });
    expect(await screen.findByText("Could not load the cost")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  });
});

describe("RawTab", () => {
  it("shows source ids, conflicts and merged sources, sorts by arrival and opens an event", () => {
    const events = [
      aTimelineEvent({ seq: 1, received_at: at(9), merged_sources: ["claude_code", "transcript"] }),
      aTimelineEvent({
        seq: 2,
        received_at: null,
        latency_ms: null,
        conflict: true,
        source: "transcript",
        source_id: "x".repeat(80),
      }),
    ];
    renderWithApi(<RawTab events={events} timelineRows={1} />);

    expect(screen.getByText("conflict")).toBeInTheDocument();
    expect(screen.getByText("claude_code + transcript")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Received" }));
    const [, firstRow] = screen.getAllByRole("row");
    if (!firstRow) throw new Error("no row");
    fireEvent.click(firstRow);
    expect(screen.getByText(/Canonical event, redacted at ingestion/)).toBeInTheDocument();
  });

  it("says nothing is recorded when the session has no event", () => {
    renderWithApi(<RawTab events={[]} timelineRows={0} />);

    expect(screen.getByText("Nothing has been recorded for this session.")).toBeInTheDocument();
  });
});

describe("Header", () => {
  it("links the run, PR and parent, and shows segments, guard counts and unknown cost", () => {
    renderWithApi(
      <Header
        session={aSession({
          run_id: "a1b2c3d4e5f6",
          step: "implement",
          attempt: 2,
          pr: { number: 69, state: "merged", url: "https://example.com/pr/69" },
          parent_session_id: anId(2, "9c4e12aa"),
          segments: [
            {
              index: 0,
              started_at: at(0),
              ended_at: at(60),
              end_reason: "clear",
              end_inferred: false,
            },
            {
              index: 1,
              started_at: at(120),
              ended_at: null,
              end_reason: null,
              end_inferred: false,
            },
          ],
          guard_denials: 1,
          errors: 2,
          cost_usd: null,
          cost_unknown_reason: "Cost unknown: model x has no price",
          has_transcript: false,
          model: null,
          tokens: null,
        })}
        now={Date.parse(at(600))}
        staleSince={new Date(Date.parse(at(500)))}
      />,
    );

    expect(
      screen.getByRole("link", { name: /Run AGH-48 › implement · attempt 2/ }),
    ).toHaveAttribute("href", "/runs/a1b2c3d4e5f6?step=implement&attempt=2");
    expect(screen.getByRole("link", { name: /PR #69 merged/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Session 9c4e12aa" })).toBeInTheDocument();
    expect(screen.getByText(/2 segments · resumed once/)).toBeInTheDocument();
    expect(screen.getByText(/1 guard event · 2 errors/)).toBeInTheDocument();
    expect(screen.getByText("Cost unknown: model x has no price")).toBeInTheDocument();
    expect(screen.getByText(/Stale · as of/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy link to this session (y)" }));
    expect(screen.getByRole("button", { name: "Link copied" })).toBeInTheDocument();
  });
});
