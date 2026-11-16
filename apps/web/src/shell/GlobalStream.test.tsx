import { act, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { aStreamCounts, renderWithApi } from "../testing/builders";
import { GlobalStreamProvider, useCollectorState, useGlobalStream } from "./GlobalStream";

function Probe() {
  const { counts } = useGlobalStream();
  const { state } = useCollectorState();
  return (
    <p>
      {state} {counts?.approvals_open ?? "none"}
    </p>
  );
}

describe("GlobalStreamProvider", () => {
  it("scopes the stream to the project and ignores malformed counts", () => {
    const { stream } = renderWithApi(
      <GlobalStreamProvider project="agent-hub">
        <Probe />
      </GlobalStreamProvider>,
    );
    const source = stream("/api/v1/events/stream");

    act(() => {
      source.open();
      source.emit("counts", { nope: true });
    });
    expect(screen.getByText("connected none")).toBeInTheDocument();
    expect(source.url).toBe("/api/v1/events/stream?project=agent-hub");

    act(() => {
      source.emit("counts", aStreamCounts({ approvals_open: 5 }));
    });
    expect(screen.getByText("connected 5")).toBeInTheDocument();
  });
});
