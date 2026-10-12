import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import { API_TARGET, DEV_ORIGINS, DEV_SERVER, apiProxy } from "./devProxy";

type Configure = NonNullable<ReturnType<typeof apiProxy>["/api"]["configure"]>;

function proxied(origin: string | undefined, target?: string) {
  const emitter = new EventEmitter();
  const headers = new Map<string, string>(origin === undefined ? [] : [["origin", origin]]);
  const request = {
    getHeader: vi.fn((name: string) => headers.get(name)),
    setHeader: vi.fn((name: string, value: string) => headers.set(name, value)),
    removeHeader: vi.fn((name: string) => headers.delete(name)),
  };
  const { configure } = apiProxy(target)["/api"];
  if (configure === undefined) throw new Error("the proxy has no configure hook");
  configure(emitter as unknown as Parameters<Configure>[0], {});
  emitter.emit("proxyReq", request);
  return headers;
}

describe("apiProxy", () => {
  it("sends /api to hub web on 127.0.0.1:7420 with its own Host", () => {
    const proxy = apiProxy();

    expect(Object.keys(proxy)).toEqual(["/api"]);
    expect(proxy["/api"].target).toBe(API_TARGET);
    expect(API_TARGET).toBe("http://127.0.0.1:7420");
    expect(proxy["/api"].changeOrigin).toBe(true);
  });

  it.each(DEV_ORIGINS)("rewrites the dev server's own origin %s to the API's", (origin) => {
    expect(proxied(origin).get("origin")).toBe(API_TARGET);
  });

  it("rewrites the dev server's origin to the target it is given", () => {
    expect(proxied("http://127.0.0.1:5173", "http://127.0.0.1:8001").get("origin")).toBe(
      "http://127.0.0.1:8001",
    );
  });

  it.each(["http://attacker.example", "null", "http://127.0.0.1:5174", "https://127.0.0.1:5173"])(
    "drops a foreign origin %s, so the API refuses the learning actions",
    (origin) => {
      expect(proxied(origin).has("origin")).toBe(false);
    },
  );

  it("adds no origin when the browser sent none", () => {
    expect(proxied(undefined).has("origin")).toBe(false);
  });

  it("lists the dev server's loopback origins only", () => {
    expect(DEV_ORIGINS).toEqual(["http://127.0.0.1:5173", "http://localhost:5173"]);
  });

  it("serves the dev app on loopback only, on a fixed port", () => {
    expect(DEV_SERVER).toEqual({ host: "127.0.0.1", port: 5173, strictPort: true });
  });
});
