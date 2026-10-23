import { describe, expect, it } from "vitest";

import { asBare, bareRef, isBare, looksLikeJson, parseLoose, stringifyLoose } from "./looseJson";

describe("loose JSON (scenario bodies)", () => {
  const body = '{"event_type":"FETCH","ids":["$INPUTS.external_ref"],"minutes":$INPUTS.minutes}';

  it("loose json reads a bare reference as a marked value and writes it back bare", () => {
    const read = parseLoose(body);
    expect(read.ok).toBe(true);
    if (!read.ok) return;
    const value = read.value as Record<string, unknown>;
    expect(value.ids).toEqual(["$INPUTS.external_ref"]);
    expect(isBare(value.minutes)).toBe(true);
    expect(bareRef(value.minutes as string)).toBe("$INPUTS.minutes");
    expect(stringifyLoose(read.value)).toBe(body);
  });

  it("loose json indents for editing and keeps the bare reference", () => {
    const read = parseLoose(body);
    if (!read.ok) throw new Error("does not parse");
    const pretty = stringifyLoose(read.value, true);
    expect(pretty).toContain('\n  "minutes": $INPUTS.minutes\n');
    const again = parseLoose(pretty);
    expect(again.ok && stringifyLoose(again.value)).toBe(body);
  });

  it("loose json leaves a dollar inside a string alone", () => {
    const text = '{"price":"$5","order_id":"$CTX.order_id"}';
    const read = parseLoose(text);
    expect(read.ok && stringifyLoose(read.value)).toBe(text);
  });

  it("loose json says why a text does not parse", () => {
    const read = parseLoose('{\n  "a": 1,\n  "b": \n}');
    expect(read.ok).toBe(false);
    if (read.ok) return;
    expect(read.message).not.toBe("");
  });

  it("loose json tells a JSON body from plain text", () => {
    expect(looksLikeJson(body)).toBe(true);
    expect(looksLikeJson("demo-events")).toBe(false);
    expect(looksLikeJson("{not json")).toBe(false);
    expect(stringifyLoose({ n: asBare("$INPUTS.n") })).toBe('{"n":$INPUTS.n}');
  });
});
