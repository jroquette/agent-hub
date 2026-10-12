import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import { API_TARGET, DEV_SERVER, apiProxy } from "./devProxy";

type Configure = NonNullable<ReturnType<typeof apiProxy>["/api"]["configure"]>;

describe("apiProxy", () => {
  it("sends /api to hub web on 127.0.0.1:7420 with its own Host", () => {
    const proxy = apiProxy();

    expect(Object.keys(proxy)).toEqual(["/api"]);
    expect(proxy["/api"].target).toBe(API_TARGET);
    expect(API_TARGET).toBe("http://127.0.0.1:7420");
    expect(proxy["/api"].changeOrigin).toBe(true);
  });

  it("drops the browser's Origin from every proxied request", () => {
    const emitter = new EventEmitter();
    const removeHeader = vi.fn();
    const { configure } = apiProxy()["/api"];
    if (configure === undefined) throw new Error("the proxy has no configure hook");

    configure(emitter as unknown as Parameters<Configure>[0], {});
    emitter.emit("proxyReq", { removeHeader });

    expect(removeHeader).toHaveBeenCalledWith("origin");
  });

  it("serves the dev app on loopback only, on a fixed port", () => {
    expect(DEV_SERVER).toEqual({ host: "127.0.0.1", port: 5173, strictPort: true });
  });
});
